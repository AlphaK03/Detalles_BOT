"""Confirma el nombre y muestra si se creará una tabla o se ampliará una existente."""
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox

from core.catalog import table_name


class ImportNameDialog(simpledialog.Dialog):
    def __init__(self, parent, initial):
        self.catalog = parent.catalog
        self.colors = parent.colors
        self.name = tk.StringVar(master=parent, value=initial)
        self.target = None
        self.valid_name = False
        super().__init__(parent, 'Confirmar tabla de destino')

    def body(self, master):
        self.configure(background=self.colors['BG'])
        master.configure(background=self.colors['BG'])
        ttk.Label(master, text='Confirma o edita el nombre de la tabla:').pack(anchor='w', padx=10, pady=(10, 6))
        entry = ttk.Entry(master, textvariable=self.name, width=44)
        entry.pack(fill='x', padx=10)
        entry.selection_range(0, 'end')
        self.hint = ttk.Label(master, wraplength=360, style='Muted.TLabel')
        self.hint.pack(fill='x', padx=10, pady=12)
        self.name.trace_add('write', self.refresh)
        self.refresh()
        return entry

    def buttonbox(self):
        bar = ttk.Frame(self, padding=(15, 0, 15, 12))
        bar.pack(fill='x')
        ttk.Button(bar, text='Cancelar', command=self.cancel).pack(side='left')
        self.confirm = ttk.Button(bar, command=self.ok, style='Primary.TButton')
        self.confirm.pack(side='right')
        self.bind('<Return>', self.ok)
        self.bind('<Escape>', self.cancel)
        self.refresh()

    def refresh(self, *args):
        try:
            self.target = self.catalog.find_by_name(self.name.get())
            self.valid_name = True
            text = (f'La tabla «{self.target["name"]}» ya existe. Se añadirán solo DUAs nuevos; '
                    'sus resultados y pendientes se conservan.' if self.target else
                    'Se creará una tabla nueva con este nombre. Usa el mismo nombre para las siguientes cargas del mes.')
        except ValueError as exc:
            self.valid_name = False
            text = str(exc)
        self.hint.configure(text=text)
        if hasattr(self, 'confirm'):
            self.confirm.configure(text='Agregar DUAs' if self.target else 'Crear tabla',
                                   state='normal' if self.valid_name else 'disabled')

    def validate(self):
        if not self.valid_name:
            return False
        current = self.catalog.find_by_name(self.name.get())
        if (current['id'] if current else None) != (self.target['id'] if self.target else None):
            self.refresh()
            messagebox.showinfo('Destino actualizado', 'La tabla de destino cambió. Revisa el mensaje y confirma de nuevo.', parent=self)
            return False
        return True

    def apply(self):
        self.result = (table_name(self.name.get()), self.target['id'] if self.target else None)
