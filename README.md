# Detalles BOT — AstraCode

Consulta los detalles de DUAs en TICA con Playwright. El Excel se importa una vez
a una cola SQLite local; cada resultado se guarda junto con su estado. El CSV es
una exportación recuperable, no el registro de progreso.

Para replicar esta arquitectura en otros bots, leer la
[guía de replicación](docs/GUIA_REPLICACION_BOTS.md): elección entre HTTP y
navegador, SQLite, estados, reanudación, formulario seguro, configuración,
comparación de estrategias y pruebas. Incluye el mapa de ambos proyectos y las
decisiones necesarias para retomar sin el historial de conversación.

## Ejecutar

El ejecutable local actualizado es `DetallesBot_AstraCode.exe`, en la raíz del
proyecto. En esa ubicación usa `config/` y `data/queues/` existentes. Mover solo el
ejecutable a otra carpeta crea una instalación independiente: para trasladar el
trabajo, mover también esas carpetas con todas las instancias detenidas.

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
python src/main.py
```

En **Procesamiento**, elegir un `.xlsx` y una hoja con la
columna `NroDUA` (por ejemplo `001-2026-020591`). El nombre de la tabla toma inicialmente
el de la hoja: se puede corregir antes de pulsar **Guardar tabla**. Después, elegir
la carpeta de resultados y pulsar **Iniciar consultas**. Guardar una tabla no consulta
el portal. La carpeta de salida se guarda al seleccionarla.

Al guardar, una ventana pide confirmar o editar el nombre. Si la tabla ya existe,
el botón **Agregar DUAs** añade únicamente los nuevos y conserva los resultados,
intentos y pendientes anteriores. Por ejemplo: importar las dos quincenas como
`marzo26` alimenta la misma tabla; `abril26` mantiene una tabla independiente.
El nombre se compara sin distinguir mayúsculas ni espacios al principio o al final.
La app informa cuántos DUAs añadió, cuántos ya estaban registrados y cuántas entradas
necesitan revisión. Volver a cargar el mes completo no duplica DUAs ni resultados,
incluidos los resultados de filas completadas que se hayan limpiado.

La misma pantalla muestra guardados, pendientes, consultas en curso y entradas que
necesitan corrección. **Base de datos** permite abrir o renombrar tablas, buscar DUAs,
filtrar por estado y eliminar filas elegidas, todas las completadas o una tabla entera.
Cada eliminación pide confirmación y crea un respaldo en `data/queues/backups/`.
Limpiar completadas conserva sus resultados para futuras exportaciones y deja los
pendientes intactos. Eliminar una tabla conserva los archivos de resultados existentes.
**Resultados** lleva directamente a la carpeta del lote.

En **Configuración** se cambia la concurrencia, espera y rondas. Se guardan con **Guardar
configuración**, o automáticamente al iniciar una consulta. Durante el procesamiento
quedan bloqueados. **Modo oscuro** cambia inmediatamente los colores de la ventana y
del administrador; se recuerda con **Guardar configuración**. Es el tema inicial si
no existe una preferencia guardada. El tema claro sigue disponible.
La consola **Actividad** muestra mensajes sencillos; los diagnósticos técnicos quedan
en el log. Limpiar esa vista no elimina los logs ni los resultados.

El botón principal cambia a **Retomar pendientes** cuando hay trabajo guardado,
y a **Actualizar resultados** si todos tienen resultado. La ventana inicial mide
760 × 610 y reúne selección, progreso, consola y botones sin desplazamiento.
Solo la configuración está en otra pestaña. Los botones tienen fondo y borde
contrastados; Iniciar y Detener se distinguen también por color.

- Cada ronda consulta una vez todos los DUAs pendientes. Predeterminado: tres
  rondas, un worker y 30 segundos de timeout por operación del navegador.
- Al terminar la lista, los reintentos comienzan automáticamente, con un máximo
  de dos consultas simultáneas para reducir la carga durante la recuperación.
- Los resultados confirmados no vuelven a consultarse dentro del mismo lote.
- Detener o cerrar devuelve las consultas interrumpidas a pendientes.
- Una nueva ejecución retoma pendientes y recupera los que estaban en curso
  durante un cierre inesperado. No se usa el índice máximo de `session.json`.
- La barra cuenta únicamente resultados guardados. **Completado** requiere el
  100%; agotar las rondas muestra **Finalizado con pendientes**.
- Las entradas inválidas quedan identificadas por fila, sin enviarse al portal.
  Para corregirlas, preparar un Excel con esas filas corregidas e importarlo como
  otra tabla o agregar los DUAs corregidos a la misma tabla y eliminar explícitamente las
  entradas inválidas anteriores. Una nueva carga nunca borra pendientes previos.
- Los casos que necesitan un clic adicional no se automatizan en esta versión.
  Se mantienen pendientes, con error y HTML de diagnóstico cuando está disponible.

## Archivos

| Archivo | Función |
| --- | --- |
| `config/captcha_lookup.json` | 191 pares número de imagen → palabra; carga única en memoria |
| `data/queues/<lote>.sqlite3` | DUAs, filas importadas, resultados, estados e historial de intentos |
| `data/queues/catalog.sqlite3` | Nombres editables e identidad de las tablas guardadas |
| `data/queues/backups/` | Copias previas a las eliminaciones; no aparecen como tablas activas |
| `<salida>/<hoja>/<lote>/Detalles_DUAs_<hoja>.csv` | Resultados confirmados, 38 columnas |
| `<salida>/<hoja>/<lote>/Detalles_DUAs_pendientes_<hoja>.txt` | DUAs válidos aún sin resultado |
| `<salida>/<hoja>/<lote>/pendientes.json` | Pendientes, errores, intentos y filas de origen, incluidas entradas inválidas |
| `<salida>/<hoja>/<lote>/diagnosticos/` | Último HTML disponible de consultas fallidas |
| `logs/debug.log` | Log con rotación de tamaño |

Cada tabla nueva tiene un identificador permanente, independiente del nombre y de
la ruta del Excel. Tras **Guardar tabla**, el archivo original se puede mover o
retirar: consultar y reanudar usan exclusivamente la lista guardada. Para incorporar
otro Excel se debe importarlo explícitamente: el mismo nombre amplía la tabla y
un nombre diferente crea otra. Cada carga queda registrada con archivo, hoja y conteos.
Un índice único en SQLite impide repetir un DUA dentro de una tabla. Los duplicados
con resultados archivados también se omiten al importar y al exportar.
Los lotes existentes se reconocen sin volver a leer sus Excel. Renombrar una tabla
no mueve sus resultados. Cambiar la carpeta de salida permite exportarlos allí.

Las “tablas” de la interfaz son lotes con nombres legibles; internamente cada lote
conserva su archivo SQLite y un esquema fijo. Los nombres nunca se interpolan en SQL.
El administrador bloquea modificaciones durante una ejecución y también respeta
los bloqueos de otras instancias. Los respaldos se conservan para recuperación manual;
esta versión no incluye un botón para restaurarlos.

La app recuerda la última tabla abierta aunque falte su Excel. Respaldar
`data/queues/` con la app detenida conserva el trabajo completo. Mantener esta
carpeta en disco local; la carpeta de salida puede ser distinta.

CSV, TXT y JSON se exportan cada 60 segundos y al finalizar/detener. Cada archivo
se reemplaza atómicamente, aunque el conjunto de exportaciones no constituye una
única transacción. Si el CSV está abierto en Excel y bloquea la escritura, la app
reporta el error; cerrar Excel y volver a Iniciar regenera la salida desde SQLite.

Desde la optimización del 6 de octubre, cada trabajador reutiliza su propia sesión
y página y las renueva al fallar, cada 100 consultas o después de 10 minutos.
El formulario y CAPTCHA se verifican nuevamente en cada DUA. Los detalles validados
se representan sin scripts secundarios, conservando el HTML original para extraer
las mismas 38 columnas. Los POST AJAX también se comprueban antes de enviarse.
`reuse_context` y `lightweight_details` permiten desactivar cada mejora en la
configuración de máquina. Las pruebas y mediciones están en
[el análisis de navegación](docs/optimizacion_navegacion_20261006.md).

## Migración

`Names_TicaPortal.xlsx` ya no es una dependencia de la app ni del empaquetado.
Se conserva el archivo original local; sus 191 entradas se convirtieron al JSON
versionado. El catálogo usa el número de imagen, por lo que no depende del host
anterior del portal.

Al importar una tabla, si existe el CSV de la versión anterior en la carpeta de salida configurada,
la app importa filas con las 38 columnas y un identificador válido que pertenezca
al lote. Los registros truncados se omiten y sus DUAs permanecen por consultar.
Los TXT antiguos de procesados y los índices de sesión no se consideran prueba de
resultado. El CSV anterior se conserva sin modificar. Un CSV con encabezado
incompatible genera un error explícito en lugar de sobrescribirlo.

## Verificación

```powershell
python -m unittest discover -s tests -v
```

Las pruebas usan datos sintéticos, navegador simulado y SQLite temporal. No
consultan TICA. Incluyen concurrencia, cierre abrupto de un subproceso, rollback,
reanudación, reintentos, exportación bloqueada y una prueba de integración de Tk.
Las pruebas del formulario también usan Chromium real con todas las peticiones
interceptadas localmente; requieren `python -m playwright install chromium`.

El formulario se completa por identificador, conservando sus eventos de cambio,
y se verifican los valores antes del clic y en el envío. Una alteración bloquea
la consulta y la deja para reintentar. Las advertencias y retornos al formulario
se reconocen sin esperar que aparezca un detalle que el portal no devolvió.
Los mensajes de la aplicación son breves; los errores completos permanecen en
`logs/debug.log` y en los archivos de diagnóstico. El HTML de error puede tener
al lado un JSON con los valores reales observados antes del envío.

Diagnóstico **real y explícito**, limitado a cuatro identificadores por ejecución:

```powershell
python scripts/probe_portal.py 001-2026-020591
```

Este comando abre Chromium, consulta el portal y guarda HTML, captura y reporte
en `logs/diagnostico_astracode/`. No hace consultas masivas ni modifica la cola de
la interfaz. La validación realizada en esta rama se detalla en
[el análisis del sistema](docs/analisis_astracode.md).

Para empaquetar: `python -m PyInstaller --distpath dist/AstraCode --workpath build/AstraCode DetallesBot.spec`.
El spec incluye el JSON;
el Chromium de Playwright debe estar instalado en la máquina donde se ejecuta.
El ejecutable local AstraCode se recompiló con estos cambios. Los ejecutables de
versiones anteriores conservan su comportamiento; no se sustituyen automáticamente.
