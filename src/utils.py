"""utils.py — Configuración, sesión y utilidades compartidas."""
import os
import json
import logging
import re
import hashlib
from logging.handlers import RotatingFileHandler
from core.job_store import atomic_output

import sys

if getattr(sys, 'frozen', False):
    # Corriendo como .exe: base = carpeta donde está el ejecutable
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    # Corriendo como script: base = raíz del proyecto (v2/)
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CONFIG_DIR    = os.path.join(_BASE_DIR, 'config')
_MACHINE_PATH  = os.path.join(_CONFIG_DIR, 'machine.json')
_SESSION_PATH  = os.path.join(_CONFIG_DIR, 'session.json')

_DEFAULT_MACHINE = {
    "base_path":        "",
    "output_base_path": "",
    "max_retries":      3,
    "timeout":          30,
    "cant_hilos":       1,
    "reuse_context":    True,
    "lightweight_details": True,
    "headless":         True,
    "dark_mode":        True,
}

_DEFAULT_SESSION = {
    "sheet_name":      "",
    "input_file_path": "",
}


def _ensure_config() -> None:
    """Crea la carpeta config/ y los JSON por defecto si no existen."""
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    if not os.path.exists(_MACHINE_PATH):
        with open(_MACHINE_PATH, 'w', encoding='utf-8') as f:
            json.dump(_DEFAULT_MACHINE, f, indent=4, ensure_ascii=False)
    if not os.path.exists(_SESSION_PATH):
        with open(_SESSION_PATH, 'w', encoding='utf-8') as f:
            json.dump(_DEFAULT_SESSION, f, indent=4, ensure_ascii=False)


# ── Config de máquina (rutas y parámetros estáticos) ─────────────────────────

def load_machine_config() -> dict:
    _ensure_config()
    with open(_MACHINE_PATH, 'r', encoding='utf-8') as f:
        return {**_DEFAULT_MACHINE, **json.load(f)}


def save_machine_config(config: dict) -> None:
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    with atomic_output(_MACHINE_PATH) as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


# ── Sesión (selección de archivo y hoja; la cola está en SQLite) ──────────────

def load_session() -> dict:
    _ensure_config()
    with open(_SESSION_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_session(session: dict) -> None:
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    with atomic_output(_SESSION_PATH) as f:
        json.dump(session, f, indent=4, ensure_ascii=False)


# ── Rutas derivadas (calculadas en memoria, nunca persistidas) ───────────────

def normalize_key(name: str) -> str:
    """Convierte un nombre de hoja a clave válida para JSON (sin caracteres especiales, minúsculas)."""
    return re.sub(r'\W+', '_', name.strip().lower())


def dataset_key(source: str, sheet_name: str) -> str:
    identity = os.path.normcase(os.path.abspath(source)) + '\n' + sheet_name
    return hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]


def get_queue_path(source: str, sheet_name: str) -> str:
    return os.path.join(_BASE_DIR, 'data', 'queues', dataset_key(source, sheet_name) + '.sqlite3')


def get_catalog_folder():
    return os.path.join(_BASE_DIR, 'data', 'queues')


def compute_output_paths(output_base: str, sheet_name: str, source: str = '', table_id: str = '') -> dict:
    """
    Calcula y crea (si no existe) la carpeta de salida para una hoja.
    Separa archivos con hojas homónimas mediante un identificador del lote.
    """
    safe_sheet = normalize_key(sheet_name) or 'hoja'
    folder = os.path.join(output_base, safe_sheet)
    if table_id:
        folder = os.path.join(folder, table_id)
    elif source:
        folder = os.path.join(folder, dataset_key(source, sheet_name))
    os.makedirs(folder, exist_ok=True)
    return {
        'output_csv':    os.path.join(folder, f'Detalles_DUAs_{safe_sheet}.csv'),
        'failed_duas':   os.path.join(folder, f'Detalles_DUAs_pendientes_{safe_sheet}.txt'),
        'processed_log': os.path.join(folder, f'Detalles_DUAs_procesados_log_{safe_sheet}.txt'),
        'pending_json':  os.path.join(folder, 'pendientes.json'),
        'diagnostics':   os.path.join(folder, 'diagnosticos'),
        'legacy_csv':    os.path.join(output_base, sheet_name,
                                     f'MM20YY_Detalles_DUAs__procesados_{sheet_name}.csv'),
    }


# ── Logging ──────────────────────────────────────────────────────────────────

def setup_logging(log_file: str = None) -> None:
    if log_file is None:
        log_file = os.path.join(_BASE_DIR, 'logs', 'debug.log')
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    console = logging.StreamHandler()
    console.addFilter(lambda record: not getattr(record, 'technical_only', False))
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3, encoding='utf-8'),
            console,
        ],
    )
