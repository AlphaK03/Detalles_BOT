# processors.py

import os
import re
import time
import gc



import pandas as pd
import logging
from threading import Lock
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from selenium.common.exceptions import WebDriverException
from selenium.common.exceptions import (
    NoSuchElementException, TimeoutException, StaleElementReferenceException
)


# Conjunto global de DUAs ya procesados (clave: numero_del_dua)
PROCESSED_DUAS = set()
PROCESSED_DUAS_LOCK = Lock()

# Definir excepción personalizada para el caso de no encontrar filas
class NoRowsException(Exception):
    pass


def set_zoom_level(driver, zoom_percentage):
    """Ajustar el nivel de zoom de la página."""
    zoom_script = f"document.body.style.zoom='{zoom_percentage}%'"
    driver.execute_script(zoom_script)


import requests

def esperar_disponibilidad_pagina(url, intervalo=10, max_intentos=0):
    intentos = 0
    while True:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                logging.info(f"La página {url} está disponible nuevamente.")
                return
        except requests.RequestException:
            pass
        intentos += 1
        logging.warning(f"La página {url} aún no está disponible. Intento {intentos}. Reintentando en {intervalo} segundos...")
        time.sleep(intervalo)
        if max_intentos and intentos >= max_intentos:
            logging.error(f"No se pudo acceder a la página {url} después de {max_intentos} intentos.")
            break


