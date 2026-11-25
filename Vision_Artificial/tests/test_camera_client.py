import json
import threading
import unittest
from unittest.mock import Mock

from soporte import jpeg_ejemplo, respuesta, captura_ejemplo
import requests
from camera_client import ClienteCamara, ErrorCamara, Adquisidor, normalizar_url


class PruebasCliente(unittest.TestCase):
    def test_jpeg_decodifica_preserva_bytes_y_cierra_respuesta(self):
        original = jpeg_ejemplo()
        recibido = respuesta(original)
        sesion = Mock()
        sesion.get.return_value = recibido
        with ClienteCamara('camara.invalid', sesion=sesion, reintentos=0) as cliente:
            captura = cliente.capturar()
        self.assertEqual(captura.jpeg, original)
        self.assertEqual(captura.imagen.shape, (80, 120, 3))
        self.assertEqual(captura.identificador, '19')
        self.assertFalse(captura.imagen.flags.writeable)
        self.assertGreaterEqual(captura.recepcion_s, 0)
        self.assertGreaterEqual(captura.decodificacion_s, 0)
        recibido.close.assert_called_once()
        sesion.close.assert_called_once()
        self.assertEqual(sesion.get.call_args.kwargs['timeout'], (3.0, 15.0))
        self.assertFalse(sesion.get.call_args.kwargs['allow_redirects'])

    def test_jpeg_invalido_aunque_tenga_marcadores(self):
        for contenido in (b'no es JPEG', b'\xff\xd8basura\xff\xd9', jpeg_ejemplo()[:-2]):
            with self.subTest(contenido=contenido[:10]):
                sesion = Mock()
                sesion.get.return_value = respuesta(contenido)
                with ClienteCamara('camara.invalid', sesion=sesion, reintentos=0) as cliente:
                    with self.assertRaises(ErrorCamara):
                        cliente.capturar()

    def test_http_503_y_tipo_incorrecto(self):
        for recibido in (respuesta(b'error', codigo=503), respuesta(jpeg_ejemplo(), 'text/html')):
            sesion = Mock()
            sesion.get.return_value = recibido
            with ClienteCamara('camara.invalid', sesion=sesion, reintentos=0) as cliente:
                with self.assertRaises(ErrorCamara):
                    cliente.capturar()
            recibido.close.assert_called_once()

    def test_timeout_se_reintenta_y_es_cancelable(self):
        sesion = Mock()
        sesion.get.side_effect = [requests.Timeout(), respuesta(jpeg_ejemplo())]
        detener = Mock()
        detener.is_set.return_value = False
        detener.wait.return_value = False
        with ClienteCamara('camara.invalid', sesion=sesion, reintentos=1, detener=detener) as cliente:
            self.assertEqual(cliente.capturar().identificador, '19')
        self.assertEqual(sesion.get.call_count, 2)
        detener.wait.assert_called_once_with(1.0)
        sesion = Mock()
        sesion.get.side_effect = requests.Timeout()
        with ClienteCamara('camara.invalid', sesion=sesion, reintentos=0) as cliente:
            with self.assertRaisesRegex(ErrorCamara, 'Timeout'):
                cliente.capturar()

    def test_status_y_captura_sin_identificador(self):
        datos = {'camera_ready': True, 'sensor': 'OV3660', 'width': 120, 'height': 80, 'quality': 12}
        sesion = Mock()
        sesion.get.side_effect = [respuesta(json.dumps(datos).encode(), 'application/json; charset=utf-8'),
                                 respuesta(jpeg_ejemplo(), identificador=None)]
        with ClienteCamara('camara.invalid', sesion=sesion, reintentos=0) as cliente:
            captura = cliente.capturar(cliente.consultar_estado())
        self.assertIsNone(captura.identificador)
        self.assertEqual(captura.calidad_reportada, 12)
        self.assertEqual(captura.estado_reportado, datos)

    def test_status_invalido(self):
        for contenido in (b'no json', b'[]', b'{"otro":1}'):
            sesion = Mock()
            sesion.get.return_value = respuesta(contenido, 'application/json')
            with ClienteCamara('camara.invalid', sesion=sesion, reintentos=0) as cliente:
                with self.assertRaises(ErrorCamara):
                    cliente.consultar_estado()

    def test_respuesta_grande_se_rechaza_y_cierra(self):
        recibido = respuesta(b'x' * (5 * 1024 * 1024 + 1))
        sesion = Mock()
        sesion.get.return_value = recibido
        with ClienteCamara('camara.invalid', sesion=sesion, reintentos=0) as cliente:
            with self.assertRaisesRegex(ErrorCamara, 'grande'):
                cliente.capturar()
        recibido.close.assert_called_once()

    def test_url_base_sin_credenciales_ni_rutas(self):
        self.assertEqual(normalizar_url('camara.invalid:80/'), 'http://camara.invalid:80')
        for direccion in ('', 'http://usuario:clave@camara.invalid', 'http://camara.invalid/capture',
                          'http://camara.invalid?q=1', 'ftp://camara.invalid', None):
            with self.subTest(direccion=direccion):
                with self.assertRaises(ValueError):
                    normalizar_url(direccion)


