# Integración con DUAS_SCRAPPING

Revisión local: 3 de octubre de 2026. Origen:
`D:/PortafolioDesarrollador/DUAS_SCRAPPING`.

Se revisó el código de trabajo, que ya tenía modificaciones sin confirmar en Git.
No se modificó ese repositorio ni se ejecutaron consultas al portal. Las pruebas
de fallos utilizaron archivos sintéticos en un directorio temporal. No se revisó
el código de los otros tres bots; su compatibilidad exacta queda por comprobar.

## Flujo observado

1. La interfaz selecciona régimen, mes, año y rango. El modo masivo recorre nueve
   regímenes secuencialmente y abre un Edge nuevo para cada uno.
2. Cada consulta selecciona fechas mediante calendarios y resuelve el CAPTCHA
   leyendo `Names.xlsx`. Espera el botón Datos XML y extrae el XML del DOM.
3. Exporta una hoja Excel por rango. En modo Ambos, vuelve a leer las dos partes,
   crea un Excel mensual por régimen y mueve las partes a una subcarpeta.
4. Unir archivos finales vuelve a leer Excel, compone `aduana-ano-numero` y crea:

| Archivo | Selección actual |
| --- | --- |
| Total_DUAS.xlsx | Los nueve regímenes configurados |
| Total_DUAS - Transito.xlsx | TRANSITO |
| Total_DUAS - Importacion.xlsx | IMPORTACION DEFINITIVA, IMPORTACION TEMPORAL, REIMPORTACION y REIMPORTACION PERFECCIONAMIENTO PASIVO |

Los tres tienen una columna `NroDUA` y una hoja como `marzo26`. Tránsito e
Importación son subconjuntos del Total por diseño: que un DUA aparezca en el Total
y en uno de esos archivos es correcto. La deduplicación debe aplicarse dentro
de cada lista, no eliminando registros entre archivos de distinta finalidad.

## Hallazgos prioritarios

### 1. Identidad del período insuficiente

`src/tica_dua_bot.py:268` genera las partes sin año. Las carpetas están separadas
por régimen, no por período. `src/main.py:112` busca partes sin comprobar el año
del contenido; el nombre de la hoja final usa el año elegido en la interfaz.

Prueba reproducida: se crearon partes ficticias con DUAs de 2025 y se solicitó
Marzo 2026. La unión produjo una hoja `marzo26` con aquellos datos, sin reportar
faltantes. Esto demuestra el riesgo; no prueba que los archivos reales estén mal.

La búsqueda de ambas partes prefiere un consolidado mensual existente; puede
ignorar partes descargadas más recientemente. Tampoco incorpora rangos personalizados
como 1–7 ni busca las partes que ya fueron movidas a `partes/`.

### 2. Un archivo existente no demuestra una consulta exitosa

Varios métodos de extracción capturan errores, escriben el mensaje y continúan.
`procesar_rango_fechas` retorna la ruta esperada aunque la exportación no haya
tenido éxito. Si ya existía un archivo con ese nombre, puede quedar una versión
anterior disponible para la unión.

La espera del XML comprueba la palabra `aduana`, no un documento completo válido.
La comprobación de cierre XML suma la longitud de `</root>` antes de comparar
con `-1`, por lo que esa condición no detecta correctamente la ausencia del cierre.

### 3. La unión puede publicar resultados parciales como satisfactorios

La validación inicial comprueba la existencia de archivos. Luego, si uno no puede
leerse o no contiene las columnas necesarias, se omite y la función continúa.
Retorna una lista vacía de faltantes aunque haya ocurrido ese error.

Prueba reproducida: un archivo ficticio de Tránsito ilegible produjo dos totales
nuevos y cero faltantes reportados, mientras el Total de Tránsito anterior permanecía
en la carpeta. Los tres archivos podrían pertenecer a generaciones diferentes.

### 4. La unión no elimina duplicados

Se concatenan listas y DataFrames sin una clave única. Una prueba sintética generó
18 filas con 17 repeticiones en Total. Detalles ya evita duplicados al importar,
pero eso no protege a los otros consumidores ni valida el período de origen.

### 5. Hay trabajo repetido y recuperación limitada

- XML → Excel parcial → lectura de parciales → Excel por régimen → nueva lectura
  → tres Excel finales. El trabajo intermedio puede realizarse en SQLite.
- CAPTCHA: 191 entradas, con lectura de Excel en cada consulta. Se puede convertir
  a JSON y cargar una sola vez, verificando primero su equivalencia.
- Las esperas fijas incluyen cinco segundos tras cada régimen: hasta 45 segundos
  explícitos por recorrido completo, además de esperas del calendario y del portal.
