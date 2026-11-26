import json
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from test_conteo_yolo import captura_svga, regiones_svga
from test_inference_worker import esperar
from detector_vehiculos import PARAMETROS_INICIALES, validar_parametros
from inference_worker import TrabajadorInferencia
from dataset_manager import GestorDataset
from camera_client import EstadoAdquisicion
from main import Visualizador
from comparar_motores import correspondencias, comparar


class PruebasOptimizacion(unittest.TestCase):
    def test_calentamiento_unico_no_publica_y_descarta_fotos_previas(self):
        entro=threading.Event(); liberar=threading.Event()
        detector=Mock()
        def calentar(numero,detener):
            self.assertEqual(numero,3); entro.set(); liberar.wait(2)
        detector.calentar.side_effect=calentar; detector.detectar.return_value=((),.01)
        trabajador=TrabajadorInferencia(PARAMETROS_INICIALES,fabrica_detector=lambda _:detector,calentamiento=3)
        trabajador.start()
        self.addCleanup(lambda:(liberar.set(),trabajador.cerrar(),trabajador.join(3)))
        self.assertTrue(entro.wait(2))
        vieja=captura_svga(); regiones=regiones_svga()
        trabajador.enviar(vieja,1,regiones)
        self.assertEqual(trabajador.obtener_estado().motivo,'CALENTANDO MODELO')
        self.assertIsNone(trabajador.obtener_estado().resultado)
        liberar.set(); esperar(lambda:not trabajador._preparando)
        self.assertFalse(trabajador.enviar(vieja,1,regiones))
        detector.detectar.assert_not_called()
        nueva=captura_svga(2); trabajador.enviar(nueva,2,regiones)
        esperar(lambda:trabajador.obtener_estado().resultado is not None)
        self.assertIs(trabajador.obtener_estado().resultado.captura,nueva)
        detector.calentar.assert_called_once()
        self.assertEqual(trabajador.obtener_estado().resultado.muestras_validas,1)

    def test_frecuencia_no_caduca_con_filtro_desactivado(self):
        detector=Mock(); detector.detectar.return_value=((),.01)
        trabajador=TrabajadorInferencia(PARAMETROS_INICIALES,filtro=False,fabrica_detector=lambda _:detector)
        trabajador.start(); self.addCleanup(lambda:(trabajador.cerrar(),trabajador.join(3)))
        for numero in (1,2):
            trabajador.enviar(captura_svga(numero),numero,regiones_svga())
            esperar(lambda:trabajador.obtener_estado().resultado is not None and trabajador.obtener_estado().resultado.secuencia==numero)
        frecuencia=trabajador.obtener_estado().frecuencia_hz
        self.assertGreater(frecuencia,0)
        with patch('inference_worker.time.monotonic',return_value=time.monotonic()+100):
            self.assertEqual(trabajador.obtener_estado().frecuencia_hz,frecuencia)

    def test_guardar_pausada_historica_sin_rehabilitar_control(self):
        captura=replace(captura_svga(),recibida_monotonic=time.monotonic()-100,iniciada_monotonic=None)
        adquisidor=Mock(); adquisidor.obtener_estado.return_value=EstadoAdquisicion(captura,False)
        with tempfile.TemporaryDirectory() as carpeta:
            almacen=GestorDataset(carpeta)
            gui=Visualizador(adquisidor,regiones_svga(),almacen,Path(carpeta)/'roi.json',1)
            gui.captura=captura; gui.pausa=True
            gui.tecla(ord('s'))
            registro=json.loads(almacen.metadatos.read_text())
            self.assertTrue(registro['referencia_historica'])
            self.assertFalse(registro['valida_para_control'])
            self.assertEqual((Path(carpeta)/registro['archivo']).read_bytes(),captura.jpeg)
            self.assertFalse(adquisidor.obtener_estado().conectado)

    def test_parametros_backend_y_hilos_invalidos(self):
        for p in ({'backend':'otro'},{'hilos_cpu':-1},{'hilos_interop':True}):
            with self.assertRaises(ValueError): validar_parametros(p)

    def test_correspondencias_por_clase_y_caja_no_solo_conteo(self):
        a=[dict(caja=[0,0,10,10],clase=2,confianza=.9)]
        b=[dict(caja=[0,0,10,10],clase=7,confianza=.8)]
        r=correspondencias(a,b)
        self.assertEqual(r['faltantes'],[0]); self.assertEqual(r['adicionales'],[0])
        b[0]['clase']=2; r=correspondencias(a,b)
        self.assertAlmostEqual(r['pares'][0]['diferencia_confianza'],-.1)
        informe=dict(parametros=PARAMETROS_INICIALES, pesos_sha256='mismo', sostenido={},
            muestras=[dict(sha256='foto',forma_entrada=[1,3,736,960],detecciones=a)])
        otro=json.loads(json.dumps(informe))
        self.assertIn('PENDIENTE',comparar(informe,otro)['seleccion_definitiva'])
        otro['muestras'][0]['forma_entrada']=[1,3,960,960]
        with self.assertRaisesRegex(ValueError,'Formas efectivas'):
            comparar(informe,otro)
