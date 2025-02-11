import os
import pandas as pd

# Obtener la ruta del directorio actual donde está el script
current_dir = os.path.dirname(os.path.abspath(__file__))

# Ruta del archivo CSV que contiene las DUAs generadas
csv_file_path = os.path.join(current_dir, "duas_coincidentes_abril.csv")  # Cambia el nombre según el archivo generado

# Cargar el archivo CSV
df_duas = pd.read_csv(csv_file_path)

# Eliminar la primera columna (índice) del DataFrame para no incluirla en la comparación
df_duas_without_index = df_duas.iloc[:, 1:]

# Identificar las filas duplicadas ignorando la primera columna (índice)
df_duplicated = df_duas[df_duas_without_index.duplicated(keep=False)]

# Eliminar duplicados ignorando la primera columna (mantener la primera aparición)
df_duas_no_duplicates = df_duas.drop_duplicates(subset=df_duas.columns[1:], keep='first')

# Guardar el archivo sin duplicados
output_file_path_no_duplicates = os.path.join(current_dir, "duas_restantes_abril.csv")
df_duas_no_duplicates.to_csv(output_file_path_no_duplicates, index=False)

# Guardar los duplicados en un archivo aparte
output_file_path_duplicates = os.path.join(current_dir, "duas_duplicadas_abril.csv")
df_duplicated.to_csv(output_file_path_duplicates, index=False)

# Mostrar cuántas filas duplicadas se eliminaron y se guardaron
duplicates_count = df_duplicated.shape[0]
print(f"Se encontraron {duplicates_count} filas duplicadas ignorando la primera columna.")
print(f"Las filas duplicadas se han guardado en {output_file_path_duplicates}.")
print(f"El archivo sin duplicados se ha guardado en {output_file_path_no_duplicates}.")
