"""Mantiene el formulario real y evita ejecutar scripts en un detalle ya validado."""
from bs4 import BeautifulSoup
import re

from core.identifiers import validate_result


async def install_lightweight_detail(page, flow, dua, timeout_ms):
    pattern = re.compile(r'.*/hcimdpola\.aspx(?:\?.*)?$', re.IGNORECASE)

    async def capture(route):
        if route.request.method != 'GET' or not route.request.is_navigation_request():
            await route.fallback()
            return
        response = None
        try:
            response = await route.fetch(timeout=timeout_ms, max_redirects=0)
            raw = await response.text()
            # Las advertencias, el clic adicional y los resultados inesperados
            # mantienen la navegación original para su diagnóstico.
            parsed = BeautifulSoup(raw, 'html.parser')
            warning = parsed.select_one('#ERROR')
            blocked = parsed.select_one('input[name="SALIR"][value="OK"]') or (
                warning is not None and bool(warning.get_text(strip=True)))
            valid = False
            page._dua_lightweight_reason = f'HTTP {response.status}'
            if blocked:
                page._dua_lightweight_reason = 'warning_or_extra_step'
            if response.status == 200 and not blocked:
                try:
                    validate_result(flow.extract_data(raw), dua)
                    valid = True
                except (ValueError, KeyError):
                    page._dua_lightweight_reason = 'raw_detail_not_validated'
            if valid:
                # Comparar TODOS los valores antes de sustituir la representación.
                expected = validate_result(flow.extract_data(raw), dua)
                for element in parsed.find_all(['script', 'link', 'iframe', 'img', 'video', 'audio', 'source', 'object', 'embed']):
                    element.decompose()
                lean = str(parsed)
                if validate_result(flow.extract_data(lean), dua) == expected:
                    page._dua_raw_detail = raw
                    page._dua_lightweight_detail = True
                    page._dua_lightweight_reason = 'applied'
                    await route.fulfill(response=response, body=lean)
                    return
                page._dua_lightweight_reason = 'representation_changed_values'
            await route.fulfill(response=response)
        finally:
            if response is not None:
                await response.dispose()

    await page.route(pattern, capture)
    return pattern, capture
