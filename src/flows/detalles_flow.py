"""detalles_flow.py — Flujo para consultar el DETALLE de una DUA en el portal TICA.

Implementa BaseFlow para la URL:
    https://ticaconsultas.hacienda.go.cr/Tica/hcimppon.aspx

Navegación:
  1. Formulario principal (Aduana / Año / Número / CAPTCHA) → click DETALLE
  2. Página intermedia con formulario LINEAS (confirma que el submit fue exitoso)
  3. Página de detalle con span_CODI_ADUAN (datos listos para extraer)
"""
import re
import logging

import pandas as pd
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from flows.base_flow import BaseFlow


class DetallesFlow(BaseFlow):

    _START_URL = 'https://ticaconsultas.hacienda.go.cr/Tica/hcimppon.aspx'

    @property
    def start_url(self) -> str:
        return self._START_URL

    def on_before_form(self, driver, attempt: int, timeout: int) -> None:
        """
        A partir del tercer intento descarta la página de rectificación si aparece.
        El portal la muestra ocasionalmente cuando un DUA fue consultado recientemente.
        """
        if attempt < 3:
            return
        try:
            btn = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//input[@name='SALIR' and @value='OK']")
                )
            )
            btn.click()
            logging.info("Página de rectificación descartada (intento %d).", attempt)
        except TimeoutException:
            pass  # No había página de rectificación, continuar normalmente

    def fill_form(self, driver, row, captcha_text: str, timeout: int) -> None:
        driver.execute_script("document.body.style.zoom='25%'")

        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.ID, 'vVCODI_ADUA'))
        )

        for field_id, value in [
            ('vVCODI_ADUA', str(row['Aduana'])),
            ('vVANO_PRE',   str(row['Año'])),
            ('vVNUME_CORR', str(row['Número'])),
            ('_cfield',     captcha_text),
        ]:
            el = driver.find_element(By.ID, field_id)
            el.clear()
            el.send_keys(value)

        btn = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.NAME, 'DETALLE'))
        )
        try:
            btn.click()
        except Exception:
            # Si otro elemento cubre el botón, forzar el clic via JS
            driver.execute_script("arguments[0].click();", btn)

    def wait_for_result(self, driver, timeout: int) -> None:
        # Paso 1: confirmar que el formulario fue enviado (página intermedia)
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.NAME, 'LINEAS'))
        )
        # Paso 2: esperar que los datos de detalle estén disponibles
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.ID, 'span_CODI_ADUAN'))
        )

    def extract_data(self, page_source: str) -> pd.DataFrame:
        soup = BeautifulSoup(page_source, 'html.parser')

        def clean(text: str) -> str:
            text = text.replace('\xa0', ' ')
            text = re.sub(r'[\n\r\t]+', ' ', text)
            text = text.replace(',', ' ')
            text = text.replace(';', ' ')
            text = re.sub(r' {2,}', ' ', text)
            return text.strip()

        def get(ids, sep=' - ') -> str:
            parts = []
            for id_ in ids:
                el = soup.find('span', {'id': id_})
                if el:
                    t = clean(el.get_text())
                    if t:
                        parts.append(t)
            return sep.join(parts)

        def gets(ids) -> str:
            return get(ids, sep=' ')

        data = {
            'aduana':                    get(['span_CODI_ADUAN', 'span_vVADUD20']),
            'regimen':                   get(['span_CODI_REGI', 'span_vVIMREGDSC']),
            'fecha_de_registro':         gets(['span_FECH_INGSI', 'span_HORA_INGSI']),
            'numero_del_dua':            get(['span_CODI_ADUAN', 'span_ANO_PRESE', 'span_NUME_CORRE'], sep='-'),
            'tipo_semaforo':             gets(['span_vVTAFORDSC']),
            'tipo_carga':                gets(['span_vVTPOCARGA']),
            'solic_inmediata_tipo_revision': gets(['span_vVAFORO']),
            'pago_impuestos':            gets(['span_vDEBEIMP']),
            'aplica_duca_f':             gets(['span_vRESPFAUCA']),
            'confirmacion_automatica':   gets(['span_vDSCCONFAUT']),
            'nro_de_envio':              gets(['span_NUME_ORDEN']),
            'modalidad':                 get(['span_TIPO_OPERA', 'span_vIMSUBREGDSC']),
            'tipo_de_dua':               gets(['span_vVDSCDOCADU']),
            'forma_de_despacho':         get(['span_DESP_URGE', 'span_vVDSCDESP']),
            'estado':                    gets(['span_ESTADO', 'span_vDUASTSDSC']),
            'momento_de_asociacion_inventario': gets(['span_vVASOCINVENTARIO']),
            'dua_es_correlac_consolidado': get(['span_vVCORR', 'span_vVDUACORRE', 'span_vDUA_CORRE']),
            'tiene_precinto_electronico': gets(['span_vVPRECELECT']),
            'supervision_de_descarga':   gets(['span_vVSUP_DESCARGA', 'FECHADESCARGA',
                                               'span_FECHA_DESCARGA', 'FUNCIODESCARGA',
                                               'span_vFUNDESC', 'span_vVFUNNOMB']),
            'afecta_valor_referencia':   gets(['span_vVALORREFERE']),
            'aplica_moratoria_alivio_fiscal': gets(['span_vAPLIMORALFIS']),
            'declarante':                (get(['span_TCODI_AGENT', 'span_CODI_AGENT']) + ' ' +
                                          gets(['span_vVNOMDECL'])).strip(),
            'agente':                    (get(['span_TI_AGENTE', 'span_CI_AGENTE']) + ' ' +
                                          gets(['span_vVNOMAGENTE'])).strip(),
            'importe_total_facturas':    gets(['span_TOT_FACT', 'span_vVMONDSC']),
            'tipo_de_cambio_de_compra':  (gets(['span_TIPCAMCOM']) +
                                          ' Tipo de Cambio de Venta: ' +
                                          gets(['span_TIPCAMVEN'])),
            'medio_de_transporte':       gets(['span_vVVIADSC']),
            'empresa':                   (get(['span_vVTDOCTRA', 'span_vVCDOCTRA']) + ' ' +
                                          gets(['span_vVDNOM'])).strip(),
            'aduana_de_ingreso':         gets(['span_vVADUIS', 'span_vVADUDSC2']),
            'lugar_de_localizacion':     gets(['span_CODI_ALMA', 'span_vVDRSOCIAL']),
            'aduana_destino':            gets(['span_vVADUDEST', 'span_vVADUDSC3']),
            'lugar_de_destino':          get(['span_vVCALMDEST', 'span_vVRGRSOC']),
            'total_bultos':              gets(['span_TCANT_BULT']),
            'total_peso_bruto':          gets(['span_TPESO_BRUT']),
            'total_peso_neto':           gets(['span_TPESO_NETO']),
            'total_valor_aduanas':       gets(['span_TVAD_INCR']),
            'garantia':                  (gets(['span_NUM_GARAN']) + ' por ' +
                                          gets(['span_TOT_GARAN'])),
            'nombre_vapor_o_medio_transporte_de_las_mercancias': gets(['span_NOM_VAPOR']),
            'lineas_de_dua':             gets(['span_vVLINEAS']),
        }
        return pd.DataFrame([data])