- El navegador se cierra sin un `finally`: una excepción puede dejarlo abierto.
- No hay cola durable por régimen y rango ni reintentos registrados de cada unidad.
- Cancelar se revisa entre regímenes; las esperas de hasta 300 segundos no reciben
  la señal de cancelación.
- La selección de calendario solo retrocede hasta doce meses, puede salir sin
  haber seleccionado la fecha solicitada y no valida ambos campos antes de enviar.
- Un rango personalizado admite hasta 31 sin validar la cantidad de días del mes.

## Comprobación de archivos existentes

Lectura completa de la columna NroDUA, sin modificar los archivos:

| Carpeta | Hoja | Total | Importación | Tránsito | Duplicados internos |
| --- | --- | ---: | ---: | ---: | ---: |
| DUAs_2025 | marzo26 | 72.290 | 34.320 | 6.919 | 0 en los tres |
| Descargas | junio25 | 127.626 | 60.874 | 14.664 | 0 en los tres |

Los identificadores revisados cumplen el patrón de tres dígitos de aduana, cuatro
de año y seis de número. Sus años corresponden a las hojas indicadas. Esto no
certifica la cobertura de todo el mes: el identificador DUA no contiene el mes
ni el rango de fechas consultado. Un nombre de hoja mensual tampoco demuestra
que se hayan descargado ambas quincenas.

## Diseño recomendado

### Registro de origen local

Guardar la respuesta validada primero en SQLite. Registrar el período explícito
`2026-03`, régimen, fechas solicitadas, intento, estado, conteo y referencia al XML
original. Separar un rango exitoso sin registros de uno fallido o aún no consultado.

Normalizar los DUAs y garantizar la unicidad de pertenencia al período. Las
observaciones del mismo DUA en diferentes consultas deben conservar su procedencia
sin duplicar su pertenencia mensual. Las asociaciones con regímenes pueden ser
múltiples: no descartarlas al deduplicar. Las reglas actuales de clasificación se
mantienen hasta que el usuario decida modificarlas.

### Descargas reanudables

La unidad de trabajo es período + régimen + fecha inicial + fecha final. Guardar
los datos y el éxito del rango en una transacción. Si falla, queda pendiente; no
se acredita por la presencia de un archivo anterior. Reintentar solo rangos
pendientes. No declarar el mes completo hasta cubrir los rangos y regímenes
requeridos, incluidos aquellos confirmados explícitamente sin registros.

Empezar con consultas secuenciales. Si se necesita, probar con medición y una
muestra pequeña antes de aumentar concurrencia. No hay una comparación de tiempos
que justifique afirmar que cambiar Selenium por Playwright acelerará este portal.
Unificar después el motor con Detalles podría simplificar mantenimiento, pero no
resuelve por sí solo los errores de fechas, persistencia o exportación.

### Tres exportaciones compatibles

Generar los tres Excel desde una misma versión validada de los datos. Mantener
sus nombres, columna `NroDUA` textual y nombre de hoja mensual. Conservar ceros
iniciales. Incluir un archivo vacío con encabezado si una categoría está confirmada
sin registros; nunca dejar un total viejo simulando la salida nueva.

Organización sugerida: `salidas/2026/03/`, con los tres nombres actuales dentro.
Preparar los tres en una carpeta temporal de generación y marcar la entrega como
lista únicamente después de validarlos todos. No suponer que tres reemplazos de
archivo separados son una sola operación atómica. La publicación y selección de
la carpeta deben coordinarse con la forma en que los bots actuales consumen archivos.

Primera quincena añade registros al período; segunda quincena añade los faltantes;
mes completo reconcilia contra lo registrado sin duplicar. Debe existir evidencia
de cobertura independiente del número de filas y del nombre de la hoja.

### Evolución de los consumidores

Primero mantener los tres Excel para no requerir cambios en los otros bots.
Después, Detalles puede importar desde el catálogo de origen en SQLite mediante
una operación de lectura, conservando su cola propia. Cada uno de los otros bots
podría adoptar el mismo mecanismo cuando se revise.

No compartir un único indicador `procesado`: un DUA completado en Detalles puede
seguir pendiente en otro bot. Cada consumidor necesita su estado, reintentos y
resultado independientes. Tampoco se necesita que todos escriban simultáneamente
en una sola base; el catálogo de entrada y las colas de resultados son distintos.

## Orden propuesto

1. Proteger períodos, validar fechas/respuestas y detener publicaciones parciales.
2. Introducir almacenamiento único, deduplicación y recuperación por rango.
3. Generar los tres Excel compatibles desde ese almacenamiento.
4. Optimizar CAPTCHA, sesiones, esperas y cancelación; medir la mejora real.
5. Conectar Detalles directamente al origen; revisar después los otros consumidores.
