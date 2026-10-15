"""Mensajes para personas; los diagnósticos completos se conservan aparte."""


def pending_reason(kind, error=''):
    if kind == 'extra_step':
        return 'El portal requiere un paso adicional.'
    if kind == 'PortalResponseError':
        return 'El portal no devolvió el detalle solicitado.'
    if kind == 'FormChangedError':
        return 'El formulario cambió; se volverá a completar.'
    if kind == 'TimeoutError' or 'Timeout' in error:
        return 'El portal tardó demasiado en responder.'
    if kind == 'input':
        return 'Revisa el número de DUA en el archivo Excel.'
    if kind == 'interrupted':
        return 'La consulta se interrumpió y está guardada para retomarla.'
    if 'ERR_' in error:
        return 'No se pudo conectar con el portal.'
    return 'No se pudo completar la consulta.'
