"""Catálogo estático mínimo; una carga y búsquedas O(1), sin Excel."""
import json
import re
import sys
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit


def image_key(url: str) -> str:
    match = re.search(r'/Captcha/images/(\d+)\.jpg$', urlsplit(url).path, re.I)
    if not match:
        raise ValueError(f'Imagen CAPTCHA no reconocida: {url}')
    return str(int(match.group(1)))


@lru_cache(maxsize=1)
def load_captcha_lookup():
    root = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
    with (root / 'config' / 'captcha_lookup.json').open(encoding='utf-8') as stream:
        lookup = json.load(stream)
    if not lookup or any(not key.isdigit() or not isinstance(word, str) or not word.strip()
                         for key, word in lookup.items()):
        raise ValueError('Catálogo CAPTCHA vacío o inválido')
    return MappingProxyType(lookup)


def resolve_captcha(url: str, lookup=None) -> str:
    key = image_key(url)
    catalog = load_captcha_lookup() if lookup is None else lookup
    try:
        return catalog[key]
    except KeyError:
        raise ValueError(f'CAPTCHA {key} no está en el catálogo') from None
