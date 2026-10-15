"""Estilos compartidos de la interfaz Tk; sin dependencias visuales externas."""
from tkinter import ttk

BG = '#DEE4EC'
SURFACE = '#EDF1F6'
INK = '#182B45'
MUTED = '#607087'
ACCENT = '#126A78'
LINE = '#8797AB'
SUCCESS = '#17724C'
WARNING = '#946200'
ERROR = '#BC3545'


def palette(dark=False):
    return dict(BG='#1E1E1E', SURFACE='#252526', INK='#E4E4E4', MUTED='#ACB4BE',
                ACCENT='#62B7E8', LINE='#56616D', SUCCESS='#89D185', WARNING='#E9C46A', ERROR='#F48771') if dark else dict(
        BG=BG, SURFACE=SURFACE, INK=INK, MUTED=MUTED, ACCENT=ACCENT, LINE=LINE,
        SUCCESS=SUCCESS, WARNING=WARNING, ERROR=ERROR)


def apply_theme(window, dark=False):
    colors = palette(dark)
    BG, SURFACE, INK, MUTED, ACCENT, LINE = (colors[key] for key in
        ('BG', 'SURFACE', 'INK', 'MUTED', 'ACCENT', 'LINE'))
    window.configure(background=BG)
    style = ttk.Style(window)
    style.theme_use('clam')
    style.configure('.', font=('Segoe UI', 9), background=BG, foreground=INK)
    style.configure('TFrame', background=BG)
    style.configure('Card.TFrame', background=SURFACE)
    style.configure('TLabel', background=BG, foreground=INK)
    style.configure('Card.TLabel', background=SURFACE)
    style.configure('Muted.TLabel', foreground=MUTED)
    style.configure('Hint.TLabel', background=SURFACE, foreground=MUTED, font=('Segoe UI', 9))
    style.configure('TButton', background='#C7D2E0', foreground=INK, bordercolor='#64758B', padding=(10, 5),
                    relief='raised', borderwidth=1, lightcolor='#DCE4EF', darkcolor='#64758B',
                    focusthickness=1, focuscolor=ACCENT)
    style.map('TButton', background=[('disabled', '#DBE1E9'), ('pressed', '#A9BACF'), ('active', '#B8C8DB')],
              foreground=[('disabled', '#788596')])
    style.configure('Primary.TButton', background=ACCENT, foreground='white',
                    bordercolor='#084B58', font=('Segoe UI', 9, 'bold'), padding=(14, 6))
    style.map('Primary.TButton', background=[('disabled', '#DAE2EA'), ('active', '#076A75')],
              foreground=[('disabled', '#77869A'), ('!disabled', 'white')])
    style.configure('Stop.TButton', background='#A53F35', foreground='white', bordercolor='#7A2B25',
                    font=('Segoe UI', 9, 'bold'), padding=(12, 6))
    style.map('Stop.TButton', background=[('disabled', '#DBE1E9'), ('active', '#C24E42')],
              foreground=[('disabled', '#788596'), ('!disabled', 'white')])
    style.configure('TEntry', fieldbackground=SURFACE, padding=4, bordercolor=LINE)
    style.map('TEntry', fieldbackground=[('readonly', '#F7F9FC')], foreground=[('readonly', INK)])
    style.configure('TCombobox', padding=3, fieldbackground=SURFACE, bordercolor=LINE)
    style.map('TCombobox', fieldbackground=[('readonly', SURFACE)])
    style.configure('TSpinbox', padding=3, fieldbackground=SURFACE, bordercolor=LINE)
    style.configure('TCheckbutton', background=SURFACE)
    style.map('TCheckbutton', background=[('active', SURFACE)])
    style.configure('TNotebook', background=BG, borderwidth=0, tabmargins=(0, 0, 0, 4))
    style.configure('TNotebook.Tab', padding=(14, 5), background='#C7D2E0', foreground=INK)
    style.map('TNotebook.Tab', background=[('selected', SURFACE)],
              foreground=[('selected', ACCENT)])
    style.configure('Horizontal.TProgressbar', troughcolor='#E7EDF4', background=ACCENT,
                    borderwidth=0, lightcolor=ACCENT, darkcolor=ACCENT, thickness=10)
    style.configure('TSeparator', background=LINE)
    style.configure('TLabelframe', background=SURFACE, bordercolor=LINE, relief='solid', borderwidth=1)
    style.configure('TLabelframe.Label', background=BG, foreground=INK, font=('Segoe UI', 9, 'bold'))
    style.configure('Treeview', background=SURFACE, fieldbackground=SURFACE, rowheight=30, borderwidth=0)
    style.configure('Treeview.Heading', padding=(8, 8), font=('Segoe UI', 10, 'bold'))
    style.map('Treeview', background=[('selected', '#DDF0F2')], foreground=[('selected', INK)])
    if not dark:
        style.configure('Treeview.Heading', background='#C7D2E0', foreground=INK, bordercolor=LINE)
        style.map('Treeview.Heading', background=[('active', '#B8C8DB')])
        for name in ('TEntry', 'TCombobox', 'TSpinbox'):
            style.configure(name, foreground=INK, insertcolor=INK, arrowcolor=INK, lightcolor=LINE, darkcolor=LINE)
            style.map(name, fieldbackground=[('readonly', SURFACE), ('disabled', '#DBE1E9')],
                      foreground=[('disabled', MUTED), ('!disabled', INK)],
                      selectbackground=[('!disabled', '#B8DCE1')], selectforeground=[('!disabled', INK)])
        style.configure('TCheckbutton', indicatorbackground=SURFACE, indicatorforeground=INK)
        style.map('TCheckbutton', indicatorbackground=[('selected', '#B8DCE1'), ('!selected', SURFACE)],
                  foreground=[('disabled', MUTED), ('!disabled', INK)])
        style.configure('Vertical.TScrollbar', background='#C7D2E0', troughcolor=BG, arrowcolor=INK)
    if dark:
        for name in ('TButton', 'TNotebook.Tab', 'Treeview.Heading'):
            style.configure(name, background='#3C424A', foreground=INK, bordercolor=LINE,
                            lightcolor=LINE, darkcolor=LINE)
        style.map('TButton', background=[('disabled', '#2D3034'), ('pressed', '#505B68'), ('active', '#485361')],
                  foreground=[('disabled', '#858B94'), ('!disabled', INK)])
        for name, base, hover in [('Primary.TButton', '#096DAD', '#1686C7'),
                                  ('Stop.TButton', '#A83838', '#C44A4A')]:
            style.configure(name, background=base, bordercolor=LINE)
            style.map(name, background=[('disabled', '#2D3034'), ('active', hover), ('!disabled', base)],
                      foreground=[('disabled', '#858B94'), ('!disabled', '#FFFFFF')])
        style.map('TNotebook.Tab', background=[('selected', SURFACE), ('active', '#41464E')],
                  foreground=[('selected', ACCENT), ('!selected', INK)])
        style.map('Treeview', background=[('selected', '#164F78')], foreground=[('selected', '#FFFFFF')])
        style.map('Treeview.Heading', background=[('active', '#485361')])
        style.configure('Horizontal.TProgressbar', troughcolor='#363B42', background='#1686C7')
        for name in ('TEntry', 'TCombobox', 'TSpinbox'):
            style.configure(name, fieldbackground='#313337', foreground=INK, arrowcolor=INK,
                            insertcolor=INK, lightcolor=LINE, darkcolor=LINE)
            style.map(name, fieldbackground=[('readonly', '#313337'), ('disabled', '#292B2F')],
                      foreground=[('disabled', '#858B94'), ('!disabled', INK)],
                      selectbackground=[('!disabled', '#164F78')], selectforeground=[('!disabled', '#FFFFFF')])
        style.configure('TCheckbutton', indicatorbackground='#3C424A', indicatorforeground=INK)
        style.map('TCheckbutton', indicatorbackground=[('selected', '#096DAD'), ('!selected', '#3C424A')],
                  foreground=[('disabled', '#858B94'), ('!disabled', INK)])
        style.configure('Vertical.TScrollbar', background='#50555D', troughcolor=BG, arrowcolor=INK)
    window.option_add('*TCombobox*Listbox.background', SURFACE)
    window.option_add('*TCombobox*Listbox.foreground', INK)
    window.option_add('*TCombobox*Listbox.selectBackground', '#164F78' if dark else '#B8DCE1')
    return colors
