from dataclasses import replace
import threading
import time
import unittest

from test_conteo_yolo import captura_svga, regiones_svga
from camera_client import EstadoAdquisicion
from contador_vehiculos import Conteo
from detector_vehiculos import Deteccion, PARAMETROS_INICIALES
from inference_worker import TrabajadorInferencia, motivo_resultado


def esperar(condicion, limite=3):
    fin = time.monotonic() + limite
    while not condicion():
        if time.monotonic() >= fin:
            raise AssertionError('No llegó el estado esperado del trabajador')
        threading.Event().wait(.005)


class PruebasTrabajador(unittest.TestCase):
    def crear(self, detectar, limite=30):
        class Simulado:
            def detectar(self, imagen):
                return detectar(imagen)
        trabajador = TrabajadorInferencia(PARAMETROS_INICIALES, limite, fabrica_detector=lambda _: Simulado())
        trabajador.start()
        self.addCleanup(lambda: (trabajador.cerrar(), trabajador.join(timeout=3)))
        return trabajador

    def test_asociacion_buzon_omitidos_y_una_sola_inferencia(self):
        entro = threading.Event()
        liberar = threading.Event()
        procesadas = []
        def detectar(imagen):
            valor = int(imagen[0, 0, 0]); procesadas.append(valor)
            if valor == 1:
                entro.set(); liberar.wait(timeout=2)
            return (Deteccion((30, 30, 100, 100), 2, 'car', .9),), .01
        trabajador = self.crear(detectar)
        regiones = regiones_svga()
        primera, segunda, tercera = (captura_svga(n) for n in (1, 2, 3))
        self.assertTrue(trabajador.enviar(primera, 1, regiones))
        self.assertTrue(entro.wait(2))
        self.assertFalse(trabajador.enviar(primera, 1, regiones))
        trabajador.enviar(segunda, 2, regiones)
        trabajador.enviar(tercera, 3, regiones)
        liberar.set()
        esperar(lambda: trabajador.obtener_estado().resultado is not None and trabajador.obtener_estado().resultado.secuencia == 3)
        resultado = trabajador.obtener_estado().resultado
        self.assertEqual(procesadas, [1, 3])
        self.assertIs(resultado.captura, tercera)
        self.assertEqual(resultado.captura.identificador, '3')
        self.assertEqual(resultado.instantaneo, Conteo(1, 0, 0))
        self.assertGreaterEqual(trabajador.obtener_estado().omitidos, 1)
        self.assertIsNone(resultado.a_dict(False, 'antiguo')['instantaneo'])

    def test_cambio_roi_durante_inferencia_descarta_contexto_anterior(self):
        entro = threading.Event(); liberar = threading.Event()
        def detectar(imagen):
            if imagen[0, 0, 0] == 1:
                entro.set(); liberar.wait(timeout=2)
            return (), .01
        trabajador = self.crear(detectar)
        regiones = regiones_svga()
        trabajador.enviar(captura_svga(1), 1, regiones)
        self.assertTrue(entro.wait(2))
        regiones.establecer(1, [(25, 25), (340, 25), (340, 570), (25, 570)], (800, 600))
        trabajador.enviar(captura_svga(2), 2, regiones)
        liberar.set()
        esperar(lambda: trabajador.obtener_estado().resultado is not None)
        resultado = trabajador.obtener_estado().resultado
        self.assertEqual(resultado.secuencia, 2)
        self.assertEqual(resultado.contexto[0], regiones.firma())
        self.assertEqual(resultado.muestras_validas, 1)

    def test_desconexion_reinicia_filtro_y_cero_sigue_siendo_valido(self):
        trabajador = self.crear(lambda _: ((), .01))
        regiones = regiones_svga()
        for secuencia in (1, 2, 3):
            trabajador.enviar(captura_svga(secuencia), secuencia, regiones)
            esperar(lambda: trabajador.obtener_estado().resultado is not None and
                    trabajador.obtener_estado().resultado.secuencia == secuencia)
        self.assertEqual(trabajador.obtener_estado().resultado.muestras_validas, 3)
        trabajador.suspender('Camara desconectada')
        captura = captura_svga(4)
        trabajador.enviar(captura, 4, regiones, epoca=1)
        esperar(lambda: trabajador.obtener_estado().resultado.secuencia == 4)
        estado_ia = trabajador.obtener_estado()
        self.assertEqual(estado_ia.resultado.muestras_validas, 1)
        estado = EstadoAdquisicion(captura, True, 'Conectado', 4, time.monotonic(), epoca=1)
        self.assertEqual(motivo_resultado(estado, captura, regiones, estado_ia, 30, 30), '')
        self.assertEqual(estado_ia.resultado.instantaneo.n_total, 0)
        desconectado = replace(estado, conectado=False)
        self.assertIn('desconectada', motivo_resultado(desconectado, captura, regiones, estado_ia, 30, 30))
        viejo = estado_ia.resultado.captura.recibida_monotonic + 40
        reciente = replace(estado, confirmada_monotonic=viejo)
        self.assertEqual(motivo_resultado(reciente, captura, regiones, estado_ia, 100, 30, ahora=viejo),
                         'Resultado neuronal antiguo')

    def test_imagen_antigua_error_y_roi_no_configuradas_no_son_cero(self):
        trabajador = self.crear(lambda _: ((), .01))
        regiones = regiones_svga()
        vieja = replace(captura_svga(), recibida_monotonic=time.monotonic() - 100)
        trabajador.enviar(vieja, 1, regiones)
        esperar(lambda: bool(trabajador.obtener_estado().error))
        self.assertIsNone(trabajador.obtener_estado().resultado)
        captura = captura_svga(2)
        estado = EstadoAdquisicion(captura, True, '', 2, time.monotonic())
        self.assertEqual(motivo_resultado(estado, captura, GestorVacio(), trabajador.obtener_estado(), 30, 30), 'ROI no configuradas')

    def test_inferencia_demasiado_lenta_se_descarta(self):
        def detectar(_):
            threading.Event().wait(.15)
            return (), .15
        trabajador = self.crear(detectar, limite=.1)
        trabajador.enviar(captura_svga(), 1, regiones_svga())
        esperar(lambda: trabajador.obtener_estado().motivo == 'Resultado neuronal antiguo' or bool(trabajador.obtener_estado().error))
        self.assertIsNone(trabajador.obtener_estado().resultado)

    def test_mediana_caducada_no_se_publica_como_vigente(self):
        from unittest.mock import patch
        def detectar(imagen):
            deteccion = Deteccion((30, 30, 100, 100), 2, 'car', .9)
            return (deteccion,) * int(imagen[0, 0, 0]), .01
        trabajador = self.crear(detectar)
        regiones = regiones_svga()
        ahora = time.monotonic()
        for secuencia, edad in ((1, 20), (2, 10), (3, 0)):
            captura = replace(captura_svga(secuencia), recibida_monotonic=ahora - edad)
            trabajador.enviar(captura, secuencia, regiones)
            esperar(lambda: trabajador.obtener_estado().resultado is not None and
                    trabajador.obtener_estado().resultado.secuencia == secuencia)
        self.assertEqual(trabajador.obtener_estado().resultado.filtrado.n1, 2)
        # Caduca la primera muestra; la última foto sigue dentro de los 30 s.
        with patch('inference_worker.time.monotonic', return_value=ahora + 11):
            resultado = trabajador.obtener_estado().resultado
        self.assertEqual(resultado.muestras_validas, 0)
        self.assertEqual(resultado.filtrado, resultado.instantaneo)
        self.assertEqual(resultado.instantaneo.n1, 3)
        self.assertIs(resultado.captura, captura)

    def test_error_neuronal_y_recuperacion_sin_ceros_falsos(self):
        intentos = []
        def detectar(_):
            intentos.append(1)
            if len(intentos) == 1:
                raise RuntimeError('Fallo simulado del modelo')
            return (), .01
        trabajador = self.crear(detectar)
        regiones = regiones_svga()
        trabajador.enviar(captura_svga(1), 1, regiones)
        esperar(lambda: bool(trabajador.obtener_estado().error))
        self.assertIsNone(trabajador.obtener_estado().resultado)
        trabajador.enviar(captura_svga(2), 2, regiones)
        esperar(lambda: trabajador.obtener_estado().resultado is not None)
        self.assertEqual(trabajador.obtener_estado().error, '')
        self.assertEqual(trabajador.obtener_estado().resultado.muestras_validas, 1)

    def test_gui_muestra_el_framebuffer_analizado_no_la_foto_mas_nueva(self):
        from main import Visualizador
        from unittest.mock import Mock
        trabajador = self.crear(lambda _: ((Deteccion((30, 30, 100, 100), 2, 'car', .8),), .01))
        regiones = regiones_svga()
        captura = captura_svga(1)
        trabajador.enviar(captura, 1, regiones)
        esperar(lambda: trabajador.obtener_estado().resultado is not None)
        mas_nueva = captura_svga(2)
        estado = EstadoAdquisicion(mas_nueva, True, '', 2, time.monotonic())
        adquisidor = Mock(); adquisidor.obtener_estado.return_value = estado
        interfaz = Visualizador(adquisidor, regiones, Mock(), 'roi.json', 1, trabajador)
        # Mantener un resultado fijo durante la renderización de la nueva foto.
        with __import__('unittest.mock').mock.patch.object(trabajador, 'enviar', return_value=False):
            interfaz.dibujar()
            self.assertIs(interfaz.captura, captura)
            self.assertEqual(interfaz.secuencia, 1)
            self.assertEqual(interfaz.informacion_diagnostico['id_mostrado'], captura.identificador)


class GestorVacio:
    def estado_calibracion(self, _):
        return 'ROI no configuradas'