class PruebasAdquisidor(unittest.TestCase):
    def configuracion(self):
        return dict(timeout_conexion_s=0.1, timeout_lectura_s=0.1, reintentos=0,
                    pausa_reintento_s=0.05, intervalo_captura_s=0.05)

    def test_buzon_solo_conserva_ultima_y_cierra_sesion(self):
        cliente = Mock()
        cliente.__enter__ = Mock(return_value=cliente)
        cliente.__exit__ = Mock()
        cliente.consultar_estado.return_value = {'camera_ready': True}
        adquisidor = Adquisidor('camara.invalid', self.configuracion(), fabrica_cliente=lambda *a, **k: cliente)
        capturas = [captura_ejemplo(50), captura_ejemplo(100)]
        def capturar(_):
            captura = capturas[cliente.capturar.call_count - 1]
            if cliente.capturar.call_count == 2:
                adquisidor.detener.set()
            return captura
        cliente.capturar.side_effect = capturar
        adquisidor.start()
        adquisidor.join(timeout=2)
        self.assertFalse(adquisidor.is_alive())
        self.assertIs(adquisidor.obtener_estado().captura, capturas[1])
        self.assertEqual(adquisidor.obtener_estado().secuencia, 2)
        cliente.__exit__.assert_called_once()

    def test_desconexion_conserva_imagen_y_marca_antigua(self):
        cliente = Mock()
        cliente.__enter__ = Mock(return_value=cliente)
        cliente.__exit__ = Mock()
        adquisidor = Adquisidor('camara.invalid', self.configuracion(), fabrica_cliente=lambda *a, **k: cliente)
        def estado():
            if cliente.consultar_estado.call_count == 2:
                adquisidor.detener.set()
                raise ErrorCamara('HTTP 503')
            return {'camera_ready': True}
        cliente.consultar_estado.side_effect = estado
        cliente.capturar.return_value = captura_ejemplo()
        adquisidor.start(); adquisidor.join(timeout=2)
        self.assertFalse(adquisidor.is_alive())
        self.assertIsNotNone(adquisidor.obtener_estado().captura)
        self.assertFalse(adquisidor.obtener_estado().conectado)
        self.assertEqual(adquisidor.obtener_estado().secuencia, 1)

    def test_status_correcto_no_borra_error_de_captura_http_503(self):
        from camera_client import captura_vigente
        cliente = Mock()
        cliente.__enter__ = Mock(return_value=cliente)
        cliente.__exit__ = Mock()
        adquisidor = Adquisidor('camara.invalid', self.configuracion(), fabrica_cliente=lambda *a, **k: cliente)
        original = captura_ejemplo()
        def estado():
            if cliente.consultar_estado.call_count == 3:
                adquisidor.detener.set()
            return {'camera_ready': True}
        def capturar(_):
            if cliente.capturar.call_count == 1:
                return original
            adquisidor.pausado.set()
            raise ErrorCamara('HTTP 503 en /capture', 'http')
        cliente.consultar_estado.side_effect = estado
        cliente.capturar.side_effect = capturar
        adquisidor.start(); adquisidor.join(timeout=2)
        self.assertFalse(adquisidor.is_alive())
        resultado = adquisidor.obtener_estado()
        self.assertTrue(resultado.conectado)  # HTTP responde; el JPEG sigue inválido.
        self.assertTrue(resultado.error_captura)
        self.assertIs(resultado.captura, original)
        self.assertFalse(captura_vigente(resultado, original, 30))
