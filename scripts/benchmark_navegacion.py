"""Comparación real explícita, máximo cuatro DUAs distintos y sin cola de producción."""
import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from playwright.async_api import async_playwright
from core.captcha import load_captcha_lookup
from core.detail_navigation import install_lightweight_detail
from core.identifiers import dua_fields, normalize_dua, validate_result
from core.playwright_processor import PlaywrightDUAProcessor
from flows.detalles_flow import DetallesFlow


async def benchmark(args):
    folder = Path(args.output).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    flow = DetallesFlow()
    processor = PlaywrightDUAProcessor({'timeout': args.timeout, 'lightweight_details': False}, {}, flow, load_captcha_lookup(), Event())
    results, original = [], {}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            for strategy in ('aislado', 'reutilizado', 'detalle_ligero', 'combinado'):
                context = page = None
                try:
                    for dua in args.duas:
                        start = time.perf_counter()
                        if context is None:
                            context = await browser.new_context()
                            page = await context.new_page()
                            await processor._block_static(page)
                        counter = {'requests': 0, 'responses': 0, 'scripts': 0, 'documents': 0}
                        def request(req):
                            counter['requests'] += 1
                            counter['scripts'] += req.resource_type == 'script'
                            counter['documents'] += req.resource_type == 'document'
                        def response(resp):
                            counter['responses'] += 1
                        page.on('request', request)
                        page.on('response', response)
                        report = {'strategy': strategy, 'dua': dua}
                        page._dua_raw_detail = None
                        page._dua_lightweight_detail = False
                        hook = None
                        if strategy in ('detalle_ligero', 'combinado'):
                            hook = await install_lightweight_detail(page, flow, dua, args.timeout * 1000)
                        try:
                            html = await processor._fetch_result(page, dua_fields(dua))
                            record = validate_result(flow.extract_data(html), dua)
                            if strategy == 'aislado':
                                original[dua] = record
                            same = record == original.get(dua)
                            report.update(status='success', fields=len(record), same_38_values=same,
                                          lightweight_used=page._dua_lightweight_detail,
                                          lightweight_reason=getattr(page, '_dua_lightweight_reason', None))
                            if not same:
                                report['changed_fields'] = [key for key in record if record[key] != original.get(dua, {}).get(key)]
                            (folder / f'{strategy}_{dua}.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
                        except Exception as exc:
                            report.update(status='pending', error=f'{type(exc).__name__}: {exc}')
                            (folder / f'{strategy}_{dua}.html').write_text(await page.content(), encoding='utf-8')
                        finally:
                            report.update(counter)
                            report['seconds'] = round(time.perf_counter() - start, 3)
                            results.append(report)
                            print(json.dumps(report, ensure_ascii=True), flush=True)
                            page.remove_listener('request', request)
                            page.remove_listener('response', response)
                            if hook:
                                await page.unroute(*hook)
                            if strategy not in ('reutilizado', 'combinado'):
                                await context.close()
                                context = page = None
                finally:
                    if context is not None:
                        await context.close()
        finally:
            await browser.close()
    (folder / 'comparacion.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('duas', nargs='+', type=normalize_dua)
    parser.add_argument('--timeout', type=int, default=30)
    parser.add_argument('--output', default='logs/benchmark_navegacion_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    args = parser.parse_args()
    if len(args.duas) > 4 or len(set(args.duas)) != len(args.duas):
        parser.error('Use entre uno y cuatro DUAs diferentes; cada estrategia los consulta una vez.')
    asyncio.run(benchmark(args))
