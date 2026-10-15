"""Administrador local de tablas y filas, sin acceso al portal ni al Excel."""
import tkinter as tk
import sqlite3
from tkinter import ttk, messagebox, simpledialog

from core.messages import pending_reason


class DatabaseWindow(tk.Toplevel):
    FILTERS = {'Todas': 'all', 'Pendientes': 'pending', 'Guardadas': 'succeeded', 'Por reintentar': 'retry'}
    STATES = {'pending': 'Pendiente', 'running': 'En curso', 'retry': 'Por reintentar',
              'succeeded': 'Guardado', 'invalid': 'Revisar dato'}

    def __init__(self, parent):
        super().__init__(parent)
        self.app = parent
        self.catalog = parent.catalog
        self.title('Base de datos · Tablas guardadas')
        self.geometry('800x560')
        self.minsize(740, 520)
        self.configure(background=parent.colors['BG'])
        self.transient(parent)
        self.offset = 0
        self.records = []
        self.rows = {}
        self.table = tk.StringVar()
        self.filter = tk.StringVar(value='Todas')
        self.search = tk.StringVar()
        top = ttk.Frame(self, padding=10)
        top.pack(fill='x')
        ttk.Label(top, text='Tabla guardada:').grid(row=0, column=0, sticky='w')
        self.combo = ttk.Combobox(top, textvariable=self.table, state='readonly')
        self.combo.grid(row=0, column=1, sticky='ew', padx=8)
        self.combo.bind('<<ComboboxSelected>>', self.reset)
        top.columnconfigure(1, weight=1)
        ttk.Button(top, text='Abrir tabla', style='Primary.TButton', command=self.use).grid(row=0, column=2)
        ttk.Button(top, text='Renombrar', command=self.rename).grid(row=0, column=3, padx=(6, 0))
        self.info = ttk.Label(self, text='', style='Muted.TLabel', padding=(10, 0))
        self.info.pack(fill='x')
        filters = ttk.Frame(self, padding=10)
        filters.pack(fill='x')
        combo = ttk.Combobox(filters, textvariable=self.filter, values=list(self.FILTERS), state='readonly', width=17)
        combo.pack(side='left')
        combo.bind('<<ComboboxSelected>>', self.reset)
        entry = ttk.Entry(filters, textvariable=self.search, width=26)
        entry.pack(side='left', padx=6)
        entry.bind('<Return>', self.reset)
        ttk.Button(filters, text='Buscar DUA', command=self.reset).pack(side='left')
        ttk.Button(filters, text='Actualizar', command=self.reload).pack(side='right')
        body = ttk.Frame(self, padding=(10, 0))
        body.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(body, columns=('dua', 'state', 'attempts'), show='headings',
                                 selectmode='extended', height=6)
        for name, title, width in [('dua', 'DUA / dato original', 310), ('state', 'Estado', 180), ('attempts', 'Intentos', 80)]:
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, minwidth=60)
        scrollbar = ttk.Scrollbar(body, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self.select)
        self.detail = ttk.Label(self, text='Selecciona una fila para ver su estado.',
                                style='Muted.TLabel', wraplength=740, padding=(10, 6))
        self.detail.pack(fill='x')
        page = ttk.Frame(self, padding=(10, 2))
        page.pack(fill='x')
        self.count = ttk.Label(page)
        self.count.pack(side='left')
        self.next = ttk.Button(page, text='Siguiente', command=lambda: self.move(100))
        self.next.pack(side='right')
        self.previous = ttk.Button(page, text='Anterior', command=lambda: self.move(-100))
        self.previous.pack(side='right', padx=5)
        actions = ttk.Frame(self, padding=10)
        actions.pack(fill='x')
        ttk.Button(actions, text='Eliminar filas elegidas', command=self.remove_selected).pack(side='left')
        ttk.Button(actions, text='Limpiar completadas', command=self.clean).pack(side='left', padx=6)
        ttk.Button(actions, text='Eliminar tabla', style='Stop.TButton', command=self.delete).pack(side='right')
        ttk.Label(self, text='Las eliminaciones piden confirmación y crean un respaldo local.',
                  style='Muted.TLabel', padding=(10, 0, 10, 8)).pack(anchor='w')
        self.reload(parent._active_table['id'] if parent._active_table else None)

    def record(self):
        return next((r for r in self.records if r['name'] == self.table.get()), None)

    def reload(self, selected_id=None):
        current = self.record()
        selected_id = selected_id or (current['id'] if current else None)
        self.records = self.catalog.list_tables()
        self.combo.configure(values=[r['name'] for r in self.records])
        record = next((r for r in self.records if r['id'] == selected_id), self.records[0] if self.records else None)
        self.table.set(record['name'] if record else '')
        self.reset()

    def reset(self, event=None):
        self.offset = 0
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        record = self.record()
        total, rows = 0, []
        if record:
            try:
                total, rows = self.catalog.read_rows(record['id'], self.FILTERS[self.filter.get()],
                                                     self.search.get().strip(), self.offset)
            except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
                messagebox.showerror('Abrir tabla', str(exc), parent=self)
        self.info.configure(text='La tabla está guardada; no necesitas el Excel original.' if record else
                            'No hay tablas. Importa un Excel desde la pantalla principal.')
        for row in rows:
            key = str(row['id'])
            self.rows[key] = row
            self.tree.insert('', 'end', iid=key, values=(row['dua'] or row['original'],
                             self.STATES.get(row['status'], row['status']), row['attempts']))
        self.count.configure(text=f'{self.offset + 1 if rows else 0}–{self.offset + len(rows)} de {total:,} filas')
        self.previous.configure(state='normal' if self.offset else 'disabled')
        self.next.configure(state='normal' if self.offset + len(rows) < total else 'disabled')
        self.detail.configure(text='Selecciona una fila para ver su estado.')

    def select(self, event=None):
        selected = self.tree.selection()
        if not selected:
            return
        row = self.rows[selected[0]]
        text = ('Resultado guardado.' if row['status'] == 'succeeded' else
                'Listo para consultar.' if row['status'] == 'pending' else
                'Consulta en curso.' if row['status'] == 'running' else pending_reason(row['error_kind'], row['last_error']))
        self.detail.configure(text=text)

    def move(self, amount):
        self.offset = max(0, self.offset + amount)
        self.refresh()

    def available(self):
        if self.app._running:
            messagebox.showinfo('Operación en curso', 'Espera a que termine o detén las consultas antes de cambiar las tablas.', parent=self)
            return False
        return self.record() is not None

    def use(self):
        if self.available():
            try:
                self.app._activate_table(self.record())
                self.destroy()
            except (ValueError, OSError) as exc:
                messagebox.showerror('Abrir tabla', str(exc), parent=self)

    def rename(self):
        if not self.available():
            return
        record = self.record()
        name = simpledialog.askstring('Renombrar tabla', 'Nombre de la tabla:', initialvalue=record['name'], parent=self)
        if name is not None:
            self.change(lambda: self.catalog.rename(record['id'], name))

    def change(self, operation):
        try:
            operation()
            self.app._catalog_changed()
            self.reload()
        except Exception as exc:
            messagebox.showerror('No se pudo modificar la tabla', str(exc), parent=self)

    def remove_selected(self):
        if not self.available():
            return
        ids = list(self.tree.selection())
        if not ids:
            return
        record = self.record()
        if messagebox.askyesno('Eliminar filas', f'¿Eliminar {len(ids)} filas de «{record["name"]}»?\n\n'
                              'Los pendientes seleccionados dejarán de consultarse. Los resultados ya obtenidos se conservan para exportar.', parent=self):
            self.change(lambda: self.catalog.remove_rows(record['id'], ids=ids))

    def clean(self):
        if not self.available():
            return
        record = self.record()
        count, _ = self.catalog.read_rows(record['id'], 'succeeded', limit=0)
        if not count:
            messagebox.showinfo('Limpiar completadas', 'No hay filas completadas para limpiar.', parent=self)
            return
        if messagebox.askyesno('Limpiar completadas', f'¿Quitar las {count:,} filas completadas de «{record["name"]}»?\n\n'
                              'Se conservan los pendientes y los resultados obtenidos para futuras exportaciones.', parent=self):
            self.change(lambda: self.catalog.remove_rows(record['id'], succeeded_only=True))

    def delete(self):
        if not self.available():
            return
        record = self.record()
        if messagebox.askyesno('Eliminar tabla', f'¿Eliminar la tabla «{record["name"]}» y todas sus filas?\n\n'
                              'Dejará de estar disponible para consultas. Se crea un respaldo y se conservan los archivos de resultados.', parent=self):
            self.change(lambda: self.catalog.delete_table(record['id']))
