"""Navegador real, portal simulado: nunca se conecta a TICA."""
import sys
import unittest
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from playwright.async_api import async_playwright
from core.portal_form import (fill_and_submit, expected_fields, validate_submission,
                              FormChangedError, PortalResponseError)
from core.identifiers import dua_fields

FORM = '''<html><body><form action="/hcimppon.aspx" method="post">
<input id="vVCODI_ADUA" name="vVCODI_ADUA" maxlength="3">
<input id="vVANO_PRE" name="vVANO_PRE" maxlength="4">
<input id="vVNUME_CORR" name="vVNUME_CORR" maxlength="6">
<div id="captchaImage"><img src="/Captcha/images/1.jpg"></div>
<input id="_cfield" name="cfield"><button name="DETALLE">Detalle</button>
</form><script>window.gx={O:{ServerClass:'HCiMPPoN'}};</script></body></html>'''


class FormTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(headless=True)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        self.posts = []
        self.response = '<span id="span_NUME_CORRE">021719</span>'
        self.row = dua_fields('001-2026-021719')

        async def server(route):
            if route.request.method == 'POST':
                self.posts.append(route.request.post_data)
                await route.fulfill(body=self.response, content_type='text/html')
            elif route.request.url.endswith('/hcimppon.aspx'):
                await route.fulfill(body=FORM, content_type='text/html')
            else:
                await route.fulfill(body='', status=204)
        await self.context.route('**/*', server)
        await self.page.goto('https://portal.test/hcimppon.aspx')

    async def asyncTearDown(self):
        await self.browser.close()
        await self.pw.stop()

    async def test_values_stay_in_correct_fields_despite_stolen_focus(self):
        await self.page.evaluate("""() => {
            document.querySelector('#vVANO_PRE').onfocus = () =>
                document.querySelector('#vVCODI_ADUA').focus();
        }""")
        await fill_and_submit(self.page, self.row, 'polish', 2000)
        self.assertEqual(len(self.posts), 1)
        validate_submission(self.posts[0], expected_fields(self.row, 'polish'))

    async def test_changed_form_is_never_submitted(self):
        await self.page.evaluate("""() => {
            document.querySelector('#_cfield').onchange = () =>
                document.querySelector('#vVNUME_CORR').value = '999999';
        }""")
        with self.assertRaises(FormChangedError):
            await fill_and_submit(self.page, self.row, 'polish', 2000)
        self.assertEqual(self.posts, [])

    async def test_submit_handler_cannot_send_a_different_dua(self):
        await self.page.evaluate("""() => {
            document.querySelector('form').onsubmit = () =>
                document.querySelector('#vVNUME_CORR').value = '999999';
        }""")
        with self.assertRaises(FormChangedError):
            await fill_and_submit(self.page, self.row, 'polish', 500)
        self.assertEqual(self.posts, [])

    async def test_portal_warning_is_not_reported_as_timeout(self):
        self.response = '<span id="ERROR">Faltan datos o la información no existe.</span>'
        with self.assertRaises(PortalResponseError):
            await fill_and_submit(self.page, self.row, 'polish', 2000)

    async def test_return_to_form_is_detected_without_waiting_for_detail(self):
        self.response = FORM
        with self.assertRaises(PortalResponseError):
            await fill_and_submit(self.page, self.row, 'polish', 2000)

    async def test_duplicate_post_fields_are_rejected(self):
        fields = expected_fields(self.row, 'polish')
        payload = urlencode({('cfield' if k == '_cfield' else k): v for k, v in fields.items()})
        with self.assertRaises(FormChangedError):
            validate_submission(payload + '&vVNUME_CORR=999999', fields)

    async def test_ajax_payload_with_changed_number_is_blocked(self):
        await self.page.evaluate("""() => {
            const button = document.querySelector('[name="DETALLE"]');
            button.type = 'button';
            button.onclick = () => {
                const fields = new URLSearchParams(new FormData(document.querySelector('form')));
                fields.set('vVNUME_CORR', '999999');
                fetch('/hcimppon.aspx', {method: 'POST', body: fields}).catch(() => {});
            };
        }""")
        with self.assertRaises(FormChangedError):
            await fill_and_submit(self.page, self.row, 'polish', 2000)
        self.assertEqual(self.posts, [])
        self.assertEqual(self.page._dua_form_snapshot['submission']['vVNUME_CORR'], ['999999'])

    async def test_valid_ajax_payload_is_accepted(self):
        await self.page.evaluate("""() => {
            const button = document.querySelector('[name="DETALLE"]');
            button.type = 'button';
            button.onclick = () => {
                const fields = new URLSearchParams(new FormData(document.querySelector('form')));
                fetch('/hcimppon.aspx', {method: 'POST', body: fields})
                    .then(r => r.text()).then(html => document.body.innerHTML = html);
            };
        }""")
        await fill_and_submit(self.page, self.row, 'polish', 2000)
        self.assertEqual(len(self.posts), 1)
        validate_submission(self.posts[0], expected_fields(self.row, 'polish'))

    async def test_ajax_mixed_case_url_cannot_send_wrong_year(self):
        await self.page.evaluate("""() => {
            const button = document.querySelector('[name="DETALLE"]');
            button.type = 'button';
            button.onclick = () => {
                const fields = new URLSearchParams(new FormData(document.querySelector('form')));
                fields.set('vVANO_PRE', '9999');
                fetch('/HCiMPPoN.aspx', {method: 'POST', body: fields}).catch(() => {});
            };
        }""")
        with self.assertRaises(FormChangedError):
            await fill_and_submit(self.page, self.row, 'polish', 2000)
        self.assertEqual(self.posts, [])

    async def test_captcha_change_after_resolution_blocks_submission(self):
        with self.assertRaises(FormChangedError):
            await fill_and_submit(self.page, self.row, 'polish', 2000,
                                  captcha_source='/Captcha/images/2.jpg')
        self.assertEqual(self.posts, [])


if __name__ == '__main__':
    unittest.main()
