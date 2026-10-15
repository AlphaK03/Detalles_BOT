"""Llenado por ID y comprobación del formulario antes de enviar la consulta."""
from urllib.parse import parse_qs, urlsplit
import re


class FormChangedError(RuntimeError):
    pass


class PortalResponseError(RuntimeError):
    pass


def expected_fields(row, captcha):
    return {'vVCODI_ADUA': str(row['Aduana']), 'vVANO_PRE': str(row['Año']),
            'vVNUME_CORR': str(row['Número']), '_cfield': captcha}


def validate_submission(body, expected):
    values = parse_qs(body or '', keep_blank_values=True)
    for field, value in expected.items():
        name = 'cfield' if field == '_cfield' else field
        if values.get(name) != [value]:
            raise FormChangedError(f'El campo {field} cambió antes de enviar la consulta.')


async def wait_form_ready(page, timeout_ms):
    # Esperar inicialización del formulario y los manejadores GeneXus.
    await page.wait_for_function("""() => document.readyState === 'complete'
        && window.gx?.O?.ServerClass?.toLowerCase() === 'hcimppon'
        && !!document.querySelector('#_cfield')""", timeout=timeout_ms)


async def fill_and_submit(page, row, captcha, timeout_ms, captcha_source=None):
    expected = expected_fields(row, captcha)
    await wait_form_ready(page, timeout_ms)
    captcha_src = await page.locator('#captchaImage img').get_attribute('src')
    if captcha_source is not None and captcha_src != captcha_source:
        raise FormChangedError('El CAPTCHA cambió después de resolverlo; se renovará el formulario.')
    await page.evaluate("""(fields) => {
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
        for (const [id, value] of Object.entries(fields)) {
            const el = document.getElementById(id);
            if (!(el instanceof HTMLInputElement) || el.disabled || el.readOnly)
                throw new Error('Campo no disponible: ' + id);
            el.focus();
            setter.call(el, value);
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
            el.blur();
        }
    }""", expected)

    # Conservar una captura de valores reales, no los atributos value del HTML.
    observed = await page.evaluate("""(ids) => Object.fromEntries(ids.map(
        id => [id, document.getElementById(id)?.value]))""", list(expected))
    if observed != expected:
        raise FormChangedError(f'El formulario cambió durante el llenado: {observed}')
    page._dua_form_snapshot = {'requested': row['NroDUA'], 'fields': observed, 'captcha_src': captcha_src}
    blocked = []

    async def guard(route):
        request = route.request
        if request.method == 'POST':
            submitted = parse_qs(request.post_data or '', keep_blank_values=True)
            page._dua_form_snapshot['submission'] = {
                ('cfield' if field == '_cfield' else field): submitted.get(
                    'cfield' if field == '_cfield' else field, [])
                for field in expected}
            try:
                validate_submission(request.post_data, expected)
            except FormChangedError as exc:
                blocked.append(exc)
                await route.abort()
                try:
                    await page.evaluate('window.__duaSubmissionBlocked = true')
                except Exception:
                    pass
                return
        await route.fallback()

    pattern = re.compile(r'.*/hcimppon\.aspx(?:\?.*)?$', re.IGNORECASE)
    await page.route(pattern, guard)
    try:
        # Comprobar y hacer clic en la misma tarea JS: ningún cambio de foco
        # puede redirigir pulsaciones de teclado a otro campo.
        verdict = await page.evaluate("""({fields, src}) => {
            for (const [id, value] of Object.entries(fields))
                if (document.getElementById(id)?.value !== value) return id;
            if (document.querySelector('#captchaImage img')?.getAttribute('src') !== src)
                return 'captcha';
            const button = document.querySelector('[name="DETALLE"]');
            if (!button || button.disabled) return 'DETALLE';
            window.__duaSubmitted = true;
            window.__duaSubmissionBlocked = false;
            button.click();
            return '';
        }""", {'fields': expected, 'src': captcha_src})
        if verdict:
            raise FormChangedError(f'El formulario cambió antes del envío: {verdict}')
        try:
            await page.wait_for_function(r"""() =>
                window.__duaSubmissionBlocked === true
                || !!document.querySelector('#span_NUME_CORRE')
                || !!document.querySelector('input[name="SALIR"][value="OK"]')
                || !!document.querySelector('#ERROR')?.textContent.trim()
                || /\/hcimsg\d*\.aspx$/i.test(location.pathname)
                || (document.readyState === 'complete' && window.__duaSubmitted !== true
                    && !!document.querySelector('#vVCODI_ADUA'))
            """, timeout=timeout_ms)
        except Exception:
            if blocked:
                raise blocked[0] from None
            raise
        if blocked:
            raise blocked[0]
        await page.wait_for_load_state('domcontentloaded', timeout=timeout_ms)
        error = page.locator('#ERROR')
        if await error.count():
            text = (await error.inner_text()).strip()
            if text:
                raise PortalResponseError(text)
        if urlsplit(page.url).path.lower().rsplit('/', 1)[-1].startswith('hcimsg'):
            raise PortalResponseError('El portal devolvió una advertencia en lugar del detalle.')
        if await page.locator('#vVCODI_ADUA').count() and not await page.locator('#span_NUME_CORRE').count():
            raise PortalResponseError('El portal devolvió el formulario sin completar la consulta.')
    finally:
        await page.unroute(pattern, guard)
