# Pruebas y optimización de navegación — 6 de octubre de 2026

Para aplicar estos resultados a otro bot y reproducir las pruebas, consultar
la [guía de replicación](GUIA_REPLICACION_BOTS.md). Este documento conserva la
medición específica de Detalles.

Se compararon cuatro estrategias usando los mismos dos DUAs en cada estrategia:
`001-2026-020594` y `001-2026-020607`. Todas las consultas fueron de lectura y
se conservaron los 38 valores extraídos. No se ejecutó la cola de producción.

| Estrategia | Tiempo de dos consultas | Solicitudes del navegador | Scripts solicitados |
| --- | ---: | ---: | ---: |
| Contexto nuevo por DUA, navegación original | 9,189 s | 256 | 158 |
| Sesión y página reutilizadas por trabajador | 6,718 s | 209 | 127 |
| Detalle simplificado, contexto nuevo | 10,167 s | 178 | 102 |
| Reutilización y detalle simplificado | 6,737 s | 141 | 78 |

La combinación redujo aproximadamente un **45% las solicitudes del navegador**,
un **51% los scripts** y un **27% el tiempo** respecto a la navegación original
en esta muestra. El tiempo fue prácticamente igual al de reutilizar solamente
la sesión. Simplificar el detalle por sí solo no resultó más rápido.

Los contadores corresponden a eventos de solicitud del navegador, incluidos
recursos que el bloqueo estático aborta; no equivalen a bytes transferidos ni a
todas las solicitudes de la API HTTP. Las estrategias se ejecutaron en orden,
no en una prueba aleatoria de larga duración. La muestra no prueba rendimiento
en un mes completo ni con 32 consultas simultáneas.

La primera comparación tuvo rutas que no coincidían por mayúsculas/minúsculas
en los nombres de páginas. Se corrigió ese reconocimiento y se repitió la
comparación. La tabla anterior corresponde a la ejecución posterior a esa
corrección: las cuatro consultas con simplificación utilizaron efectivamente
la estrategia y mantuvieron los 38 valores idénticos a sus referencias.

Evidencia: `logs/estrategias_navegacion_20261006/comparacion_definitiva/comparacion.json`.
El script `scripts/benchmark_navegacion.py` acepta como máximo cuatro DUAs
diferentes; cada estrategia consulta una vez cada identificador. Guarda resultados
separados y no modifica los lotes de la interfaz.

## Implementación aplicada

- Cada trabajador mantiene su propio contexto y página. Sus DUAs se procesan
  secuencialmente y nunca se comparten campos ni CAPTCHA entre trabajadores.
- Antes de cada DUA se navega de nuevo al formulario y se resuelve su CAPTCHA.
- El contexto se descarta al fallar y se renueva entre consultas cada 100 DUAs
  o 10 minutos. Se cierra al terminar, cancelar o abandonar la ronda.
- El detalle se obtiene con `route.fetch`, usando la sesión del navegador.
  Solo se simplifica después de validar la identidad y comparar los 38 valores
  extraídos antes y después de retirar scripts y otros recursos secundarios.
- Las advertencias, el clic adicional, las identidades distintas y cualquier
  cambio de valores conservan la navegación original. No se automatiza el clic
  adicional reservado por las instrucciones del proyecto.
- La extracción final usa el HTML original recibido; se mantiene `DetallesFlow`.
  La representación simplificada sirve para completar la navegación, no para
  fabricar registros. Las respuestas HTTP se liberan en `finally`.
- SQLite, índices, exportaciones y reintentos conservan sus garantías anteriores.

Opciones de máquina: `reuse_context` y `lightweight_details`, ambas `true` por
defecto. Establecer una de ellas a `false` desactiva la optimización correspondiente.
No se cambió la preferencia local de siete consultas simultáneas ni el límite de
la interfaz. Los reintentos siguen usando como máximo dos trabajadores.

## Seguridad del formulario

La inspección confirmó que los campos se asignan por ID mediante su setter
nativo; no se depende del foco del teclado. Se comparan los valores antes del
clic y se valida la identidad del DUA antes de confirmar su resultado.

Se encontró una cobertura incompleta en el control del envío: vigilaba solo
POST de navegación y el portal usa POST AJAX. Se amplió a todos los POST del
formulario, con reconocimiento de URL sin distinguir mayúsculas y minúsculas.
Si el contenido tiene campos alterados, vacíos o duplicados, se aborta antes
de llegar al servidor y se registra `FormChangedError`. También se comprueba
que el CAPTCHA no haya cambiado después de resolverlo.

El diagnóstico conserva los valores reales y los cuatro campos del envío,
sin copiar campos de acceso de otros formularios. El pendiente de producción
`001-2026-021841` mostraba los campos correctos en su evidencia; su timeout no
permitía atribuir el error a un cruce de campos. No se modificó su estado.

## Verificación e integración

- **50 pruebas automáticas aprobadas**, incluyendo CAPTCHA cambiado, POST AJAX
  alterado, URL en otra capitalización, robo de foco, cierre, renovación de
  contexto, fallback de detalle y liberación de respuestas.
- Prueba integrada real de cuatro DUAs, con dos trabajadores y ambas mejoras:
  tres resultados en la primera ronda y un timeout. El envío del caso fallido
  tenía los valores correctos. Se reintentó únicamente ese pendiente en una
  sesión nueva y terminó correctamente.
- Final: cuatro resultados con los **38 valores idénticos** a los resultados
  previos del motor original. Una ronda adicional produjo cero intentos.
- Evidencia: `logs/estrategias_navegacion_20261006/integracion/report.json` y base
  de prueba en esa misma carpeta, independiente de `data/queues/`.

El código está en AstraCode. Se recompiló `DetallesBot_AstraCode.exe` con
`DetallesBot.spec` y se verificó que los módulos empaquetados coincidan con el
código actualizado. La versión anterior se conserva en
`dist/respaldo_20261006/DetallesBot_AstraCode.exe`; ambas copias se comprobaron
con SHA256. Las opciones nuevas se aplican al abrir el ejecutable actualizado
de la raíz. La versión `DetallesBot_v5.4.exe` abierta en otra ubicación no
recibe estas mejoras.
