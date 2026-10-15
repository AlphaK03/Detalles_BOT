"""Persistencia y eliminaciones aisladas: solamente datos sintéticos temporales."""
import csv
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from openpyxl import Workbook
from core.catalog import TableCatalog
from core.job_store import JobStore, RunLock
from utils import compute_output_paths


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'test.xlsx'
        wb = Workbook()
        wb.active.title = 'Sheet1'
        for row in [['NroDUA'], ['001-2026-020591'], ['001-2026-020592'], ['dato incorrecto']]:
            wb.active.append(row)
        wb.save(self.source)
        wb.close()
        self.catalog = TableCatalog(self.root / 'queues')

    def imported(self, name='Marzo'):
        return self.catalog.import_excel(self.source, 'Sheet1', name)

    def test_import_rename_reopen_without_excel(self):
        table = self.imported()
        self.source.unlink()
        renamed = self.catalog.rename(table['id'], 'Marzo corregido')
        self.assertEqual(renamed['output_name'], 'Marzo')
        reopened = TableCatalog(self.catalog.folder)
        reopened.discover_legacy()
        self.assertEqual(reopened.get(table['id'])['name'], 'Marzo corregido')
        self.assertEqual(reopened.read_rows(table['id'])[0], 3)
        self.assertEqual(reopened.read_rows(table['id'], search='%')[0], 0)

    def test_names_and_failed_import(self):
        initial = self.imported()
        self.assertEqual(self.imported(' MARZO ')['id'], initial['id'])
        with self.assertRaises(ValueError):
            self.imported(' ')
        with self.assertRaises(KeyError):
            self.catalog.import_excel(self.source, 'missing', 'Fallida')
        self.catalog.discover_legacy()
        self.assertEqual(len(self.catalog.list_tables()), 1)

    def test_cleanup_preserves_pending_and_exported_results(self):
        table = self.imported()
        path = self.catalog.database(table)
        store = JobStore(path)
        try:
            store.begin_run()
            done = store.claim(1)
            store.complete(done, {'numero_del_dua': done['dua']})
            retry = store.claim(1)
            store.retry(retry, 'Timeout 20ms', 'TimeoutError')
        finally:
            store.close()
        removed, backup = self.catalog.remove_rows(table['id'], succeeded_only=True)
        self.assertEqual(removed, 1)
        self.assertTrue(Path(backup).is_file())
        db = sqlite3.connect(backup)
        try:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 3)
        finally:
            db.close()
        store = JobStore(path)
        try:
            self.assertEqual(store.summary()['retry'], 1)
            self.assertEqual(store.summary()['invalid'], 1)
            self.assertEqual(store.db.execute('PRAGMA foreign_key_check').fetchall(), [])
            paths = compute_output_paths(str(self.root / 'out'), 'Marzo', table_id=table['id'])
            store.export(paths, ['numero_del_dua'])
            with open(paths['output_csv'], encoding='utf-8-sig', newline='') as stream:
                self.assertEqual(list(csv.DictReader(stream)), [{'numero_del_dua': done['dua']}])
        finally:
            store.close()
        self.assertEqual(self.catalog.read_rows(table['id'], 'pending')[0], 2)
        removed, _ = self.catalog.remove_rows(table['id'], ids=[retry['id']])
        self.assertEqual(removed, 1)

    def test_lock_protects_processing_from_mutations(self):
        table = self.imported()
        with RunLock(self.catalog.database(table)):
            for action in [lambda: self.catalog.rename(table['id'], 'Otro'),
                           lambda: self.imported(),
                           lambda: self.catalog.remove_rows(table['id'], succeeded_only=True),
                           lambda: self.catalog.delete_table(table['id'])]:
                with self.assertRaises(RuntimeError):
                    action()
        self.assertEqual(self.catalog.read_rows(table['id'])[0], 3)

    def test_delete_table_retains_backup_and_cannot_rediscover(self):
        table = self.imported()
        other = self.imported('Abril')
        with patch.object(Path, 'unlink', side_effect=PermissionError):
            backup = self.catalog.delete_table(table['id'])
        self.assertTrue(Path(backup).exists())
        self.catalog.discover_legacy()
        with self.assertRaises(ValueError):
            self.catalog.get(table['id'])
        self.assertEqual(self.catalog.list_tables()[0]['id'], other['id'])
        self.assertEqual(self.imported('Marzo')['name'], 'Marzo')

    def test_legacy_discovery_reads_no_excel(self):
        path = self.catalog.folder / 'legacy.sqlite3'
        store = JobStore(path)
        store.import_excel(self.source, 'Sheet1')
        store.close()
        before = path.read_bytes()
        self.source.unlink()
        self.catalog.discover_legacy()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.catalog.get('legacy')['name'], 'Sheet1')

    def test_failed_backup_never_deletes_data(self):
        table = self.imported()
        with patch.object(self.catalog, '_backup', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.catalog.remove_rows(table['id'], ids=['001-2026-020591'])
            with self.assertRaises(OSError):
                self.catalog.delete_table(table['id'])
        self.assertEqual(self.catalog.read_rows(table['id'])[0], 3)

    def test_failed_migration_cannot_publish_partial_import(self):
        with patch.object(JobStore, 'migrate_csv', side_effect=ValueError('bad CSV')):
            with self.assertRaises(ValueError):
                self.catalog.import_excel(self.source, 'Sheet1', 'Marzo', 'old.csv', ['numero_del_dua'])
        self.catalog.discover_legacy()
        self.assertEqual(self.catalog.list_tables(), [])

    def test_append_quincena_preserves_results_retries_and_invalids(self):
        table = self.imported('marzo26')
        path = self.catalog.database(table)
        store = JobStore(path)
        try:
            store.begin_run()
            done = store.claim(1)
            store.complete(done, {'numero_del_dua': done['dua']})
            retry = store.claim(1)
            store.retry(retry, 'error de prueba', 'extra_step')
            before = [tuple(row) for row in store.db.execute('SELECT * FROM jobs ORDER BY id')]
        finally:
            store.close()
        other = self.root / 'segunda_quincena.xlsx'
        wb = Workbook()
        wb.active.title = 'marzo26'
        for row in [['NroDUA'], [done['dua']], [retry['dua']], ['001-2026-020593'], ['001-2026-020593']]:
            wb.active.append(row)
        wb.save(other)
        wb.close()
        updated = self.catalog.import_excel(other, 'marzo26', ' MARZO26 ', expected_target=table['id'])
        self.assertEqual(updated['id'], table['id'])
        self.assertEqual(updated['import_summary'], dict(rows=4, added=1, existing=3, invalid=0))
        self.assertEqual(len(self.catalog.list_tables()), 1)
        store = JobStore(path)
        try:
            after = {row['id']: tuple(row) for row in store.db.execute('SELECT * FROM jobs')}
            self.assertTrue(all(after[row[0]] == row for row in before))
            self.assertEqual(store.summary()['total'], 4)
            self.assertEqual(store.summary()['invalid'], 1)
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM imports').fetchone()[0], 2)
            with self.assertRaises(sqlite3.IntegrityError):
                with store.transaction() as db:
                    db.execute("INSERT INTO jobs(id,dua,status) VALUES ('another-id',?,'pending')", (done['dua'],))
        finally:
            store.close()
        self.assertEqual(self.catalog.read_rows(table['id'], 'pending')[0], 3)
        from ui.pending import read_pending
        self.assertEqual(len(read_pending(path)), 3)
        again = self.catalog.import_excel(other, 'marzo26', 'marzo26')
        self.assertEqual(again['import_summary']['added'], 0)
        self.catalog.remove_rows(table['id'], succeeded_only=True)
        again = self.catalog.import_excel(other, 'marzo26', 'marzo26')
        self.assertEqual(again['import_summary']['added'], 0)
        store = JobStore(path)
        try:
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM jobs WHERE dua=?', (done['dua'],)).fetchone()[0], 0)
            paths = compute_output_paths(str(self.root / 'out'), 'marzo26', table_id=table['id'])
            store.export(paths, ['numero_del_dua'])
            with open(paths['output_csv'], encoding='utf-8-sig', newline='') as stream:
                self.assertEqual(list(csv.DictReader(stream)), [{'numero_del_dua': done['dua']}])
        finally:
            store.close()
        april = self.catalog.import_excel(other, 'marzo26', 'abril26')
        self.assertNotEqual(april['id'], table['id'])
        self.assertEqual(april['import_summary']['added'], 3)

    def test_failed_append_rolls_back_and_changed_destination_is_rejected(self):
        table = self.imported()
        path = self.catalog.database(table)
        store = JobStore(path)
        try:
            before = store.summary()
            def broken_values():
                yield '001-2026-020594'
                raise OSError('Error leyendo Excel')
            with self.assertRaises(OSError):
                store.import_values(broken_values(), revision='failed', append=True)
            self.assertEqual(store.summary(), before)
            self.assertIsNone(store.db.execute("SELECT 1 FROM source_rows WHERE revision='failed'").fetchone())
        finally:
            store.close()
        with self.assertRaises(ValueError):
            self.catalog.import_excel(self.source, 'Sheet1', 'Marzo', expected_target=None)
        with self.assertRaises(ValueError):
            self.catalog.import_excel(self.source, 'Sheet1', 'Otra', expected_target=table['id'])


if __name__ == '__main__':
    unittest.main()
