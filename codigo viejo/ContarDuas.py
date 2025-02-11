import os
import pandas as pd

# Obtener la ruta del directorio actual donde está el script
current_dir = os.path.dirname(os.path.abspath(__file__))

# Ruta del archivo Excel
excel_file_path = os.path.join(current_dir, "Detalle DUAS_sin registro_fechas.xlsx")

# Cargar el archivo Excel
df_duas = pd.read_excel(excel_file_path)

# Filtrar las filas que contienen "de mar. 2024" (independientemente del día de la semana)
df_duas_march = df_duas[df_duas['Fecha DUA'].str.contains(r'de mar')]

# Contar cuántas filas hay de marzo
dua_count = df_duas_march.shape[0]

# Mostrar el resultado
print(f"Hay {dua_count} DUAs de marzo en el archivo Excel.")
