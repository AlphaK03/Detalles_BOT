import os
import pandas as pd
import chardet

# Obtener la ruta del directorio actual donde está el script
current_dir = os.path.dirname(os.path.abspath(__file__))

# Ruta del archivo CSV original
csv_file_path = os.path.join(current_dir, "042024_detalle_DUAs_abril.csv")

# Detectar la codificación del archivo CSV original
with open(csv_file_path, 'rb') as rawdata:
    result = chardet.detect(rawdata.read(100000))  # Leer parte del archivo para detectar la codificación
    original_encoding = result['encoding']
    print(f"Codificación detectada: {original_encoding}")

# Cargar el archivo CSV con la codificación detectada
df = pd.read_csv(csv_file_path, encoding=original_encoding)

# Guardar el archivo como UTF-8
utf8_file_path = os.path.join(current_dir, "042024_detalle_DUAs_abril_utf8.csv")
df.to_csv(utf8_file_path, index=False, encoding='utf-8')

print(f"Archivo convertido a UTF-8 y guardado en: {utf8_file_path}")
