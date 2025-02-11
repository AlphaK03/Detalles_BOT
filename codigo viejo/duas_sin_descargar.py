import os
import pandas as pd

# Obtener la ruta del directorio actual donde está el script
current_dir = os.path.dirname(os.path.abspath(__file__))

# Ruta del archivo Excel (DUAs)
excel_file_path = os.path.join(current_dir, "abril_duas.xlsx")

# Ruta del archivo CSV de detalles de abril
csv_file_path = os.path.join(current_dir, "042024_detalle_DUAs_abril.csv")

# Cargar el archivo Excel completo sin filtro de fechas
df_duas = pd.read_excel(excel_file_path)

# Normalizar el formato de la columna NroDUA en el archivo Excel (eliminar guiones)
df_duas['NroDUA_normalized'] = df_duas['NroDUA'].str.replace('-', '')

# Cargar el archivo CSV con una codificación diferente (intentar con 'latin1' o 'utf-16')
df_details = pd.read_csv(csv_file_path, encoding='latin1')  # Si 'latin1' no funciona, intenta con 'utf-16'

# Normalizar el formato de la columna numero_del_dua en el CSV (eliminar espacios)
df_details['numero_del_dua_normalized'] = df_details['numero_del_dua'].str.replace(' ', '')

# Encontrar DUAs del archivo Excel que no están en los detalles del CSV
duas_no_encontradas = df_duas[~df_duas['NroDUA_normalized'].isin(df_details['numero_del_dua_normalized'])]

# Guardar las DUAs no encontradas en un archivo CSV aparte
output_file_path_not_found = os.path.join(current_dir, "duas_no_encontradas.csv")
duas_no_encontradas.to_csv(output_file_path_not_found, index=False)

# Mostrar cuántas DUAs no se encontraron
duas_no_encontradas_count = duas_no_encontradas.shape[0]
print(f"Se encontraron {duas_no_encontradas_count} DUAs que no están en el CSV de detalles.")
print(f"Las DUAs no encontradas se han guardado en {output_file_path_not_found}.")
