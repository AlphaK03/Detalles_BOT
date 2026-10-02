"""http_processor.py — Motor HTTP de procesamiento de DUAs (sin navegador).

Sustituye a DUAProcessor (Selenium) con requests.Session:
  GET  hcimppon.aspx           → extrae __VIEWSTATE, __EVENTVALIDATION, CAPTCHA URL
  POST hcimppon.aspx           → sigue redirect automático a hcimdpola.aspx?{token}
  BeautifulSoup(response.text) → reutiliza DetallesFlow.extract_data() sin cambios
"""
import os
import logging
from threading import Lock, Event
from typing import Callable
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

from flows.base_flow import BaseFlow

_PORTAL_BASE = 'https://ticaconsultas.hacienda.go.cr'
_FORM_URL    = f'{_PORTAL_BASE}/Tica/hcimppon.aspx'

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'es-CR,es;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

_PROCESSED_DUAS = set()
_PROCESSED_LOCK = Lock()


def load_processed_duas_from_log(log_path: str) -> None:
    """Pre-carga DUAs ya procesados desde el log dedicado. Llamar antes de iniciar el executor."""
    if not os.path.exists(log_path):
        return
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            with _PROCESSED_LOCK:
                for line in f:
                    dua = line.strip()
                    if dua:
                        _PROCESSED_DUAS.add(dua)
        logging.info("Cargados %d DUAs previos desde %s.", len(_PROCESSED_DUAS), log_path)
    except Exception as e:
        logging.error("No se pudo cargar DUAs previos: %s", e)


