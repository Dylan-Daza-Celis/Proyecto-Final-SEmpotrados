from dataclasses import replace
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from soporte import captura_ejemplo
import cv2
import numpy as np
from camera_client import captura_vigente, EstadoAdquisicion
from contador_vehiculos import Conteo, FiltroMediana, contar_vehiculos
from detector_vehiculos import (Deteccion, DetectorVehiculos, ErrorDeteccion, CLASES_COCO,
                                PARAMETROS_INICIALES, filtrar_filas, validar_parametros)
from roi_manager import GestorROI
from evaluar import calcular_metricas, registrar_escena, leer_escenas, evaluar_escenas


def captura_svga(valor=1):
    captura = captura_ejemplo()
    imagen = np.full((600, 800, 3), valor, np.uint8)
    jpeg = cv2.imencode('.jpg', imagen)[1].tobytes()
    imagen.setflags(write=False)
    return replace(captura, imagen=imagen, jpeg=jpeg, identificador=str(valor), recibida_monotonic=time.monotonic())


def regiones_svga():
    regiones = GestorROI()
    regiones.establecer(1, [(20, 20), (350, 20), (350, 580), (20, 580)], (800, 600))
    regiones.establecer(2, [(450, 20), (780, 20), (780, 580), (450, 580)], (800, 600))
    return regiones


class PruebasDetector(unittest.TestCase):
    def test_centro_y_filtrado(self):
        filas = np.array([[20, 30, 60, 90, .8, 2], [70, 80, 90, 100, .1, 2],
                          [80, 90, 120, 130, .9, 0], [100, 100, 120, 130, .7, 7]])
        detecciones = filtrar_filas(filas, (800, 600), PARAMETROS_INICIALES, CLASES_COCO)
        self.assertEqual(len(detecciones), 2)
        self.assertEqual(detecciones[0].centro, (40, 60))
        self.assertEqual(detecciones[1].nombre, 'truck')

    def test_detecciones_invalidas_no_se_convierten_en_escena_vacia(self):
        for fila in ([0, 0, 0, 30, .9, 2], [0, 0, 900, 30, .9, 2],
                     [0, 0, 10, 30, float('nan'), 2], [0, 0, 10, 30, .9, 2.5],
                     [float('nan'), 0, 10, 30, .9, 2]):
            with self.subTest(fila=fila):
                with self.assertRaises(ErrorDeteccion):
                    filtrar_filas(np.array([fila]), (800, 600), PARAMETROS_INICIALES, CLASES_COCO)

    def test_modelo_carga_una_vez_y_coordenadas_originales(self):
        modelo = Mock(names=CLASES_COCO)
        modelo.names = CLASES_COCO
        cajas = Mock()
        cajas.data.cpu.return_value.numpy.return_value = np.array([[20, 20, 100, 100, .8, 2]])
        modelo.predict.return_value = [SimpleNamespace(orig_shape=(600, 800), boxes=cajas)]
        fabrica = Mock(return_value=modelo)
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'yolo11x.pt'
            ruta.write_bytes(b'pesos simulados')
            detector = DetectorVehiculos(PARAMETROS_INICIALES | {'pesos': str(ruta)}, fabrica)
            for _ in range(2):
                detecciones, segundos = detector.detectar(np.zeros((600, 800, 3), np.uint8))
                self.assertEqual(detecciones[0].centro, (60, 60))
                self.assertGreaterEqual(segundos, 0)
            fabrica.assert_called_once()
            self.assertEqual(modelo.predict.call_args.kwargs['imgsz'], 960)
            self.assertEqual(modelo.predict.call_args.kwargs['device'], 'cpu')
            modelo.predict.return_value[0].orig_shape = (960, 960)
            with self.assertRaises(ErrorDeteccion):
                detector.detectar(np.zeros((600, 800, 3), np.uint8))

    def test_pesos_ausentes_nombres_y_parametros_invalidos(self):
        with tempfile.TemporaryDirectory() as carpeta:
            fabrica = Mock()
            with self.assertRaises(ErrorDeteccion):
                DetectorVehiculos({'pesos': str(Path(carpeta) / 'ausente.pt')}, fabrica)
            fabrica.assert_not_called()
            ruta = Path(carpeta) / 'local.pt'; ruta.write_bytes(b'x')
            modelo = Mock(); modelo.names = {2: 'person'}
            with self.assertRaises(ErrorDeteccion):
                DetectorVehiculos({'pesos': str(ruta)}, lambda *_: modelo)
        for parametros in ({'confianza': -1}, {'imgsz': 961}, {'clases': [0]}, {'clases': [[2]]}):
            with self.assertRaises(ValueError):
                validar_parametros(parametros)


