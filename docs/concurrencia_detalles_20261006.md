# Aplicabilidad de la estrategia de Manifiestos a Detalles

**Nota de contexto:** este análisis corresponde a la evaluación anterior a la
optimización de navegación del mismo día. La creación de contexto por intento
descrita abajo fue sustituida por reutilización aislada por trabajador.
La implementación vigente y su comparación están en
[optimización de navegación](optimizacion_navegacion_20261006.md); el método para
replicarlas está en la [guía de replicación](GUIA_REPLICACION_BOTS.md).

La arquitectura es compatible y ya está parcialmente aplicada. El motor activo
es `src/core/playwright_processor.py`; los motores HTTP y Selenium anteriores
no forman parte del flujo actual de la interfaz.

El motor actual utiliza trabajadores `asyncio`, reserva transaccional de DUAs
en SQLite, confirmación conjunta del resultado y su estado, reintentos por rondas,
cancelación recuperable y comunicación de progreso a Tk mediante una cola.
Las rondas posteriores a la primera limitan la concurrencia a dos para recuperar
pendientes. La configuración local indica siete consultas simultáneas y la GUI
permite de una a veinte. No se cambió ninguna de esas preferencias en esta revisión.

## Diferencia que afecta al rendimiento

Los bots de Manifiestos obtienen enlaces de la lista y descargan tablas mediante
solicitudes HTTP asíncronas con las cookies del navegador. Detalles completa un
formulario con CAPTCHA y eventos GeneXus. Cada intento crea un contexto y una
página de Chromium, navega, verifica los campos y el POST y extrae el detalle.
Sus contextos independientes evitan compartir los valores de dos DUAs distintos.

En la muestra, cada DUA recibió 81–83 respuestas HTTP, de las cuales tres eran
documentos. Esto explica por qué 32 consultas de Detalles suponen más recursos
que 32 descargas directas de tablas. Aumentar el número de tareas por sí solo no
demuestra que mejore la velocidad ni que el portal lo sostenga.

## Comprobación realizada

- Suite existente: **37 pruebas aprobadas**.
- Prueba real aislada: **cuatro identificadores**, cuatro contextos simultáneos,
  cuatro resultados confirmados con identidad correcta y **38 campos** cada uno.
  La ronda duró aproximadamente **13,86 segundos**, incluyendo el cierre del
  navegador y excluyendo su arranque. No es una comparación controlada con otra
  concurrencia ni con el bot de Manifiestos.
- Simulación sin conexión: **357 DUAs con 32 trabajadores**; 330 guardados y 27
  fallidos recuperables. Segunda ronda: solo los 27 pendientes, final con 357
  guardados. No hubo reservas repetidas ni trabajos en curso al terminar.

Los resultados se guardaron en una base de prueba dentro de
`logs/analisis_concurrencia_20261006/`, junto con `report.json` y
`simulacion_32.json`. No se ejecutó la cola de producción ni se modificó la
configuración de la app. El código de extracción de las 38 columnas permanece
igual. Las pruebas reales no incluyeron consultas simultáneas de 32 DUAs.

## Estrategia de mejora compatible

La prioridad es medir y reducir el costo por consulta manteniendo la validación
del formulario, la identidad y la separación de sesiones. Se puede investigar
la reutilización de recursos por trabajador, con renovación ante error, pero debe
comprobarse que reutilizar cookies no provoque los casos de paso adicional.
Una alternativa es una ruta híbrida: inicialización y CAPTCHA en navegador y
consulta directa donde el protocolo permita conservar correctamente su estado.
El procesador HTTP legado no es prueba suficiente para activar esa alternativa.

Una prueba escalonada debe comparar duración, porcentaje de errores, memoria y
reintentos; el número de consultas se elige por esos resultados. La infraestructura
de cola soporta 32 tareas en simulación; queda por validar la capacidad del portal
y del navegador antes de habilitar ese máximo en producción.
