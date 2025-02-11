import pandas as pd

# Cargar el archivo de Excel con la columna 'NroDUA'
excel_path = r'C:/Users/keylo/CHC Consultores/CHC-CONSULTORES - Automatizacion TICA/Datos_Generales/DUAs/Total_DUAS - Import.xlsx'
df_total_duas = pd.read_excel(excel_path, sheet_name='octubre24')

# Cargar el archivo CSV con la columna 'numero_del_dua', omitiendo filas problemáticas
csv_path = r'C:/Users/keylo/CHC Consultores/CHC-CONSULTORES - Automatizacion TICA/Datos_Generales/Datos_Procesados/Talon_BOT/octubre24/Duas_procesados_octubre24.csv'
df_duas_procesados = pd.read_csv(csv_path, on_bad_lines='skip')

# Extraer las columnas relevantes
nro_dua_values = df_total_duas['NroDUA'].astype(str)
numero_del_dua_values = df_duas_procesados['numero_del_dua'].astype(str)

# Filtrar los valores de 'NroDUA' que no están en 'numero_del_dua'
duas_fallidas = df_total_duas[~nro_dua_values.isin(numero_del_dua_values)]

# Guardar los valores faltantes en un nuevo archivo de Excel
output_path = r'C:/Users/keylo/CHC Consultores/CHC-CONSULTORES - Automatizacion TICA/Datos_Generales/DUAs/Total_DUAS - Import_octubre24.xlsx'
with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
    duas_fallidas.to_excel(writer, index=False, sheet_name='DUAs_Fallidas')

print(f"Archivo guardado como '{output_path}' con las DUAs que faltan en el archivo procesado.")
