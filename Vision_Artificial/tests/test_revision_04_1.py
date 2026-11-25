"""Regresiones de vigencia, persistencia y reproducibilidad sin cámara."""
from dataclasses import replace
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
import requests

from soporte import respuesta, jpeg_ejemplo
from test_conteo_yolo import captura_svga, regiones_svga
from camera_client import ClienteCamara, Adquisidor, EstadoAdquisicion, captura_vigente
from contador_vehiculos import Conteo
from detector_vehiculos import DetectorVehiculos, CLASES_COCO, validar_parametros
from evaluar import registrar_escena, leer_escenas, evaluar_escenas, metadatos_reproducibilidad
from inference_worker import ResultadoInferencia, EstadoInferencia, motivo_resultado
from main import cargar_configuracion
from roi_manager import GestorROI


class PruebasRevision(unittest.TestCase):
    def test_defaults_y_valores_locales_se_conservan(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'config.json'
            ruta.write_text('{"url_base":"camara.invalid"}')
            config = cargar_configuracion(ruta)
            self.assertEqual((config['max_antiguedad_imagen_s'], config['max_antiguedad_resultado_s']), (6, 12))
            self.assertFalse(config['filtro_mediana'])
            datos = dict(url_base='camara.invalid', max_antiguedad_imagen_s=30,
                         max_antiguedad_resultado_s=40, filtro_mediana=True,
                         detector={'agnostic_nms': True})
            ruta.write_text(json.dumps(datos))
            config = cargar_configuracion(ruta)
            self.assertEqual((config['max_antiguedad_imagen_s'], config['max_antiguedad_resultado_s']), (30, 40))
            self.assertTrue(config['filtro_mediana'])
            self.assertTrue(config['detector']['agnostic_nms'])
            self.assertEqual(json.loads(ruta.read_text()), datos)

    def test_edad_desde_inicio_incluye_reintento_y_status_no_la_renueva(self):
        sesion = Mock()
        sesion.get.side_effect = [requests.Timeout(), respuesta(jpeg_ejemplo())]
        detener = Mock(); detener.is_set.return_value = False; detener.wait.return_value = False
        fallo = Mock()
        with ClienteCamara('camara.invalid', sesion=sesion, reintentos=1, detener=detener) as cliente:
            cliente.al_fallo = fallo
            with patch('camera_client.time.monotonic', side_effect=[10, 20]):
                captura = cliente.capturar()
        fallo.assert_called_once()
        self.assertEqual(captura.origen_monotonic, 10)
        estado = EstadoAdquisicion(captura, True, '', 1, 22)
        self.assertFalse(captura_vigente(estado, captura, 6, ahora=22))

    def test_fallo_publicado_antes_de_esperar_reintento_y_epoca_cambia(self):
        sesion = Mock()
        sesion.get.side_effect = [requests.Timeout(), respuesta(jpeg_ejemplo())]
        detener = Mock(); detener.is_set.return_value = False
        adquisidor = Adquisidor('camara.invalid', {})
        captura = captura_svga()
        adquisidor._publicar(captura=captura, conectado=True, secuencia=1, confirmada_monotonic=time.monotonic())
        def esperar(_):
            estado = adquisidor.obtener_estado()
            self.assertFalse(estado.conectado)
            self.assertTrue(estado.error_captura)
            self.assertGreater(estado.epoca, 0)
            return False
        detener.wait.side_effect = esperar
        with ClienteCamara('camara.invalid', sesion=sesion, reintentos=1, detener=detener) as cliente:
            cliente.al_fallo = adquisidor._fallo
            nueva = cliente.capturar()
        epoca = adquisidor.obtener_estado().epoca
        adquisidor._publicar(captura=nueva, conectado=True, error_captura=False)
        self.assertEqual(adquisidor.obtener_estado().epoca, epoca)
        regiones = regiones_svga()
        resultado = ResultadoInferencia(captura, 1, (), Conteo(0, 0, 0), Conteo(0, 0, 0),
            0, .01, time.monotonic(), .01, 'yolo11x.pt', (regiones.firma(), 0), 1)
        estado_ia = EstadoInferencia(resultado, '', '', None, 0, 0, 1)
        estado = replace(adquisidor.obtener_estado(), captura=captura, confirmada_monotonic=time.monotonic())
        self.assertIn('contexto cambiado', motivo_resultado(estado, captura, regiones, estado_ia, 6, 12))

    def test_roi_invalidada_por_v_o_resolucion_persiste_hasta_guardar(self):
        for accion in ('v', 'resolucion'):
            with self.subTest(accion=accion), tempfile.TemporaryDirectory() as carpeta:
                ruta = Path(carpeta) / 'roi.json'
                regiones = regiones_svga(); regiones.guardar(ruta)
                original = ruta.read_bytes()
                if accion == 'v':
                    regiones.invalidar_calibracion()
                else:
                    regiones.observar_resolucion((320, 240))
                self.assertEqual(ruta.read_bytes(), original)
                reabierta = GestorROI.cargar(ruta)
                self.assertEqual(reabierta.regiones, regiones.regiones)
                self.assertIn('recalibracion', reabierta.estado_calibracion((800, 600)))
                reabierta.establecer(1, reabierta.puntos_pixel(1, (800, 600)), (800, 600))
                with self.assertRaises(ValueError):
                    reabierta.guardar(ruta)
                reabierta.establecer(2, reabierta.puntos_pixel(2, (800, 600)), (800, 600))
                self.assertIn('recalibracion', reabierta.estado_calibracion((800, 600)))
                # Cerrar sin G sigue invalidando ambas al reabrir.
                self.assertEqual(GestorROI.cargar(ruta).pendientes, {1, 2})
                with patch.object(Path, 'replace', side_effect=OSError('Disco simulado')):
                    with self.assertRaises(OSError):
                        reabierta.guardar(ruta)
                self.assertIn('recalibracion', GestorROI.cargar(ruta).estado_calibracion((800, 600)))
                reabierta.guardar(ruta)
                self.assertEqual(GestorROI.cargar(ruta).estado_calibracion((800, 600)), '')

    def test_agnostic_nms_booleano_se_envia_sin_supresion_adicional(self):
        for valor in (True, False):
            with self.subTest(valor=valor), tempfile.TemporaryDirectory() as carpeta:
                pesos = Path(carpeta) / 'yolo11x.pt'; pesos.write_bytes(b'simulado')
                modelo = Mock(); modelo.names = CLASES_COCO
                cajas = Mock()
                cajas.data.cpu.return_value.numpy.return_value = np.array(
                    [[30, 30, 100, 100, .9, 2], [31, 30, 101, 100, .8, 7]])
                modelo.predict.return_value = [SimpleNamespace(orig_shape=(600, 800), boxes=cajas)]
                detector = DetectorVehiculos({'pesos': pesos, 'agnostic_nms': valor}, lambda _: modelo)
                detecciones, _ = detector.detectar(captura_svga().imagen)
                self.assertEqual(len(detecciones), 2)
                self.assertIs(modelo.predict.call_args.kwargs['agnostic_nms'], valor)
        for invalido in (1, 'true', None):
            with self.assertRaises(ValueError):
                validar_parametros({'agnostic_nms': invalido})

    def test_hash_impide_duplicados_por_nombre_y_entre_usos(self):
        with tempfile.TemporaryDirectory() as carpeta:
            carpeta = Path(carpeta); csv_ruta = carpeta / 'escenas.csv'
            a = carpeta / 'a.jpg'; b = carpeta / 'b.jpg'
            a.write_bytes(captura_svga().jpeg); b.write_bytes(a.read_bytes())
            registrar_escena(csv_ruta, a, 0, 0, 'a', 'desarrollo')
            for uso in ('desarrollo', 'final'):
                with self.assertRaisesRegex(ValueError, 'SHA-256'):
                    registrar_escena(csv_ruta, b, 0, 0, 'b', uso)
            self.assertEqual(leer_escenas(csv_ruta)[0]['sha256'], hashlib.sha256(a.read_bytes()).hexdigest())
            # También rechaza manifiestos editados manualmente antes de filtrar --uso.
            with csv_ruta.open('a', newline='') as archivo:
                csv.writer(archivo).writerow([str(b), 0, 0, 'b', 'final', hashlib.sha256(b.read_bytes()).hexdigest()])
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                leer_escenas(csv_ruta)

    def test_informe_hash_versiones_y_cambio_de_foto(self):
        with tempfile.TemporaryDirectory() as carpeta:
            carpeta = Path(carpeta); foto = carpeta / 'a.jpg'; pesos = carpeta / 'yolo11x.pt'; roi = carpeta / 'roi.json'
            foto.write_bytes(captura_svga().jpeg); pesos.write_bytes(b'pesos'); regiones_svga().guardar(roi)
            with patch('evaluar.version', side_effect=lambda paquete: {'ultralytics':'8.4.218','torch':'2.15.0+cpu'}[paquete]):
                datos = metadatos_reproducibilidad(pesos, roi)
            self.assertEqual(datos['pesos_sha256'], hashlib.sha256(pesos.read_bytes()).hexdigest())
            self.assertEqual(datos['calibracion_sha256'], hashlib.sha256(roi.read_bytes()).hexdigest())
            self.assertEqual(datos['pytorch'], '2.15.0+cpu')
            detector = Mock(); detector.detectar.return_value = ((), .1)
            escena = dict(archivo=foto, n1_real=0, n2_real=0, sha256='hash anterior')
            registros, _ = evaluar_escenas([escena], regiones_svga(), detector)
            self.assertFalse(registros[0]['valido'])
            self.assertIn('cambió', registros[0]['error'])
            detector.detectar.assert_not_called()

    def test_csv_anterior_migra_y_detecta_cambio_posterior(self):
        with tempfile.TemporaryDirectory() as carpeta:
            carpeta = Path(carpeta); ruta = carpeta / 'escenas.csv'
            a = carpeta / 'a.jpg'; b = carpeta / 'b.jpg'
            a.write_bytes(captura_svga(1).jpeg); b.write_bytes(captura_svga(2).jpeg)
            originales = a.read_bytes(), b.read_bytes()
            with ruta.open('w', newline='') as archivo:
                escritor = csv.writer(archivo)
                escritor.writerow(['archivo','n1_real','n2_real','grupo','uso'])
                escritor.writerow(['a.jpg',0,0,'a','desarrollo'])
            self.assertEqual(len(leer_escenas(ruta)), 1)
            registrar_escena(ruta, b, 0, 0, 'b', 'final')
            self.assertEqual(len(leer_escenas(ruta)), 2)
            self.assertEqual((a.read_bytes(), b.read_bytes()), originales)
            self.assertIn('sha256', ruta.read_text().splitlines()[0])
            a.write_bytes(originales[1])
            with self.assertRaisesRegex(ValueError, 'SHA-256 no coincide'):
                leer_escenas(ruta)

    def test_resultado_caduca_desde_solicitud_aunque_recepcion_sea_reciente(self):
        ahora = time.monotonic()
        regiones = regiones_svga()
        anterior = replace(captura_svga(), recibida_monotonic=ahora-2, iniciada_monotonic=ahora-13)
        actual = captura_svga(2)
        resultado = ResultadoInferencia(anterior, 1, (), Conteo(0,0,0), Conteo(0,0,0),
            0, 4, ahora, 13, 'yolo11x.pt', (regiones.firma(), 0), 1)
        estado_ia = EstadoInferencia(resultado, '', '', None, 0, 0, 1)
        estado = EstadoAdquisicion(actual, True, '', 2, ahora)
        self.assertEqual(motivo_resultado(estado, actual, regiones, estado_ia, 6, 12, ahora=ahora),
                         'Resultado neuronal antiguo')
