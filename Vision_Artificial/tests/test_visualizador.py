from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

from soporte import captura_ejemplo
import cv2
import numpy as np
from camera_client import EstadoAdquisicion, Adquisidor
from main import Visualizador, cargar_configuracion
from roi_manager import GestorROI


class PruebasInterfazSinVentana(unittest.TestCase):
    def setUp(self):
        self.captura = captura_ejemplo()
        self.estado = EstadoAdquisicion(self.captura, True, 'Conectado', 1, time.monotonic(), 1.0)
        self.adquisidor = Mock()
        self.adquisidor.pausado = threading.Event()
        self.adquisidor.obtener_estado.side_effect = lambda: self.estado
        self.almacenamiento = Mock()
        self.interfaz = Visualizador(self.adquisidor, GestorROI(), self.almacenamiento, 'roi.json', 1)
        self.interfaz.dibujar()

    def test_edicion_pausa_y_no_modifica_original(self):
        original = self.captura.imagen.copy()
        self.interfaz.tecla(ord('1'))
        self.assertTrue(self.adquisidor.pausado.is_set())
        for punto in ((5, 5), (40, 5), (40, 50), (5, 50)):
            self.interfaz.raton(cv2.EVENT_LBUTTONDOWN, *punto, 0, None)
        self.interfaz.tecla(13)
        self.assertIn(1, self.interfaz.regiones.regiones)
        self.interfaz.dibujar()
        np.testing.assert_array_equal(self.captura.imagen, original)
        self.assertTrue(self.interfaz.tecla(32))
        self.assertFalse(self.adquisidor.pausado.is_set())
        self.assertFalse(self.interfaz.tecla(27))

    def test_imagen_pausada_no_cambia_al_llegar_otra(self):
        self.interfaz.tecla(32)
        self.estado = replace(self.estado, captura=captura_ejemplo(100), secuencia=2)
        self.interfaz.dibujar()
        self.assertIs(self.interfaz.captura, self.captura)

    def test_no_guarda_durante_desconexion_ni_confirmacion_antigua(self):
        for estado in (replace(self.estado, conectado=False),
                       replace(self.estado, confirmada_monotonic=time.monotonic() - 30)):
            self.estado = estado
            self.interfaz.tecla(ord('s'))
        self.almacenamiento.guardar.assert_not_called()

    def test_guarda_objeto_original_no_lienzo_anotado(self):
        self.almacenamiento.guardar.return_value = Path('fotografia.jpg')
        self.interfaz.tecla(ord('s'))
        self.almacenamiento.guardar.assert_called_once_with(self.captura)

    def test_configuracion_rutas_relativas_y_url_cli(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'config.json'
            ruta.write_text(json.dumps({'url_base':'http://camara.invalid', 'ruta_roi':'calibracion/roi.json'}))
            datos = cargar_configuracion(ruta, 'otra-camara.invalid')
            self.assertEqual(datos['url_base'], 'http://otra-camara.invalid')
            self.assertEqual(datos['ruta_roi'], Path(carpeta) / 'calibracion/roi.json')
            ruta.write_text('{"timeout_lectura_s": -1}')
            with self.assertRaises(ValueError):
                cargar_configuracion(ruta, 'camara.invalid')

    def test_pausa_consulta_estado_sin_pedir_capturas(self):
        cliente = Mock()
        cliente.__enter__ = Mock(return_value=cliente)
        cliente.__exit__ = Mock()
        config = dict(timeout_conexion_s=.1, timeout_lectura_s=.1, reintentos=0,
                      pausa_reintento_s=.05, intervalo_captura_s=.05)
        adquisidor = Adquisidor('camara.invalid', config, fabrica_cliente=lambda *a, **k: cliente)
        adquisidor.pausado.set()
        def consultar():
            adquisidor.detener.set()
            return {'camera_ready': True}
        cliente.consultar_estado.side_effect = consultar
        adquisidor.start(); adquisidor.join(timeout=2)
        self.assertFalse(adquisidor.is_alive())
        cliente.capturar.assert_not_called()
        self.assertTrue(adquisidor.obtener_estado().conectado)
