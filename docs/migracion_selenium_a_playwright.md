# Migración Selenium → Playwright (browser compartido)

> Documento histórico. La rama AstraCode sustituye la reanudación por índice y el
> Excel CAPTCHA por SQLite y JSON. Consultar [el análisis actualizado](analisis_astracode.md)
> y [README](../README.md) para el flujo activo y la configuración actual.

Guía de referencia para aplicar esta migración a cualquier bot de la familia TICA que use la misma arquitectura (`BaseFlow` + `DUAProcessor`).

---

## Contexto del problema

El bot original abría **una instancia completa de Edge por hilo worker**:

```
cant_hilos = 1  →  ~300 MB de RAM
cant_hilos = 3  →  ~900 MB de RAM
cant_hilos = 5  →  ~1.5 GB de RAM
```

El objetivo era reducir el consumo de RAM para poder usar más hilos sin que el sistema colapse.

---

## Lo que se investigó primero: HTTP puro

Antes de ir a Playwright, se evaluó si era posible hacer scraping **sin ningún browser**, usando solo `requests` + `BeautifulSoup`.

### Por qué era viable en teoría

El portal TICA (`hcimppon.aspx`) es ASP.NET WebForms (`.aspx`). Confirmamos con `Ctrl+U` en el browser que:
- La **página de resultado** (`hcimdpola.aspx`) es completamente **server-side rendered** — todos los `<span>` con datos ya vienen en el HTML del servidor.
- El flujo es exactamente 2 requests: `GET` el formulario → `POST` los datos → redirect automático a la página de resultado.

### Por qué no funcionó: el CAPTCHA

El CAPTCHA es un **GeneXus UserControl** (`CAPTCHA1Container`). El servidor entrega el div vacío:

```html
<div class="gx_usercontrol" id="CAPTCHA1Container"></div>
```

JavaScript de GeneXus lo rellena después de cargar la página, inyectando:

```html
<div id="captchaImage">
  <img src="https://portaltica.hacienda.go.cr/TicaExterno/Captcha/images/89.jpg" ...>
</div>
```

Sin browser, JavaScript nunca corre, y la URL de la imagen (que es la clave para el lookup en `Names_TicaPortal.xlsx`) nunca aparece en el HTML. El intento de buscarla con regex en el HTML crudo también falló — no existe referencia a ella en ningún tag, script ni atributo.

**Conclusión:** cualquier bot de la familia TICA que use CAPTCHA de GeneXus necesita un browser real para la fase de resolución del CAPTCHA. La extracción de datos sí podría hacerse con HTTP, pero el ganancial no justifica la complejidad del enfoque híbrido.

---

## Solución final: Playwright con browser compartido

### Arquitectura

```
Selenium (antes):          Playwright (ahora):
[Edge 1] ← 300 MB          [Chromium] ← 100 MB base
[Edge 2] ← 300 MB            ├── context 1 ← ~30 MB
[Edge 3] ← 300 MB            ├── context 2 ← ~30 MB
Total: ~900 MB               └── context 3 ← ~30 MB
                           Total: ~190 MB
```

- **Un único proceso Chromium** compartido entre todos los workers.
- Cada worker usa un **BrowserContext** aislado (cookies, sesión, estado independientes — como ventanas incógnito separadas).
- El contexto se crea al inicio de cada DUA y se cierra al terminar — sin acumulación de carpetas temp.
- La concurrencia se gestiona con `asyncio.Queue` + `asyncio.Semaphore` en lugar de `ThreadPoolExecutor`.

### Comparativa de consumo

| Hilos | Selenium (Edge) | Playwright (Chromium) |
|-------|-----------------|----------------------|
| 1     | ~300 MB         | ~130 MB              |
| 3     | ~900 MB         | ~190 MB              |
| 5     | ~1.5 GB         | ~250 MB              |
| 10    | ~3 GB           | ~400 MB              |

### Límite real de hilos

El límite no es RAM sino el **rate-limiting del portal**. Recomendación:
- Empezar en **2**, observar tasa de errores 5-10 minutos.
- Subir a **3-4** si el portal tolera.
- Rara vez vale la pena pasar de **5** en portales de gobierno.

---

## Archivos modificados / creados

### Nuevo: `src/core/playwright_processor.py`

Reemplaza `src/core/processor.py` para los bots de la rama Playwright. Responsabilidades:
- Lanzar y cerrar el browser Chromium.
- Gestionar la cola de DUAs y la concurrencia con `asyncio`.
- Resolver el CAPTCHA esperando que GeneXus JS rellene `#captchaImage img`.
- Llamar `flow.extract_data()` del flujo específico del bot.
- Escribir CSV, log de procesados y log de fallidos.

### Modificado: `src/ui/app.py`

