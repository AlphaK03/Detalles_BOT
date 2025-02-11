import pandas as pd
import os

# Obtener la ruta del directorio actual donde está el script
current_dir = os.path.dirname(os.path.abspath(__file__))

# Ruta del archivo CSV original
csv_file_path = os.path.join(current_dir, "Keylor_detalle_DUAs_Test_agosto24-RifloteCharris.csv")

# Ruta del archivo CSV reparado
output_file_path = os.path.join(current_dir, "Keylor_detalle_DUAs_Test_agosto24-RifloteCharris_fixed.csv")

# Intentar leer el archivo original con diferentes codificaciones y eliminar las líneas malformadas
try:
    df = pd.read_csv(csv_file_path, encoding='latin1', on_bad_lines='skip')
    print("Archivo leído correctamente con codificación 'latin1'.")
except UnicodeDecodeError:
    try:
        df = pd.read_csv(csv_file_path, encoding='ISO-8859-1', on_bad_lines='skip')
        print("Archivo leído correctamente con codificación 'ISO-8859-1'.")
    except Exception as e:
        print(f"No se pudo leer el archivo. Error: {e}")
        exit()

# Guardar el archivo reparado en un nuevo CSV con codificación 'utf-8'
df.to_csv(output_file_path, index=False, encoding='utf-8')
print(f"Archivo CSV reparado guardado en: {output_file_path}")