class PruebasConteo(unittest.TestCase):
    def test_conteo_ocupacion_sin_acumular(self):
        regiones = regiones_svga()
        detecciones = [Deteccion((40, 40, 100, 100), 2, 'car', .8),
                       Deteccion((500, 50, 550, 100), 5, 'bus', .6),
                       Deteccion((370, 40, 420, 90), 3, 'motorcycle', .7)]
        for _ in range(2):
            conteo = contar_vehiculos(detecciones, regiones, (800, 600))
            self.assertEqual((conteo.n1, conteo.n2, conteo.n_fuera, conteo.n_total, conteo.diferencia), (1, 1, 1, 3, 0))
        self.assertEqual(contar_vehiculos([], regiones, (800, 600)), Conteo(0, 0, 0))

    def test_roi_ausentes_ambiguas_y_deteccion_invalida(self):
        with self.assertRaises(ValueError):
            contar_vehiculos([], GestorROI(), (800, 600))
        regiones = regiones_svga()
        regiones.regiones[2] = regiones.regiones[1]
        with self.assertRaises(ValueError):
            contar_vehiculos([], regiones, (800, 600))
        with self.assertRaises(ErrorDeteccion):
            contar_vehiculos([Deteccion((30, 30, -1, 100), 2, 'car', .8)], regiones_svga(), (800, 600))

    def test_recalibrar_exige_ambas_roi_y_persiste_la_invalidacion(self):
        regiones = regiones_svga()
        regiones.observar_resolucion((320, 240))
        regiones.observar_resolucion((800, 600))
        self.assertIn('recalibracion', regiones.estado_calibracion((800, 600)))
        regiones.establecer(1, regiones.puntos_pixel(1, (800, 600)), (800, 600))
        self.assertIn('recalibracion', regiones.estado_calibracion((800, 600)))
        regiones.establecer(2, regiones.puntos_pixel(2, (800, 600)), (800, 600))
        self.assertEqual(regiones.estado_calibracion((800, 600)), '')
        regiones.invalidar_calibracion()
        self.assertIn('recalibracion', regiones.estado_calibracion((800, 600)))

    def test_status_no_rejuvenece_imagen(self):
        captura = replace(captura_svga(), recibida_monotonic=10)
        estado = EstadoAdquisicion(captura, True, 'Status correcto', 1, 100)
        self.assertFalse(captura_vigente(estado, captura, 5, ahora=100))

    def test_guardado_no_se_rehabilita_por_status_correcto(self):
        from main import Visualizador
        captura = replace(captura_ejemplo(), recibida_monotonic=time.monotonic() - 60)
        estado = EstadoAdquisicion(captura, True, 'Status correcto', 1, time.monotonic())
        adquisidor = Mock(); adquisidor.obtener_estado.return_value = estado
        almacenamiento = Mock()
        interfaz = Visualizador(adquisidor, GestorROI(), almacenamiento, 'roi.json', 1)
        interfaz.dibujar(); interfaz.tecla(ord('s'))
        almacenamiento.guardar.assert_not_called()

    def test_diagnostico_separado_y_credenciales_modelo_no_se_sustituyen(self):
        from dataset_manager import guardar_diagnostico
        from main import cargar_configuracion
        import json
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'config.json'
            datos = {'url_base':'http://camara.invalid','detector':{'confianza': .25, 'imgsz':640, 'clases':[2]}}
            ruta.write_text(json.dumps(datos))
            configuracion = cargar_configuracion(ruta)
            self.assertEqual(configuracion['detector']['confianza'], .25)
            self.assertEqual(configuracion['detector']['imgsz'], 640)
            self.assertEqual(json.loads(ruta.read_text()), datos)
            imagen = captura_svga().imagen
            diagnostico = guardar_diagnostico(imagen, Path(carpeta) / 'diagnosticos', {'valido':False, 'motivo':'prueba'})
            self.assertEqual(diagnostico.suffix, '.png')
            self.assertFalse(json.loads(diagnostico.with_suffix('.json').read_text())['valido'])

    def test_mediana_tres_muestras_reinicio_y_desactivacion(self):
        filtro = FiltroMediana()
        self.assertEqual(filtro.agregar(1, Conteo(1, 0, 0))[1], 1)
        filtro.agregar(2, Conteo(9, 2, 0))
        filtrado, muestras = filtro.agregar(3, Conteo(2, 1, 1))
        self.assertEqual(filtrado, Conteo(2, 1, 0))
        self.assertEqual(muestras, 3)
        with self.assertRaises(ValueError):
            filtro.agregar(3, Conteo(0, 0, 0))
        filtro.reiniciar()
        self.assertEqual(filtro.agregar(4, Conteo(0, 0, 0))[1], 1)
        self.assertEqual(FiltroMediana(False).agregar(1, Conteo(3, 0, 0)), (Conteo(3, 0, 0), 0))