| Antes | Después |
|-------|---------|
| `from core.processor import DUAProcessor` | `from core.playwright_processor import PlaywrightDUAProcessor` |
| `ThreadPoolExecutor` con N workers | `PlaywrightDUAProcessor.run()` maneja asyncio internamente |
| `_lock = threading.Lock()` pasado a cada processor | Eliminado — el processor usa `asyncio.Lock` propio |
| Límite de hilos: 10 | Límite de hilos: 20 |
| Descripción hilos: "navegadores en paralelo" | "Contextos Playwright paralelos" |
| Headless eliminado | Headless restaurado (desactivable para depurar) |

`_run()` pasó de ~30 líneas con executor a 8 líneas:

```python
def _run(self, df, output_paths, start_from):
    processor = PlaywrightDUAProcessor(
        self.machine, output_paths, DetallesFlow(),
        self._names_df, self._stop_event,
    )
    try:
        processor.run(df, start_from, self._on_progress)
    except Exception as e:
        logging.exception("Error en la ejecución principal: %s", e)
    finally:
        self.after(0, self._on_finished)
```

### Modificado: `src/utils.py`

- Eliminados de `_DEFAULT_MACHINE`: `edge_driver_path`, `screenshot_path`.
- Mantenido y restaurado: `headless` (ahora lo usa Playwright).

### Eliminados (solo en esta rama)

- `src/driver_updater.py` ya no se importa en `app.py`.
- UI de WebDriver (frame de versiones, botón de actualización) removida de la pestaña Configuración.

---

## Instalación de dependencias

```bash
pip install playwright
playwright install chromium
```

Solo se instala Chromium (111 MB). No se necesita msedgedriver ni ningún binario externo adicional.

---

## Cómo aplicar a un bot nuevo

Un bot nuevo de la familia TICA solo necesita cambiar `DetallesFlow` o equivalente flow. El processor y la UI son idénticos.

### Paso 1 — Crear el flujo del nuevo bot

```python
# src/flows/mi_nuevo_flow.py
from flows.base_flow import BaseFlow
import pandas as pd
from bs4 import BeautifulSoup

class MiNuevoFlow(BaseFlow):

    _START_URL = 'https://portaltica.hacienda.go.cr/TicaExterno/OTRA_PAGINA.aspx'

    @property
    def start_url(self) -> str:
        return self._START_URL

    def extract_data(self, page_source: str) -> pd.DataFrame:
        soup = BeautifulSoup(page_source, 'html.parser')
        data = {
            'campo1': soup.find('span', {'id': 'span_CAMPO1'}).get_text(strip=True),
            'campo2': soup.find('span', {'id': 'span_CAMPO2'}).get_text(strip=True),
            # ...
            'numero_del_dua': ...,  # OBLIGATORIO — usado para deduplicación
        }
        return pd.DataFrame([data])
```

> **Nota:** `numero_del_dua` es obligatorio en el DataFrame devuelto por `extract_data()`. Es la clave de deduplicación usada por `PlaywrightDUAProcessor`.

### Paso 2 — Verificar si el formulario es el mismo

Si el nuevo bot usa la misma página de búsqueda (`hcimppon.aspx`) con los mismos campos (`vVCODI_ADUA`, `vVANO_PRE`, `vVNUME_CORR`, `_cfield`, botón `DETALLE`), **no hay nada más que cambiar en el processor**.

Si la página de búsqueda es diferente, sobrescribir `_fetch_result` en una subclase de `PlaywrightDUAProcessor` o implementar `fill_form` en el flow (ver `BaseFlow`).

### Paso 3 — Conectar en `app.py`

```python
# Solo cambiar la importación del flow:
from flows.mi_nuevo_flow import MiNuevoFlow

# Y en _run():
processor = PlaywrightDUAProcessor(
    self.machine, output_paths, MiNuevoFlow(),  # ← único cambio
    self._names_df, self._stop_event,
)
```

### Paso 4 — Verificar el selector del CAPTCHA

Si el nuevo portal también usa GeneXus CAPTCHA, el selector `#captchaImage img` funciona igual. Si usa otro sistema de CAPTCHA, sobrescribir `_resolve_captcha` en `PlaywrightDUAProcessor`.

### Paso 5 — Verificar el selector de datos listos

En `playwright_processor._fetch_result()` se espera `#span_CODI_ADUAN` para confirmar que la página de resultado cargó:

```python
await page.wait_for_selector('#span_CODI_ADUAN', timeout=timeout_ms)
```

Cambiar este selector al elemento equivalente de la nueva página de resultado.

---

## Notas de operación

- **Headless desactivado**: útil para depurar — se ve el browser en tiempo real con cada paso.
- **Rectificación**: el processor detecta y descarta automáticamente la página de rectificación de GeneXus antes de llenar el formulario.
- **Limpieza de temp**: Playwright limpia sus directorios temporales al salir del context manager, incluso en crashes (lo gestiona él mismo, sin daemon threads adicionales).
- **Reanudación**: el mecanismo de reanudación (`session.json` + `processed_log`) funciona igual que antes — no cambió.
- **CAPTCHA lookup**: sin cambios — `Names_TicaPortal.xlsx` con las 191 imágenes posibles sigue siendo la fuente de verdad.
