"""Catálogo de tablas guardadas. La identidad deja de depender del Excel."""
import json
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone

from core.job_store import JobStore, RunLock, active_revisions

_ANY_TARGET = object()


def table_name(value):
    name = unicodedata.normalize('NFC', value).strip()
    if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
        raise ValueError('Escribe un nombre de tabla de 1 a 80 caracteres.')
    return name


class TableCatalog:
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / 'catalog.sqlite3'
        with self.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS saved_tables (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL UNIQUE, source_path TEXT NOT NULL,
                source_sheet TEXT NOT NULL, output_name TEXT NOT NULL,
                created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, deleted INTEGER NOT NULL DEFAULT 0
            )''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def database(self, record):
        path = (self.folder / record['filename']).resolve()
        if path.parent != self.folder or path == self.path or path.suffix != '.sqlite3':
            raise ValueError('Ruta de tabla inválida.')
        return path

    def get(self, table_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM saved_tables WHERE id=? AND deleted=0', (table_id,)).fetchone()
        if row is None:
            raise ValueError('La tabla ya no existe. Selecciona otra en el administrador.')
        record = dict(row)
        if not self.database(record).is_file():
            raise FileNotFoundError('No se encuentra la tabla guardada.')
        return record

    def list_tables(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM saved_tables WHERE deleted=0 ORDER BY name_key')]

    def find_by_name(self, name):
        key = table_name(name).casefold()
        with self.connection() as db:
            row = db.execute('SELECT * FROM saved_tables WHERE name_key=? AND deleted=0', (key,)).fetchone()
        return dict(row) if row else None

    def discover_legacy(self):
        """Registra lotes existentes sin abrirlos para escritura ni leer sus Excel."""
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            known = {row[0] for row in db.execute('SELECT filename FROM saved_tables')}
            for path in sorted(self.folder.glob('*.sqlite3')):
                if path == self.path or path.name in known:
                    continue
                source = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)
                try:
                    metadata = {row[0]: json.loads(row[1]) for row in source.execute('SELECT key,value FROM metadata')}
                except (sqlite3.Error, ValueError):
                    continue
                finally:
                    source.close()
                signature = metadata.get('source_signature')
                if not signature or not metadata.get('revision') or metadata.get('catalog_managed'):
                    continue
                source_path, sheet = signature[:2]
                base = table_name(sheet)
                name, index = base, 2
                while db.execute('SELECT 1 FROM saved_tables WHERE name_key=?', (name.casefold(),)).fetchone():
                    name = f'{base[:70]} ({index})'
                    index += 1
                db.execute('''INSERT INTO saved_tables(id,name,name_key,filename,source_path,source_sheet,output_name)
                    VALUES (?,?,?,?,?,?,?)''', (path.stem, name, name.casefold(), path.name, source_path, sheet, sheet))

    def import_excel(self, source, sheet, name, legacy_csv=None, fields=(), expected_target=_ANY_TARGET):
        name = table_name(name)
        if not Path(source).is_file():
            raise FileNotFoundError('Selecciona un Excel existente para importarlo.')
        table_id = uuid.uuid4().hex
        filename = table_id + '.sqlite3'
        database = self.folder / filename
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            target = db.execute('SELECT * FROM saved_tables WHERE name_key=? AND deleted=0', (name.casefold(),)).fetchone()
            if expected_target is not _ANY_TARGET and (target['id'] if target else None) != expected_target:
                raise ValueError('La tabla de destino cambió. Confirma otra vez el nombre antes de importar.')
            if target:
                table_id = target['id']
                database = self.database(target)
                if not database.is_file():
                    raise FileNotFoundError('No se encuentra la tabla guardada. No se modificó la lista.')
            with RunLock(database):
                store = JobStore(database)
                try:
                    # Un import incompleto no aparece en el administrador.
                    with store.transaction() as batch:
                        store._set_meta(batch, 'catalog_managed', True)
                    store.import_excel(source, sheet, append=True)
                    report = store.meta('last_import')
                    if legacy_csv and not target:
                        store.migrate_csv(legacy_csv, fields)
                finally:
                    store.close()
            if not target:
                db.execute('''INSERT INTO saved_tables(id,name,name_key,filename,source_path,source_sheet,output_name)
                    VALUES (?,?,?,?,?,?,?)''', (table_id, name, name.casefold(), filename, str(Path(source).resolve()), sheet, name))
        return {**self.get(table_id), 'import_summary': report, 'appended': bool(target)}

    def rename(self, table_id, name):
        name = table_name(name)
        record = self.get(table_id)
        with RunLock(self.database(record)), self.connection() as db:
            self.get(table_id)
            try:
                db.execute('UPDATE saved_tables SET name=?, name_key=? WHERE id=? AND deleted=0',
                           (name, name.casefold(), table_id))
            except sqlite3.IntegrityError:
                raise ValueError('Ya existe una tabla con ese nombre.') from None
        return self.get(table_id)

    def _backup(self, path):
        folder = self.folder / 'backups'
        folder.mkdir(exist_ok=True)
        backup = folder / f'{path.stem}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%f}-{uuid.uuid4().hex[:6]}.sqlite3'
        source = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        target = sqlite3.connect(backup)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return backup

    def remove_rows(self, table_id, ids=None, succeeded_only=False):
        record = self.get(table_id)
        path = self.database(record)
        with RunLock(path):
            self.get(table_id)
            backup = self._backup(path)
            store = JobStore(path)
            try:
                count = store.remove_jobs(ids, succeeded_only)
            finally:
                store.close()
        return count, str(backup)

    def delete_table(self, table_id):
        record = self.get(table_id)
        path = self.database(record)
        with RunLock(path):
            self.get(table_id)
            with self.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                backup = self._backup(path)
                # Tombstone: no volver a descubrir/importar automáticamente esta tabla.
                db.execute('UPDATE saved_tables SET deleted=1,name_key=? WHERE id=?',
                           ('deleted:' + table_id, table_id))
            # El catálogo ya no expone la tabla incluso si Windows mantiene el archivo abierto.
            try:
                path.unlink()
            except OSError:
                pass  # El registro eliminado impide que el archivo reaparezca al reiniciar.
        return str(backup)

    def read_rows(self, table_id, status='all', search='', offset=0, limit=100):
        record = self.get(table_id)
        db = sqlite3.connect(self.database(record).as_uri() + '?mode=ro', uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            where, args = '1=1', []
            if status == 'pending':
                where += " AND j.status!='succeeded'"
            elif status == 'succeeded':
                where += " AND j.status='succeeded'"
            elif status == 'retry':
                where += " AND j.status='retry'"
            elif status != 'all':
                raise ValueError('Filtro inválido')
            revisions = active_revisions(db)
            marks = ','.join('?' for _ in revisions)
            where += f" AND (j.status!='invalid' OR EXISTS (SELECT 1 FROM source_rows s WHERE s.job_id=j.id AND s.revision IN ({marks})))"
            args.extend(revisions)
            if search:
                pattern = '%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
                where += " AND (COALESCE(j.dua,'') LIKE ? ESCAPE '\\' OR j.last_error LIKE ? ESCAPE '\\')"
                args.extend([pattern, pattern])
            total = db.execute(f'SELECT COUNT(*) FROM jobs j WHERE {where}', args).fetchone()[0]
            rows = db.execute(f'''SELECT j.id,j.dua,j.status,j.attempts,j.last_error,j.error_kind,
                (SELECT raw FROM source_rows s WHERE s.job_id=j.id LIMIT 1) original
                FROM jobs j WHERE {where} ORDER BY j.rowid LIMIT ? OFFSET ?''', [*args, limit, offset])
            return total, [dict(row) for row in rows]
        finally:
            db.close()
