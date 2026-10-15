"""Identidad de DUAs compartida por entrada, validación y persistencia."""
import re


def normalize_dua(value) -> str:
    text = str(value).strip()
    match = re.fullmatch(r'(\d{1,3})\s*-\s*(\d{4})\s*-\s*(\d{1,6})', text)
    if not match:
        raise ValueError(f'DUA inválido: {text!r}; se espera Aduana-Año-Número')
    aduana, year, number = match.groups()
    if not (int(aduana) > 0 and 1900 <= int(year) <= 2100 and int(number) > 0):
        raise ValueError(f'DUA fuera de rango: {text!r}')
    return f'{int(aduana):03d}-{year}-{int(number):06d}'


def dua_fields(dua: str) -> dict:
    aduana, year, number = normalize_dua(dua).split('-')
    return {'NroDUA': dua, 'Aduana': aduana, 'Año': year, 'Número': number}


def validate_result(data, expected: str) -> dict:
    if data is None or len(data) != 1 or 'numero_del_dua' not in data:
        raise ValueError(f'Resultado vacío o ambiguo para {expected}')
    record = data.iloc[0].to_dict()
    actual = normalize_dua(record['numero_del_dua'])
    if actual != normalize_dua(expected):
        raise ValueError(f'Identidad incorrecta: se pidió {expected}, se recibió {actual}')
    record['numero_del_dua'] = actual
    return {key: str(value) for key, value in record.items()}
