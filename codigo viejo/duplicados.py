import pandas as pd
from tkinter import filedialog
from tkinter import Tk


# Función para seleccionar el archivo .xlsx
def seleccionar_archivo():
    root = Tk()
    root.withdraw()  # Ocultar la ventana principal de Tkinter
    archivo = filedialog.askopenfilename(title="Selecciona un archivo Excel", filetypes=[("Archivos Excel", "*.xlsx")])
    return archivo


# Función principal
def encontrar_duplicados():
    archivo = seleccionar_archivo()

    if archivo:
        df = pd.read_excel(archivo)

        # 📌 Imprimir los nombres de las columnas para verificar
        print("Columnas en el archivo:", df.columns.tolist())

        # Buscar el nombre correcto de la columna (sin espacios extra)
        columnas_procesadas = [col.strip() for col in df.columns]
        df.columns = columnas_procesadas  # Limpiar nombres de columnas

        if 'numero_del_dua' in df.columns:
            duplicados = df[df.duplicated(subset='numero_del_dua', keep=False)]
            if not duplicados.empty:
                print("Filas con 'numero_del_dua' duplicados:")
                print(duplicados)
            else:
                print("No se encontraron duplicados.")
        else:
            print("No se encuentra la columna 'numero_del_dua'. Verifique los nombres en el archivo.")
    else:
        print("No se seleccionó ningún archivo.")


if __name__ == "__main__":
    encontrar_duplicados()
