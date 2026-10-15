"""Consulta local de pendientes. No modifica la cola ni llama al portal."""
import sqlite3
import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from ui.theme import BG, MUTED, INK, SURFACE
from core.messages import pending_reason
from core.job_store import active_revisions


def read_pending(database, search=''):
    uri = Path(database).resolve().as_uri() + '?mode=ro'
    db = sqlite3.connect(uri, uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    try:
        revisions = active_revisions(db)
        marks = ','.join('?' for _ in revisions)
        escaped = search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        pattern = f'%{escaped}%'
        return [dict(row) for row in db.execute(f'''
                SELECT j.id, j.dua, j.status, j.attempts, j.last_error, j.error_kind,
                    (SELECT raw FROM source_rows s WHERE s.job_id=j.id
                     ORDER BY row_number LIMIT 1) AS original
                FROM jobs j WHERE j.status!='succeeded'
                AND (j.status!='invalid' OR EXISTS (SELECT 1 FROM source_rows s
                    WHERE s.job_id=j.id AND s.revision IN ({marks})))
                AND (COALESCE(j.dua,'') LIKE ? ESCAPE '\\' OR j.last_error LIKE ? ESCAPE '\\')
                ORDER BY j.rowid LIMIT 201
            ''', (*revisions, pattern, pattern))]
    finally:
        db.close()


class PendingWindow(tk.Toplevel):
    def __init__(self, parent, database):
        super().__init__(parent)
        self.database = database
        self.title('DUAs pendientes')
        self.configure(background=BG)
        self.geometry('920x540')
        self.minsize(700, 420)
        self.transient(parent)
        self._rows = {}
        body = ttk.Frame(self, padding=20)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Pendientes de este archivo', font=('Segoe UI', 17, 'bold')).pack(anchor='w')
        ttk.Label(body, text='Selecciona una fila para ver el último error. Retoma las consultas desde la pantalla principal.',
                  foreground=MUTED).pack(anchor='w', pady=(4, 12))
        filters = ttk.Frame(body)
        filters.pack(fill='x', pady=(0, 10))
        ttk.Label(filters, text='Buscar DUA o error').pack(side='left', padx=(0, 10))
        self.search = tk.StringVar()
        entry = ttk.Entry(filters, textvariable=self.search)
        entry.pack(side='left', fill='x', expand=True)
        entry.bind('<Return>', lambda event: self.refresh())
        ttk.Button(filters, text='Buscar / actualizar', command=self.refresh).pack(side='left', padx=(10, 0))
        grid = ttk.Frame(body)
        grid.pack(fill='both', expand=True)
        grid.rowconfigure(0, weight=1)
        grid.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(grid, columns=('dua', 'status', 'attempts'), show='headings', selectmode='browse')
        for key, title, width in [('dua', 'DUA / entrada original', 330),
                                  ('status', 'Estado', 220), ('attempts', 'Intentos', 80)]:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=80)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(grid, orient='vertical', command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind('<<TreeviewSelect>>', self._select)
        self.count = ttk.Label(body, foreground=MUTED)
        self.count.pack(anchor='w', pady=(6, 8))
        self.detail = ScrolledText(body, height=4, state='disabled', wrap='word',
                                   background=SURFACE, foreground=INK, font=('Segoe UI', 10), relief='flat')
        self.detail.pack(fill='x')
        self.refresh()

    def refresh(self):
        try:
            rows = read_pending(self.database, self.search.get().strip())
        except (OSError, sqlite3.Error) as exc:
            self.count.config(text=f'No se pudo leer la lista: {exc}')
            return
        self.tree.delete(*self.tree.get_children())
        self._rows = {}
        states = {'pending': 'Por consultar', 'running': 'En consulta', 'retry': 'Para reintentar',
                  'invalid': 'Revisar en Excel'}
        for index, row in enumerate(rows[:200]):
            key = str(index)
            self._rows[key] = row
            self.tree.insert('', 'end', iid=key, values=(row['dua'] or row['original'] or '(vacío)',
                                                       states.get(row['status'], row['status']), row['attempts']))
        self.count.config(text=('Primeros 200 pendientes. Usa la búsqueda para encontrar uno concreto.'
                                if len(rows) > 200 else f'{len(rows)} pendientes encontrados.'))
        self._set_detail('Selecciona un DUA para revisar su último error.' if rows else 'No hay pendientes que mostrar.')

    def _select(self, event=None):
        selection = self.tree.selection()
        if selection and selection[0] in self._rows:
            row = self._rows[selection[0]]
            self._set_detail(pending_reason(row['error_kind'], row['last_error']) if row['last_error']
                             else 'Sin errores registrados. Pendiente de consulta.')

    def _set_detail(self, text):
        self.detail.config(state='normal')
        self.detail.delete('1.0', 'end')
        self.detail.insert('end', text)
        self.detail.config(state='disabled')
