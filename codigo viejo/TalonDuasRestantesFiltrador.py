import pandas as pd

# Rutas de los archivos de Excel
excel_path_total_duas = r'C:/Users/keylo/CHC Consultores/CHC-CONSULTORES - Automatizacion TICA/Datos_Generales/DUAs/Total_DUAS.xlsx'
excel_path_duas_procesados = r'C:/Users/keylo/CHC Consultores/CHC-CONSULTORES - Automatizacion TICA/Datos_Generales/Datos_Procesados/DetalleFixed_BOT/enero25/012025_detalle_DUAs_enero25.xlsx'

# Cargar los archivos de Excel
df_total_duas = pd.read_excel(excel_path_total_duas, sheet_name='enero25')
df_duas_procesados = pd.read_excel(excel_path_duas_procesados, sheet_name='enero25')  # Ajusta el nombre de la hoja si es necesario

# Extraer las columnas relevantes y convertir a string
nro_dua_values = df_total_duas['NroDUA'].astype(str)
numero_del_dua_values = df_duas_procesados['numero_del_dua'].astype(str)

# Filtrar los valores de 'NroDUA' que no están en 'numero_del_dua'
duas_fallidas = df_total_duas[~nro_dua_values.isin(numero_del_dua_values)]

# Guardar los valores faltantes en un nuevo archivo de Excel
output_path = r'C:/Users/keylo/CHC Consultores/CHC-CONSULTORES - Automatizacion TICA/Datos_Generales/DUAs/Total_DUAS_enero25.xlsx'
with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
    duas_fallidas.to_excel(writer, index=False, sheet_name='DUAs_Fallidas')

print(f"Archivo guardado como '{output_path}' con las DUAs que faltan en el archivo procesado.")