class HttpDUAProcessor:
    """
    Procesa DUAs vía HTTP puro (requests.Session), sin abrir ningún navegador.
    Una instancia por hilo worker — cada una mantiene su propia sesión HTTP.
    """

    def __init__(
        self,
        machine_config: dict,
        output_paths: dict,
        flow: BaseFlow,
        names_df: pd.DataFrame,
        lock: Lock,
        stop_event: Event,
    ):
        self.machine = machine_config
        self.output_paths = output_paths
        self._flow = flow
        self.names_df = names_df
        self.lock = lock
        self.stop_event = stop_event
        self._session = self._new_session()

    # ── API pública ──────────────────────────────────────────────────────────

    def process_dua(
        self,
        index: int,
        row,
        progress_callback: Callable[[int, str], None],
    ) -> None:
        """
        Procesa un DUA con reintentos.
        Llama progress_callback(index, status) con 'success', 'failed' o 'skipped'.
        """
        if self.stop_event.is_set():
            return

        dua_number = row['NroDUA']
        max_retries = self.machine['max_retries']

        for attempt in range(1, max_retries + 1):
            if self.stop_event.is_set():
                return
            try:
                html = self._fetch_result(row)
                data = self._flow.extract_data(html)
                self._validate(data, dua_number)

                extracted_dua = data.iloc[0]['numero_del_dua'].strip()

                with _PROCESSED_LOCK:
                    if extracted_dua in _PROCESSED_DUAS:
                        logging.warning("DUA %s ya procesado. Omitido.", extracted_dua)
                        progress_callback(index, 'skipped')
                        return
                    _PROCESSED_DUAS.add(extracted_dua)

                with self.lock:
                    self._write_csv(data)
                    self._log_processed(extracted_dua)

                logging.info("DUA %s guardado.", extracted_dua, extra={'tag': 'SUCCESS'})
                progress_callback(index, 'success')
                return

            except Exception as e:
                logging.warning("[%s] Intento %d/%d: %s: %s",
                                dua_number, attempt, max_retries, type(e).__name__, e)
                self._session = self._new_session()

        logging.error("[%s] Reintentos agotados.", dua_number)
        self._log_failed(dua_number)
        progress_callback(index, 'failed')

    def close(self) -> None:
        self._session.close()

    # ── Internals ────────────────────────────────────────────────────────────

    def _new_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update(_HEADERS)
        return s

    def _fetch_result(self, row) -> str:
        """GET el formulario, POST los datos del DUA y retorna el HTML de resultado."""
        timeout = self.machine['timeout']

        resp = self._session.get(_FORM_URL, timeout=timeout)
        resp.raise_for_status()
        logging.debug("GET %s → %s", _FORM_URL, resp.url)
        # Volcado único para diagnóstico — eliminar una vez resuelto el CAPTCHA
        _dump_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                                  'logs', 'debug_html.html')
        if not os.path.exists(_dump_path):
            os.makedirs(os.path.dirname(_dump_path), exist_ok=True)
            with open(_dump_path, 'w', encoding='utf-8') as _f:
                _f.write(resp.text)
            logging.info("HTML volcado en: %s", _dump_path)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # El portal a veces muestra una página de rectificación antes del formulario
        if soup.find('input', {'name': 'SALIR', 'value': 'OK'}):
            logging.info("Página de rectificación detectada. Descartando...")
            payload = self._build_payload(soup)
            payload['SALIR'] = 'OK'
            resp = self._session.post(_FORM_URL, data=payload, timeout=timeout)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')

        captcha_text = self._resolve_captcha(soup)

        payload = self._build_payload(soup)
        payload.update({
            'vVCODI_ADUA': str(row['Aduana']),
            'vVANO_PRE':   str(row['Año']),
            'vVNUME_CORR': str(row['Número']),
            '_cfield':     captcha_text,
        })

        # requests.Session sigue el redirect a hcimdpola.aspx?{token} automáticamente
        result = self._session.post(_FORM_URL, data=payload, timeout=timeout)
        result.raise_for_status()
        return result.text

    def _build_payload(self, soup: BeautifulSoup) -> dict:
        """Extrae todos los campos del form ASP.NET (ViewState, hidden inputs, etc.)."""
        form = soup.find('form')
        if not form:
            raise ValueError("No se encontró el formulario en la página.")
        payload = {}
        for inp in form.find_all('input'):
            name = inp.get('name')
            itype = inp.get('type', 'text').lower()
            if name and itype != 'submit':
                payload[name] = inp.get('value', '')
        # Incluir el botón DETALLE que se "clica"
        btn = form.find('input', {'name': 'DETALLE'})
        if btn:
            payload['DETALLE'] = btn.get('value', 'DETALLE')
        return payload

    def _resolve_captcha(self, soup: BeautifulSoup) -> str:
        """Extrae el número de imagen del CAPTCHA y lo resuelve por lookup."""
        import re as _re

        captcha_url = None

        # Estrategia 1: div#captchaImage img (presente en el DOM del browser tras ejecutar JS)
        div = soup.find('div', {'id': 'captchaImage'})
        if div:
            img = div.find('img')
            if img:
                captcha_url = urljoin(_PORTAL_BASE, img.get('src', ''))

        # Estrategia 2: buscar el patrón /Captcha/images/N.jpg en todo el HTML
        # (puede estar en un <script>, data-attr, o referencia oculta)
        if not captcha_url:
            m = _re.search(r'Captcha/images/(\d+)\.jpg', str(soup), _re.I)
            if m:
                captcha_url = f"{_PORTAL_BASE}/Tica/Captcha/images/{m.group(1)}.jpg"

        if not captcha_url:
            raise ValueError("No se encontró la URL del CAPTCHA en el HTML de la página.")

        matches = self.names_df.loc[self.names_df['Path'] == captcha_url, 'Word'].values
        if len(matches) == 0:
            raise ValueError(f"CAPTCHA no encontrado en lookup: {captcha_url}")
        return str(matches[0])

    def _validate(self, data: pd.DataFrame, dua_number: str) -> None:
        if (data is None or data.empty
                or 'numero_del_dua' not in data.columns
                or data['numero_del_dua'].iloc[0].strip() == ''):
            raise ValueError(f"Datos vacíos para DUA {dua_number}")

    def _write_csv(self, data: pd.DataFrame) -> None:
        path = self.output_paths['output_csv']
        header = not os.path.exists(path)
        data.to_csv(path, mode='a', header=header, index=False, encoding='utf-8-sig')

    def _log_processed(self, dua_number: str) -> None:
        with open(self.output_paths['processed_log'], 'a', encoding='utf-8') as f:
            f.write(f"{dua_number}\n")

    def _log_failed(self, dua_number: str) -> None:
        with open(self.output_paths['failed_duas'], 'a', encoding='utf-8') as f:
            f.write(f"{dua_number}\n")