class DUAProcessor:
    def __init__(self, config, names_df, lock, stop_event):
        self.config = config
        self.names_df = names_df
        self.lock = lock
        self.stop_event = stop_event
        self.driver = self.get_browser_instance()
        self.max_index_processed = -1

        # Crear la carpeta de capturas de pantalla si no existe
        self.screenshot_path = self.config.get('screenshot_path', 'screenshots')
        if not os.path.exists(self.screenshot_path):
            os.makedirs(self.screenshot_path)

    def get_browser_instance(self):
        options = EdgeOptions()

        #options.add_argument('--headless')

        options.add_argument('--disable-extensions')
        options.add_argument('--disable-popup-blocking')
        options.add_argument('--disable-notifications')
        options.add_argument('--mute-audio')
        options.add_argument('--no-first-run')
        options.add_argument('--disable-background-timer-throttling')
        options.add_argument('--disable-renderer-backgrounding')
        options.add_argument('--disable-translate')
        options.add_argument('--disable-features=NetworkService')
        options.add_argument('--disable-blink-features=AutomationControlled')

        service = EdgeService(executable_path=self.config['edge_driver_path'])
        driver = webdriver.Edge(service=service, options=options)

        blocked_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.css', '.woff', '.woff2', '.ttf', '.otf', '.svg']

        def interceptor(request):
            if any(request.path.endswith(ext) for ext in blocked_extensions):
                request.abort()

        driver.request_interceptor = interceptor

        #driver.get('https://portaltica.hacienda.go.cr/TicaExterno/hcimppon.aspx')
        return driver

    def process_dua(self, index, row, progress_callback):
        """
        Nuevo flujo: Se navega a la página principal, se llena el formulario y se hace clic en el botón
        'DETALLE'. Luego, se espera a que cargue la página de detalle y se extraen directamente los datos importantes.
        """
        try:
            if self.stop_event.is_set():
                return
            dua_number = row['NroDUA']
            self.set_current_dua(dua_number, row)
            max_retries = self.config['max_retries']
            retry_count = 0

            while retry_count < max_retries and not self.stop_event.is_set():
                try:
                    # Volver a la página principal
                    try:
                        self.driver.get('https://ticaconsultas.hacienda.go.cr/Tica/hcimppon.aspx')
                    except WebDriverException as e:
                        if "ERR_NAME_NOT_RESOLVED" in str(e):
                            logging.warning("Error DNS: página no disponible. Esperando disponibilidad...")
                            esperar_disponibilidad_pagina("https://ticaconsultas.hacienda.go.cr/Tica/hcimppon.aspx",
                                                          intervalo=10)
                            try:
                                self.driver.get('https://ticaconsultas.hacienda.go.cr/Tica/hcimppon.aspx')
                            except Exception as e2:
                                logging.error(f"No se pudo cargar la página tras la espera: {e2}")
                                self.log_failed_dua(dua_number)
                                return
                        else:
                            raise
                    # Opcional: pausa corta para asegurarnos que la página se cargue
                    # time.sleep(2)
                    set_zoom_level(self.driver, 25)

                    # Procesar la página principal: llenar el formulario y hacer clic en DETALLE
                    if not self.process_main_page(row):
                        raise Exception("Error en process_main_page")

                    # (Opcional) En el tercer intento, si aparece una página de rectificación, clic en OK para continuar
                    if retry_count == 2:
                        try:
                            WebDriverWait(self.driver, 5).until(
                                EC.presence_of_element_located((By.XPATH, "//input[@name='SALIR' and @value='OK']"))
                            )
                            ok_button = self.driver.find_element(By.XPATH, "//input[@name='SALIR' and @value='OK']")
                            logging.info("Botón OK detectado en el tercer intento. Haciendo clic para continuar.")
                            ok_button.click()
                        except TimeoutException:
                            logging.info("No se detectó la página de rectificación en el tercer intento.")

                    # Esperar a que la página de detalle cargue completamente, por ejemplo que aparezca el span del código de aduana
                    WebDriverWait(self.driver, self.config['timeout']).until(
                        EC.presence_of_element_located((By.ID, 'span_CODI_ADUAN'))
                    )
                    # Opcional: time.sleep(2)
                    current_page_source = self.driver.page_source

                    # Extraer la información importante de la página de detalle
                    new_data = self.extract_important_data(current_page_source)
                    if (new_data is None or new_data.empty or
                            'numero_del_dua' not in new_data.columns or
                            new_data['numero_del_dua'].iloc[0].strip() == ""):
                        raise Exception(f"Datos vacíos o inválidos extraídos para el DUA: {row['Número']}")

                    # Tomar el número del DUA desde la página (clave única)
                    extracted_dua = new_data.iloc[0]['numero_del_dua'].strip()
                    logging.info(f"Dua extraída: {extracted_dua}")

                    # === NUEVO: control global de duplicados por numero_del_dua ===
                    with PROCESSED_DUAS_LOCK:
                        if extracted_dua in PROCESSED_DUAS:
                            logging.warning(
                                f"DUA {extracted_dua} ya estaba procesado (set global). "
                                f"No se escribirá de nuevo."
                            )
                            # Consideramos este DUA como ya atendido y salimos del método
                            return
                        # Marcar este DUA como procesado
                        PROCESSED_DUAS.add(extracted_dua)
                    # === FIN CONTROL DUPLICADOS ===

                    # Guardar los datos en el CSV (protegido por el lock del archivo)
                    output_csv_path = self.config['output_csv']
                    with self.lock:
                        if not os.path.exists(output_csv_path):
                            new_data.to_csv(output_csv_path, mode='w', header=True, index=False, encoding='utf-8-sig')
                        else:
                            new_data.to_csv(output_csv_path, mode='a', header=False, index=False, encoding='utf-8-sig')

                        # Actualizar progreso dentro del mismo lock
                        if index > self.max_index_processed:
                            self.max_index_processed = index
                            progress_callback(self.max_index_processed)

                    break  # Salir del bucle si todo salió bien

                except (
                StaleElementReferenceException, NoSuchElementException, TimeoutException, WebDriverException) as e:
                    retry_count += 1
                    logging.warning(
                        f"Error al procesar DUA {row['Número']}: {e}. Reintentando ({retry_count}/{max_retries})...")
                    time.sleep(2)
                    continue
                except Exception as e:
                    retry_count += 1
                    logging.exception(
                        f"Error al procesar DUA {row['Número']}: {e}. Reintentando ({retry_count}/{max_retries})...")
                    time.sleep(2)
                    continue

            if retry_count >= max_retries:
                logging.error(f"Máximo de reintentos alcanzado para el DUA {row['numero_del_dua']}. Reiniciando navegador.")
                self.driver.quit()
                self.driver = self.get_browser_instance()
                self.log_failed_dua(row['numero_del_dua'])

            # Regresar a la página principal para el siguiente DUA
            self.driver.get('https://ticaconsultas.hacienda.go.cr/Tica/hcimppon.aspx')
        except Exception as e:
            logging.exception(f"Error general al procesar DUA {dua_number}: {e}")

    def process_main_page(self, row):
        dua_number = row['NroDUA']
        if self.stop_event.is_set():
            return False
        try:
            max_retries = 3
            retries = 0
            while retries < max_retries and not self.stop_event.is_set():
                try:
                    # Navegar a la página principal
                    self.driver.get('https://ticaconsultas.hacienda.go.cr/Tica/hcimppon.aspx')
                    #time.sleep(2)  # <-- Nueva pausa de 2s
                    # Establecer el zoom de la página al 25%
                    set_zoom_level(self.driver, 25)

                    # Esperar a que el captcha esté presente
                    captcha_image_element = WebDriverWait(self.driver, self.config['timeout']).until(
                        EC.presence_of_element_located((By.XPATH, "//div[@id='captchaImage']/img"))
                    )
                    captcha_url = captcha_image_element.get_attribute('src')
                    captcha_word = self.names_df.loc[self.names_df['Path'] == captcha_url, 'Word'].values
                    captcha_text = captcha_word[0] if len(captcha_word) > 0 else ''

                    # Ingresar los datos del DUA
                    WebDriverWait(self.driver, self.config['timeout']).until(
                        EC.presence_of_element_located((By.ID, 'vVCODI_ADUA'))
                    )
                    self.driver.find_element(By.ID, 'vVCODI_ADUA').clear()
                    self.driver.find_element(By.ID, 'vVCODI_ADUA').send_keys(row['Aduana'])
                    self.driver.find_element(By.ID, 'vVANO_PRE').clear()
                    self.driver.find_element(By.ID, 'vVANO_PRE').send_keys(row['Año'])
                    self.driver.find_element(By.ID, 'vVNUME_CORR').clear()
                    self.driver.find_element(By.ID, 'vVNUME_CORR').send_keys(row['Número'])
                    self.driver.find_element(By.ID, '_cfield').clear()
                    self.driver.find_element(By.ID, '_cfield').send_keys(captcha_text)

                    # Botón 'DETALLE'
                    detalle_button = WebDriverWait(self.driver, self.config['timeout']).until(
                        EC.element_to_be_clickable((By.NAME, 'DETALLE'))
                    )

                    try:
                        # Intentar hacer clic en el botón 'DETALLE'
                        detalle_button.click()
                    except WebDriverException:
                        # Si otro elemento está cubriendo el botón, usar JS
                        logging.warning("Elemento 'DETALLE' bloqueado, intentando forzar el clic con JavaScript.")
                        self.driver.execute_script("arguments[0].click();", detalle_button)

                    # Esperar a que cargue la siguiente página
                    WebDriverWait(self.driver, self.config['timeout']).until(
                        EC.presence_of_element_located((By.NAME, 'LINEAS'))
                    )
                    #time.sleep(2)  # <-- Nueva pausa de 2s tras cargar la página
                    return True

                except WebDriverException as e:
                    if "ERR_NAME_NOT_RESOLVED" in str(e):
                        logging.warning("Error DNS: página no disponible. Esperando disponibilidad...")
                        esperar_disponibilidad_pagina("https://ticaconsultas.hacienda.go.cr/Tica/hcimppon.aspx",
                                                      intervalo=10)
                        continue
                    retries += 1
                    logging.warning(
                        f"WebDriverException para DUA {dua_number}: {e}. Reintentando ({retries}/{max_retries})...")
                    continue

                except (TimeoutException, NoSuchElementException, StaleElementReferenceException, WebDriverException) as e:
                    retries += 1
                    logging.warning(
                        f"Error al procesar la página principal para DUA {dua_number}: {e}. "
                        f"Reintentando ({retries}/{max_retries})..."
                    )
                    continue
                except Exception as e:
                    self.driver.save_screenshot(f'error_{dua_number}.png')
                    logging.error(f"Error en process_main_page para DUA {dua_number}: {e}")
                    self.log_failed_dua(dua_number)
                    return False

            logging.error(f"No se pudo procesar la página principal para DUA {dua_number} tras varios intentos.")
            self.log_failed_dua(dua_number)
            return False

        except Exception as e:
            logging.error(f"Error en la página principal para DUA {dua_number}: {e}")
            self.log_failed_dua(dua_number)
            return False

    def extract_important_data(self, current_page_source):
        """
        Extrae los datos importantes de la página de detalle (después de hacer clic en DETALLE)
        y retorna un DataFrame con una fila que contiene la información requerida.
        """
        soup = BeautifulSoup(current_page_source, 'html.parser')
        time.sleep(0.5)

        def clean_text(text: str) -> str:
            # Reemplaza tabs, saltos de línea, NBSP y espacios múltiples
            text = text.replace('\xa0', ' ')  # NBSP
            text = re.sub(r'\s+', ' ', text)  # Cualquier \t, \n, \r, o espacio repetido → 1 espacio
            return text.strip()

        def get_combined_text(ids):
            texts = []
            for id_ in ids:
                elem = soup.find('span', {'id': id_})
                if elem:
                    raw = elem.get_text()  # sin strip=True, ya limpiamos nosotros
                    text = clean_text(raw)
                    if text:
                        texts.append(text)
            return ' - '.join(texts)

        def get_combined_text_numero_del_dua(ids):
            texts = []
            for id_ in ids:
                elem = soup.find('span', {'id': id_})
                if elem:
                    raw = elem.get_text()
                    text = clean_text(raw)
                    if text:
                        texts.append(text)
            return '-'.join(texts)

        def get_combined_text_by_ids_with_space(ids):
            texts = []
            for id_ in ids:
                elem = soup.find('span', {'id': id_})
                if elem:
                    raw = elem.get_text()
                    text = clean_text(raw)
                    if text:
                        texts.append(text)
            return ' '.join(texts) if texts else ''

        data = {
            'aduana': get_combined_text(['span_CODI_ADUAN', 'span_vVADUD20']),
            'regimen': get_combined_text(['span_CODI_REGI', 'span_vVIMREGDSC']),
            'fecha_de_registro': get_combined_text_by_ids_with_space(['span_FECH_INGSI', 'span_HORA_INGSI']),
            'numero_del_dua': get_combined_text_numero_del_dua(
                ['span_CODI_ADUAN', 'span_ANO_PRESE', 'span_NUME_CORRE']),
            'tipo_semaforo': get_combined_text_by_ids_with_space(['span_vVTAFORDSC']),
            'tipo_carga': get_combined_text_by_ids_with_space(['span_vVTPOCARGA']),
            'solic_inmediata_tipo_revision': get_combined_text_by_ids_with_space(['span_vVAFORO']),
            'pago_impuestos': get_combined_text_by_ids_with_space(['span_vDEBEIMP']),
            'aplica_duca_f': get_combined_text_by_ids_with_space(['span_vRESPFAUCA']),
            'confirmacion_automatica': get_combined_text_by_ids_with_space(['span_vDSCCONFAUT']),
            'nro_de_envio': get_combined_text_by_ids_with_space(['span_NUME_ORDEN']),
            'modalidad': get_combined_text(['span_TIPO_OPERA', 'span_vIMSUBREGDSC']),
            'tipo_de_dua': get_combined_text_by_ids_with_space(['span_vVDSCDOCADU']),
            'forma_de_despacho': get_combined_text(['span_DESP_URGE', 'span_vVDSCDESP']),
            'estado': get_combined_text_by_ids_with_space(['span_ESTADO', 'span_vDUASTSDSC']),
            'momento_de_asociacion_inventario': get_combined_text_by_ids_with_space(['span_vVASOCINVENTARIO']),
            'dua_es_correlac_consolidado': get_combined_text(['span_vVCORR', 'span_vVDUACORRE', 'span_vDUA_CORRE']),
            'tiene_precinto_electronico': get_combined_text_by_ids_with_space(['span_vVPRECELECT']),
            'supervision_de_descarga': get_combined_text_by_ids_with_space(
                ['span_vVSUP_DESCARGA', 'FECHADESCARGA', 'span_FECHA_DESCARGA', 'FUNCIODESCARGA',
                 'span_vFUNDESC', 'span_vVFUNNOMB']),
            'afecta_valor_referencia': get_combined_text_by_ids_with_space(['span_vVALORREFERE']),
            'aplica_moratoria_alivio_fiscal': get_combined_text_by_ids_with_space(['span_vAPLIMORALFIS']),
            'datos_del_importad_exportad_y_proveedor_del_dua': get_combined_text_by_ids_with_space(['']),
            'declarante': get_combined_text(['span_TCODI_AGENT', 'span_CODI_AGENT']) + ' ' +
                          get_combined_text_by_ids_with_space(['span_vVNOMDECL']),
            'agente': get_combined_text(['span_TI_AGENTE', 'span_CI_AGENTE']) + ' ' +
                      get_combined_text_by_ids_with_space(['span_vVNOMAGENTE']),
            'importe_total_facturas': get_combined_text_by_ids_with_space(['span_TOT_FACT', 'span_vVMONDSC']),
            'tipo_de_cambio_de_compra': get_combined_text_by_ids_with_space(['span_TIPCAMCOM']) +
                                        ' Tipo de Cambio de Venta: ' +
                                        get_combined_text_by_ids_with_space(['span_TIPCAMVEN']),
            'medio_de_transporte': get_combined_text_by_ids_with_space(['span_vVVIADSC']),
            'empresa': get_combined_text(['span_vVTDOCTRA', 'span_vVCDOCTRA']) + ' ' +
                       get_combined_text_by_ids_with_space(['span_vVDNOM']),
            'aduana_de_ingreso': get_combined_text_by_ids_with_space(['span_vVADUIS', 'span_vVADUDSC2']),
            'lugar_de_localizacion': get_combined_text_by_ids_with_space(['span_CODI_ALMA', 'span_vVDRSOCIAL']),
            'aduana_destino': get_combined_text_by_ids_with_space(['span_vVADUDEST', 'span_vVADUDSC3']),
            'lugar_de_destino': get_combined_text(['span_vVCALMDEST', 'span_vVRGRSOC']),
            'total_bultos': get_combined_text_by_ids_with_space(['span_TCANT_BULT']),
            'total_peso_bruto': get_combined_text_by_ids_with_space(['span_TPESO_BRUT']),
            'total_peso_neto': get_combined_text_by_ids_with_space(['span_TPESO_NETO']),
            'total_valor_aduanas': get_combined_text_by_ids_with_space(['span_TVAD_INCR']),
            'garantia': get_combined_text_by_ids_with_space(['span_NUM_GARAN']) +
                        ' por ' +
                        get_combined_text_by_ids_with_space(['span_TOT_GARAN']),
            'nombre_vapor_o_medio_transporte_de_las_mercancias': get_combined_text_by_ids_with_space(
                ['span_NOM_VAPOR']),
            'lineas_de_dua': get_combined_text_by_ids_with_space(['span_vVLINEAS']),
        }
        return pd.DataFrame([data])


    def log_failed_dua(self, dua_number):
        failed_duas_path = self.config['failed_duas']
        with open(failed_duas_path, 'a') as f:
            f.write(f"{dua_number}\n")

    def log_dua_no_rows(self, dua_number):
        no_rows_duas_path = self.config.get('no_rows_duas', 'data/output/DUAs_sin_filas_agosto24.txt')
        with open(no_rows_duas_path, 'a') as f:
            f.write(f"{dua_number}\n")

    def close(self):
        self.driver.quit()

    def is_captcha_present(self):
        try:
            captcha_image_element = self.driver.find_element(By.XPATH, "//div[@id='captchaImage']/img")
            return True
        except NoSuchElementException:
            return False

    def set_current_dua(self, dua_number, row):
        self.current_dua_number = dua_number
        self.current_row = row

    def wait_for_page_to_load(driver, timeout=10):
        """Función de ejemplo para esperar que desaparezca un 'velo' (modal) si fuera necesario."""
        try:
            WebDriverWait(driver, timeout).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, "div[style*='block']"))
            )
        except Exception as e:
            print(f"Error al esperar la desaparición del 'velo': {e}")
def load_processed_duas_from_csv(output_csv_path):
    """
    Carga en PROCESSED_DUAS todos los 'numero_del_dua' ya presentes en el CSV de salida.
    Útil para reanudar ejecuciones sin volver a guardar duplicados.
    """
    if os.path.exists(output_csv_path):
        try:
            df = pd.read_csv(output_csv_path, dtype=str)
            if 'numero_del_dua' in df.columns:
                with PROCESSED_DUAS_LOCK:
                    for dua in df['numero_del_dua'].dropna():
                        PROCESSED_DUAS.add(dua.strip())
            logging.info(f"Se cargaron {len(PROCESSED_DUAS)} DUAs ya procesados desde {output_csv_path}.")
        except Exception as e:
            logging.error(f"No se pudo cargar DUAs previos desde {output_csv_path}: {e}")
