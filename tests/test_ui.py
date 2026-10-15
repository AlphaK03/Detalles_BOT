"""Integración de Tk y su hilo de control; sin tráfico hacia el portal."""
import logging
import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from openpyxl import Workbook
from core.identifiers import validate_result
from core.job_store import JobStore
from flows.detalles_flow import DetallesFlow
from ui.app import App
from ui.pending import PendingWindow, read_pending
from ui.database_manager import DatabaseWindow


class UITests(unittest.TestCase):
    def test_import_worker_queue_and_final_counter(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'entrada.xlsx'
            database = root / 'jobs.sqlite3'
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = 'prueba'
            sheet.append(['NroDUA'])
            sheet.append(['001-2026-020591'])
            sheet.append(['001-2026-020592'])
            workbook.save(source)
            workbook.close()

            def fake_run(processor, store, callback):
                store.begin_run()
                job = store.claim(1)
                text = ''.join(f'<span id="{key}">{value}</span>' for key, value in [
                    ('span_CODI_ADUAN', '001'), ('span_ANO_PRESE', '2026'), ('span_NUME_CORRE', '020591')])
                store.complete(job, validate_result(DetallesFlow().extract_data(text), job['dua']))
                job = store.claim(1)
                store.retry(job, 'caso pendiente', 'extra_step')
                callback(store.summary())
                store.export(processor.output_paths, processor.fields)

            with patch('ui.app.load_machine_config', return_value={'output_base_path': str(root / 'out')}), \
                    patch('ui.app.load_session', return_value={'input_file_path': str(source), 'sheet_name': 'prueba'}), \
                    patch('ui.app.save_session'), patch('ui.app.setup_logging'), \
                    patch('ui.app.save_machine_config') as save_config, \
                    patch('ui.app.get_catalog_folder', return_value=str(root / 'queues')), \
                    patch('ui.app.ImportNameDialog') as name_dialog, \
                    patch('ui.app.messagebox.showinfo'), patch('ui.app.messagebox.showerror') as errors, \
                    patch('ui.app.PlaywrightDUAProcessor.run', fake_run):
                try:
                    app = App()
                except tk.TclError as exc:
                    self.skipTest(f'Tk no disponible: {exc}')
                app.withdraw()
                try:
                    name_dialog.return_value.result = None
                    app._import_table()
                    self.assertFalse(app._running)
                    self.assertEqual(app.catalog.list_tables(), [])
                    name_dialog.return_value.result = ('Marzo revisado', None)
                    self.assertTrue(app._dark_var.get())
                    app._dark_var.set(False)
                    self.assertEqual(app.colors['BG'], '#DEE4EC')
                    app._dark_var.set(True)
                    self.assertEqual(app.colors['BG'], '#1E1E1E')
                    app._table_name.set('Marzo revisado')
                    app._import_table()
                    deadline = time.monotonic() + 10
                    while app._running and time.monotonic() < deadline:
                        app.update()
                        time.sleep(0.01)
                    self.assertFalse(app._running)
                    self.assertEqual(app._active_table['name'], 'Marzo revisado')
                    database = app.catalog.database(app._active_table)
                    source.unlink()  # Processing must no longer depend on the Excel.
                    app._param_vars['cant_hilos'].set(2)
                    app._start_processing()
                    save_config.assert_called_once()
                    self.assertEqual(save_config.call_args[0][0]['cant_hilos'], 2)
                    self.assertTrue(save_config.call_args[0][0]['dark_mode'])
                    self.assertEqual(str(app._output_btn.cget('state')), 'disabled')
                    self.assertTrue(all(str(widget.cget('state')) == 'disabled'
                                        for widget, state in app._config_widgets))
                    deadline = time.monotonic() + 10
                    while app._running and time.monotonic() < deadline:
                        app.update()
                        time.sleep(0.01)
                    self.assertFalse(app._running)
                    errors.assert_not_called()
                    self.assertEqual(app._counter_label.cget('text'), '1 / 2')
                    self.assertEqual(app._progress_var.get(), 50)
                    self.assertEqual(app._status_label.cget('text'), 'Finalizado con pendientes')
                    self.assertEqual(app._start_btn.cget('text'), 'Retomar pendientes')
                    self.assertEqual(app._metric_labels['remaining'].cget('text'), '1')
                    self.assertEqual([row['dua'] for row in read_pending(database)], ['001-2026-020592'])
                    self.assertEqual(read_pending(database, '020591'), [])
                    self.assertEqual(read_pending(database, '%'), [])
                    pending = PendingWindow(app, database)
                    try:
                        self.assertEqual(len(pending.tree.get_children()), 1)
                        pending.tree.selection_set('0')
                        pending._select()
                        self.assertIn('paso adicional', pending.detail.get('1.0', 'end'))
                        pending.search.set('020591')
                        pending.refresh()
                        self.assertEqual(len(pending.tree.get_children()), 0)
                    finally:
                        pending.destroy()
                    manager = DatabaseWindow(app)
                    try:
                        self.assertEqual(len(manager.tree.get_children()), 2)
                        manager.filter.set('Pendientes')
                        manager.reset()
                        key = manager.tree.get_children()[0]
                        manager.tree.selection_set(key)
                        manager.select()
                        self.assertIn('paso adicional', manager.detail.cget('text'))
                        with patch('ui.database_manager.messagebox.askyesno', return_value=False):
                            manager.clean()
                        self.assertEqual(app.catalog.read_rows(app._active_table['id'])[0], 2)
                        with patch('ui.database_manager.messagebox.askyesno', return_value=True):
                            manager.clean()
                        self.assertEqual(app.catalog.read_rows(app._active_table['id'])[0], 1)
                    finally:
                        manager.destroy()
                    store = JobStore(database)
                    try:
                        self.assertEqual(store.summary()['retry'], 1)
                    finally:
                        store.close()
                    saved_session = dict(app.session)
                    saved_machine = dict(app.machine)
                    with patch('ui.app.load_session', return_value=saved_session), \
                            patch('ui.app.load_machine_config', return_value=saved_machine), \
                            patch('ui.app.load_workbook', side_effect=AssertionError('Excel must not be reopened')):
                        reopened = App()
                        try:
                            reopened.withdraw()
                            self.assertEqual(reopened._active_table['id'], app._active_table['id'])
                            self.assertEqual(reopened._table_name.get(), 'Marzo revisado')
                            self.assertTrue(reopened._dark_var.get())
                            self.assertEqual(reopened._stats['retry'], 1)
                        finally:
                            logging.getLogger().removeHandler(reopened._log_handler)
                            reopened.destroy()
                finally:
                    logging.getLogger().removeHandler(app._log_handler)
                    app.destroy()


if __name__ == '__main__':
    unittest.main()
