"""Fixtures locales; nunca contactan una cámara ni abren ventanas."""
from pathlib import Path
import sys
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
import requests

from camera_client import ClienteCamara


def jpeg_ejemplo(tono=80):
    imagen = np.full((80, 120, 3), tono, dtype=np.uint8)
    cv2.rectangle(imagen, (10, 10), (40, 40), (20, 170, 230), -1)
    correcto, buffer = cv2.imencode('.jpg', imagen)
    assert correcto
    return buffer.tobytes()


def respuesta(contenido, tipo='image/jpeg', codigo=200, identificador='19'):
    objeto = requests.Response()
    objeto.status_code = codigo
    objeto._content = contenido
    objeto._content_consumed = True
    objeto.headers['Content-Type'] = tipo
    if identificador is not None:
        objeto.headers['X-Capture-Id'] = identificador
    objeto.close = Mock(wraps=objeto.close)
    return objeto


def captura_ejemplo(tono=80, identificador='19'):
    sesion = Mock()
    sesion.get.return_value = respuesta(jpeg_ejemplo(tono), identificador=identificador)
    with ClienteCamara('http://camara.invalid', sesion=sesion, reintentos=0) as cliente:
        return cliente.capturar({'camera_ready': True, 'sensor': 'OV3660', 'width': 120,
                                 'height': 80, 'quality': 12})
