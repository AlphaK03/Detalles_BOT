"""Diagnóstico reproducible: consultas de solo lectura, artefactos locales."""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from playwright.async_api import async_playwright
from flows.detalles_flow import DetallesFlow
from core.playwright_processor import PlaywrightDUAProcessor


async def probe(args):
    from core.captcha import load_captcha_lookup
    lookup = load_captcha_lookup()
    processor = PlaywrightDUAProcessor(
        {'timeout': args.timeout}, {}, DetallesFlow(), lookup, Event())
    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=True)
    reports = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for dua in args.duas:
            from core.identifiers import normalize_dua, dua_fields
            dua = normalize_dua(dua)
            context = await browser.new_context()
            page = await context.new_page()
            await processor._block_static(page)
            started = time.monotonic()
            report = {'dua': dua, 'documents': []}
            page.on('response', lambda r: report['documents'].append(
                {'status': r.status, 'url': r.url.split('?')[0]}
            ) if r.request.resource_type == 'document' else None)
            try:
                html = await processor._fetch_result(page, dua_fields(dua))
                data = DetallesFlow().extract_data(html)
                processor._validate(data, dua)
                report.update(status='success', fields=len(data.columns),
                              extracted=data.iloc[0]['numero_del_dua'])
            except Exception as exc:
                report.update(status='pending', error=f'{type(exc).__name__}: {exc}')
            finally:
                report['seconds'] = round(time.monotonic() - started, 2)
                report['url'] = page.url.split('?')[0]
                (folder / f'{dua}.html').write_text(await page.content(), encoding='utf-8')
                await page.screenshot(path=str(folder / f'{dua}.png'), full_page=True)
                reports.append(report)
                print(json.dumps(report, ensure_ascii=True), flush=True)
                await context.close()
        await browser.close()
    (folder / 'report.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('duas', nargs='+')
    parser.add_argument('--timeout', type=int, default=30)
    parser.add_argument('--output', default='logs/diagnostico_astracode')
    args = parser.parse_args()
    if len(args.duas) > 4:
        parser.error('El diagnóstico acepta como máximo 4 DUAs por ejecución.')
    asyncio.run(probe(args))
