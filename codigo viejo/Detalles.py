import os
import pandas as pd

# Obtener la ruta del directorio actual donde está el script
current_dir = os.path.dirname(os.path.abspath(__file__))

# Ruta del archivo XLSX de mayo
xlsx_file_path = os.path.join(current_dir, "mayo_duas.xlsx")  # Archivo de DUAs de mayo

# Ruta del archivo CSV
csv_file_path = os.path.join(current_dir, "Keylor_detalle_DUAs_mayo24.csv")  # Cambia el nombre si es necesario

# Cargar el archivo XLSX
df_duas = pd.read_excel(xlsx_file_path)

# Cargar el archivo CSV con el separador correcto (punto y coma)
df_details = pd.read_csv(csv_file_path, encoding='latin1', sep=';', on_bad_lines='skip')  # Usamos sep=';' para el separador correcto

# Imprimir los nombres de las columnas para verificar si se leyeron correctamente
print("Columnas del archivo CSV:")
print(df_details.columns)

# Si 'numero_del_dua' está en las columnas, proceder con la normalización
if 'numero_del_dua' in df_details.columns:
    # Normalizar el formato de la columna NroDUA en el archivo XLSX (eliminar guiones)
    df_duas['NroDUA_normalized'] = df_duas['NroDUA'].str.replace('-', '')

    # Normalizar el formato de la columna numero_del_dua en el CSV (eliminar espacios)
    df_details['numero_del_dua_normalized'] = df_details['numero_del_dua'].str.replace(' ', '')

    # Comparar las DUAs normalizadas
    matching_duas = df_details[df_details['numero_del_dua_normalized'].isin(df_duas['NroDUA_normalized'])]

    # Guardar los DUAs coincidentes en un nuevo archivo CSV en el mismo directorio
    output_file_path = os.path.join(current_dir, "duas_coincidentes_mayo.csv")
    matching_duas.to_csv(output_file_path, index=False)

    print(f"Los DUAs coincidentes de mayo han sido guardados en {output_file_path}")
else:
    print("La columna 'numero_del_dua' no se encontró en el archivo CSV.")
