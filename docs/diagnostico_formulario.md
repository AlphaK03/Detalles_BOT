# Diagnóstico de los fallos reportados el 2 de octubre de 2026

Se leyó la cola existente en modo de solo lectura. En esa captura había 422
resultados y nueve pendientes de reintento. No se alteraron sus estados ni se
inició el lote de 72.290 DUAs.

Cinco de esos pendientes conservaron el formulario de consulta. Cuatro conservaron
la página `hcimsg2.aspx` con `#ERROR`: el portal indicaba que faltaban datos o no
existía la información. El motor esperaba únicamente `#span_NUME_CORRE` y terminaba
reportando todos esos casos como timeout. Ese mensaje del portal por sí solo no
demuestra que el DUA sea inexistente.

Se consultaron dos DUAs del reporte, `001-2026-021719` y `001-2026-021731`, una vez
con el llenado anterior instrumentado y otra con el nuevo (cuatro consultas en
total). Los dos funcionaron con el llenado anterior: 4,42 y 4,16 segundos. Sus
campos y cuerpos POST correspondían exactamente al DUA solicitado. No se reprodujo
el cruce de campos en esta muestra ni se estableció una causa única para los fallos.
Con el nuevo llenado, ambos volvieron a entregar los 38 campos con la identidad
correcta (4,48 y 13,41 segundos). No son mediciones suficientes para afirmar una
mejora de velocidad. La suite local terminó con 27 pruebas aprobadas.

Los atributos `value` del HTML guardado no reflejan necesariamente el valor actual
de un input modificado por JavaScript. Por eso los formularios guardados con
atributos vacíos no permiten afirmar que se enviaran vacíos. Se agregó evidencia
de las propiedades reales `.value` para próximos incidentes.

El script público `hcimppon.js` usa eventos de cambio y pérdida de foco GeneXus.
Se conserva Playwright para ejecutar ese flujo, con estos cambios:

- Esperar inicialización de la página y del formulario antes de completar campos.
- Asignar valores al input exacto mediante su setter nativo, con eventos input,
  change y blur. No se escribe texto a través del elemento que tenga el foco.
- Comparar todos los valores antes de enviar y comprobar el CAPTCHA seleccionado.
- Validar también el cuerpo del POST de navegación; abortar si cambió algún valor.
- Distinguir detalle, advertencia, retorno al formulario y caso de clic adicional.
- Mantener todo fallo como reintentable, con un máximo de dos workers en rondas de
  recuperación. Esto reduce la concurrencia de los reintentos; no se afirma que
  siete workers fueran la causa comprobada de los fallos originales.

Las pruebas locales usan un Chromium real con rutas interceptadas, sin acceder al
portal: robo deliberado del foco, campos alterados durante onchange y onsubmit,
campos duplicados en POST, advertencia del servidor y regreso al formulario.
El cambio está sustentado en el DOM y JavaScript observado, y en la documentación
oficial de [interacción con formularios](https://playwright.dev/python/docs/input)
y [navegación](https://playwright.dev/python/docs/navigations).

No se implementa el clic adicional ni se sustituyen resultados reales por valores
vacíos. Los logs técnicos conservan el detalle; la pantalla muestra mensajes como
«DUA … guardado» y «Se reintentará al final».
