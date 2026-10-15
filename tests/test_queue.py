import asyncio
import csv
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import pandas as pd
from core.captcha import load_captcha_lookup, resolve_captcha
from core.identifiers import normalize_dua, validate_result
from core.job_store import JobStore, RunLock
from core.playwright_processor import PlaywrightDUAProcessor, ExtraStepRequired
from flows.detalles_flow import DetallesFlow
from utils import compute_output_paths, dataset_key


DUAS = ['001-2026-020591', '001-2026-020592', '001-2026-020594', '001-2026-020607']


def html(dua):
    aduana, year, number = dua.split('-')
    return ''.join(f'<span id="{key}">{value}</span>' for key, value in [
        ('span_CODI_ADUAN', aduana), ('span_ANO_PRESE', year), ('span_NUME_CORRE', number)])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'jobs.sqlite3'
        self.store = JobStore(self.path)
        self.paths = compute_output_paths(self.temp.name, 'prueba')
        self.fields = list(DetallesFlow().extract_data('').columns)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def result(self, dua):
        return validate_result(DetallesFlow().extract_data(html(dua)), dua)

    def test_import_accounts_for_duplicates_invalid_and_empty(self):
        self.store.import_values([DUAS[0], '1-2026-20591', None, 'bad', DUAS[1]])
        stats = self.store.summary()
        self.assertEqual(stats['source_rows'], 5)
        self.assertEqual(stats['total'], 4)
        self.assertEqual(stats['invalid'], 2)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM source_rows').fetchone()[0], 5)
        self.store.export(self.paths, self.fields)
        pending = json.loads(Path(self.paths['pending_json']).read_text(encoding='utf-8'))['pending']
        self.assertEqual(sum(len(p['source_rows']) for p in pending), 5)

    def test_import_transaction_rolls_back_entire_sheet(self):
        def values():
            yield DUAS[0]
            raise OSError('read failed')
        with self.assertRaises(OSError):
            self.store.import_values(values())
        self.assertEqual(self.store.summary()['total'], 0)

    def test_empty_import_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.import_values([])
        self.assertEqual(self.store.summary()['total'], 0)

    def test_corrected_input_archives_invalid_row_and_keeps_other_jobs(self):
        self.store.import_values(['bad', DUAS[0]], revision='first')
        self.store.import_values([DUAS[1]], revision='corrected')
        self.assertEqual(self.store.summary()['invalid'], 0)
        self.assertEqual(self.store.summary()['pending'], 2)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM jobs WHERE status='invalid'").fetchone()[0], 1)
        self.store.export(self.paths, self.fields)
        pending = json.loads(Path(self.paths['pending_json']).read_text(encoding='utf-8'))['pending']
        self.assertEqual(len(pending), 2)
        self.assertTrue(all(item['source_rows'] for item in pending))

    def test_abrupt_process_exit_recovers_job_and_releases_lock(self):
        self.store.import_values(DUAS[:2])
        code = '''import sys,os
sys.path.insert(0,sys.argv[1])
from core.job_store import JobStore,RunLock
with RunLock(sys.argv[2]):
    store=JobStore(sys.argv[2])
    store.begin_run()
    store.claim(1)
    job=store.claim(1)
    store.complete(job, {'numero_del_dua': job['dua']})
    os._exit(42)
'''
        result = subprocess.run([sys.executable, '-c', code,
                                 str(Path(__file__).resolve().parents[1] / 'src'), str(self.path)],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 42, result.stderr)
        with RunLock(self.path):
            self.store.begin_run()
            self.assertEqual(self.store.summary()['succeeded'], 1)
            self.assertEqual(self.store.claim(1)['dua'], DUAS[0])

    def test_resume_out_of_order_recovers_missing_lower_rows(self):
        self.store.import_values(DUAS)
        self.store.begin_run()
        first, second = self.store.claim(1), self.store.claim(1)
        self.store.complete(second, self.result(second['dua']))
        self.store.close()
        self.store = JobStore(self.path)
        self.store.begin_run()
        recovered = self.store.claim(1)
        self.assertEqual(recovered['dua'], first['dua'])
        self.assertEqual(self.store.summary()['succeeded'], 1)
        self.assertEqual(self.store.summary()['total'], 4)
        with self.assertRaises(RuntimeError):
            self.store.complete(first, self.result(first['dua']))

    def test_concurrent_claims_across_connections_are_unique(self):
        self.store.import_values(f'001-2026-{i:06}' for i in range(1, 101))
        def worker():
            store = JobStore(self.path)
            jobs = []
            try:
                while job := store.claim(1):
                    jobs.append(job['dua'])
                    store.complete(job, self.result(job['dua']))
            finally:
                store.close()
            return jobs
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = sum(list(pool.map(lambda _: worker(), range(4))), [])
        self.assertEqual(len(jobs), 100)
        self.assertEqual(len(set(jobs)), 100)
        self.assertEqual(self.store.summary()['succeeded'], 100)

    def test_retry_is_fair_and_survives_new_run(self):
        self.store.import_values(DUAS[:2])
        job = self.store.claim(1)
        self.store.retry(job, 'timeout')
        second = self.store.claim(1)
        self.assertEqual(second['dua'], DUAS[1])
        self.store.complete(second, self.result(second['dua']))
        self.assertIsNone(self.store.claim(1))
        retried = self.store.claim(2)
        self.assertEqual(retried['dua'], job['dua'])
        self.store.retry(retried, 'timeout')
        self.store.begin_run()
        self.assertEqual(self.store.claim(1)['dua'], job['dua'])

    def test_result_and_status_rollback_together(self):
        self.store.import_values(DUAS[:1])
        job = self.store.claim(1)
        self.store.db.executescript("""CREATE TRIGGER fail_attempt BEFORE UPDATE ON attempts
            WHEN NEW.outcome='success' BEGIN SELECT RAISE(ABORT, 'disk simulation'); END;""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.complete(job, self.result(job['dua']))
        row = self.store.db.execute('SELECT status,result FROM jobs').fetchone()
        self.assertEqual(tuple(row), ('running', None))
        self.store.begin_run()
        self.assertIsNotNone(self.store.claim(1))

    def test_wrong_dua_never_marks_success(self):
        self.store.import_values(DUAS[:1])
        job = self.store.claim(1)
        with self.assertRaises(ValueError):
            self.store.complete(job, self.result(DUAS[1]))
        self.assertEqual(self.store.summary()['succeeded'], 0)
        with self.assertRaises(ValueError):
            validate_result(pd.DataFrame([{'numero_del_dua': '001'}]), DUAS[0])

    def test_export_failure_keeps_result_and_old_csv(self):
        self.store.import_values(DUAS[:1])
        job = self.store.claim(1)
        self.store.complete(job, self.result(job['dua']))
        output = Path(self.paths['output_csv'])
        output.write_text('original', encoding='utf-8')
        with patch('core.job_store.os.replace', side_effect=PermissionError('Excel abierto')):
            with self.assertRaises(PermissionError):
                self.store.export(self.paths, self.fields)
        self.assertEqual(output.read_text(), 'original')
        self.assertEqual(self.store.summary()['succeeded'], 1)
        self.store.export(self.paths, self.fields)
        self.store.export(self.paths, self.fields)
        with output.open(encoding='utf-8-sig', newline='') as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 1)

    def test_existing_csv_only_migrates_matching_complete_rows(self):
        self.store.import_values(DUAS[:1])
        legacy = Path(self.temp.name) / 'legacy.csv'
        with legacy.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=self.fields)
            writer.writeheader()
            writer.writerows([self.result(DUAS[0]), self.result(DUAS[1])])
            stream.write('001,incomplete\n')
        self.assertEqual(self.store.migrate_csv(legacy, self.fields), 1)
        self.assertEqual(self.store.migrate_csv(legacy, self.fields), 0)
        self.assertEqual(self.store.summary()['succeeded'], 1)

    def test_run_lock_rejects_second_instance(self):
        with RunLock(self.path):
            with self.assertRaises(RuntimeError):
                with RunLock(self.path):
                    pass
        with RunLock(self.path):
            pass

    def test_excel_is_imported_once_and_can_resume_without_it(self):
        from openpyxl import Workbook
        path = Path(self.temp.name) / 'source.xlsx'
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'prueba'
        sheet.append(['NroDUA'])
        for dua in DUAS:
            sheet.append([dua])
        workbook.save(path)
        workbook.close()
        self.store.import_excel(path, 'prueba')
        with patch('openpyxl.load_workbook', side_effect=AssertionError('No volver a leer')):
            self.store.import_excel(path, 'prueba')
        path.unlink()
        self.assertEqual(self.store.import_excel(path, 'prueba')['total'], 4)

    def test_dataset_isolation(self):
        self.assertNotEqual(dataset_key('a.xlsx', 'enero'), dataset_key('b.xlsx', 'enero'))
        self.assertNotEqual(dataset_key('a.xlsx', 'Enero'), dataset_key('a.xlsx', 'enero'))

    def test_captcha_catalog_is_immutable_and_host_independent(self):
        lookup = load_captcha_lookup()
        self.assertEqual(len(lookup), 191)
        self.assertIs(lookup, load_captcha_lookup())
        self.assertEqual(resolve_captcha('https://old.example/TicaExterno/Captcha/images/1.jpg?v=2'), 'polish')
        with self.assertRaises(TypeError):
            lookup['1'] = 'changed'
        with self.assertRaises(ValueError):
            resolve_captcha('/Captcha/images/999.jpg')


class FakePage:
    def set_default_timeout(self, value):
        pass


class FakeContext:
    async def new_page(self):
        return FakePage()

    async def close(self):
        pass


class FakeBrowser:
    async def new_context(self):
        return FakeContext()


class FakeProcessor(PlaywrightDUAProcessor):
    def __init__(self, paths, stop):
        super().__init__({'cant_hilos': 3, 'timeout': 1}, paths, DetallesFlow(), {}, stop)
        self.visited = []
        self.fail = set()
        self.block = False

    async def _block_static(self, page):
        pass

    async def _fetch_result(self, page, row):
        self.visited.append(row['NroDUA'])
        if self.block:
            await asyncio.sleep(60)
        await asyncio.sleep(0.001)
        if row['NroDUA'] in self.fail:
            raise ExtraStepRequired('clic extra')
        return html(row['NroDUA'])


class ProcessorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp.name) / 'jobs.sqlite3')
        self.store.import_values(DUAS)
        self.store.begin_run()
        self.stop = threading.Event()
        self.processor = FakeProcessor(compute_output_paths(self.temp.name, 'prueba'), self.stop)

    async def asyncTearDown(self):
        self.store.close()
        self.temp.cleanup()

    async def test_rounds_revisit_only_unresolved_duas(self):
        self.processor.fail = {DUAS[0]}
        await self.processor._run_round(self.store, FakeBrowser(), 1, lambda s: None)
        self.assertCountEqual(self.processor.visited, DUAS)
        self.assertEqual(self.store.summary()['retry'], 1)
        self.processor.fail.clear()
        await self.processor._run_round(self.store, FakeBrowser(), 2, lambda s: None)
        self.assertEqual(self.processor.visited.count(DUAS[0]), 2)
        self.assertEqual(self.store.summary()['succeeded'], 4)

    async def test_stop_cancels_navigation_and_preserves_all_jobs(self):
        self.processor.block = True
        task = asyncio.create_task(self.processor._run_round(self.store, FakeBrowser(), 1, lambda s: None))
        await asyncio.sleep(0.03)
        self.stop.set()
        await asyncio.wait_for(task, timeout=2)
        self.assertEqual(self.store.summary()['running'], 0)
        self.assertEqual(self.store.summary()['pending'], 4)

    async def test_disk_error_is_fatal_and_does_not_drop_claims(self):
        with patch.object(self.store, 'complete', side_effect=OSError('disco lleno')):
            with self.assertRaises(OSError):
                await self.processor._run_round(self.store, FakeBrowser(), 1, lambda s: None)
        self.assertEqual(self.store.summary()['succeeded'], 0)
        self.assertEqual(self.store.summary()['pending'], 4)

    async def test_context_creation_error_stays_retryable(self):
        class BadBrowser:
            async def new_context(self):
                raise RuntimeError('browser disconnected')
        await self.processor._run_round(self.store, BadBrowser(), 1, lambda s: None)
        self.assertEqual(self.store.summary()['retry'], 4)
        self.assertEqual(self.store.summary()['running'], 0)


if __name__ == '__main__':
    unittest.main()