class PruebasEvaluacion(unittest.TestCase):
    def test_metricas_no_interpretan_invalidos_como_ceros(self):
        registros = [dict(valido=True, n1=1, n2=1, n1_real=1, n2_real=1, inferencia_s=1, latencia_s=1),
                     dict(valido=True, n1=2, n2=0, n1_real=1, n2_real=1, inferencia_s=3, latencia_s=3),
                     dict(valido=False, n1=None, n2=None, n1_real=0, n2_real=0)]
        metricas = calcular_metricas(registros, 4)
        self.assertEqual(metricas['mae_carril_1'], .5)
        self.assertEqual(metricas['mae_carril_2'], .5)
        self.assertAlmostEqual(metricas['ambos_correctos_porcentaje'], 100 / 3)
        self.assertEqual(metricas['latencia_mediana_s'], 2)
        self.assertAlmostEqual(metricas['latencia_p95_s'], 2.9)
        self.assertEqual(metricas['frecuencia_efectiva_hz'], .5)
        invalidas = calcular_metricas([registros[-1]], 1)
        self.assertIsNone(invalidas['mae_carril_1'])
        self.assertEqual(invalidas['ambos_correctos_porcentaje'], 0)

    def test_registro_manual_y_separacion_de_grupos(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'escenas.csv'
            primera = Path(carpeta) / 'a.jpg'; primera.write_bytes(captura_svga().jpeg)
            segunda = Path(carpeta) / 'b.jpg'; segunda.write_bytes(captura_svga(2).jpeg)
            registrar_escena(ruta, primera, 0, 0, 'sesion-a', 'desarrollo')
            with self.assertRaises(ValueError):
                registrar_escena(ruta, segunda, 1, 0, 'sesion-a', 'final')
            filas = leer_escenas(ruta)
            self.assertEqual(filas[0]['n1_real'], 0)
            detector = Mock(); detector.detectar.return_value = ((), .1)
            registros, duracion = evaluar_escenas(filas, regiones_svga(), detector)
            self.assertTrue(registros[0]['valido'])
            self.assertEqual(registros[0]['n1'], 0)
            self.assertGreater(duracion, 0)
