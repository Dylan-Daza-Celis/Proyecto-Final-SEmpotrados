"""Regresiones vigentes de edicion ROI, conservadas de tarea07."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import soporte
from camera_client import EstadoAdquisicion
from main import Visualizador
from test_conteo_yolo import captura_svga,regiones_svga

class PruebasEdicionROI07(unittest.TestCase):
    def test_edicion_ordinaria_rechaza_imagen_antigua_desconexion_error_y_ausencia(self):
        for fallo in ('antigua','desconectada','error','sin_foto'):
            with self.subTest(fallo=fallo),tempfile.TemporaryDirectory() as carpeta:
                foto=replace(captura_svga(),iniciada_monotonic=98,recibida_monotonic=99)
                estado=EstadoAdquisicion(foto,True,'',1,100)
                ad=Mock();ad.obtener_estado.return_value=estado
                gui=Visualizador(ad,regiones_svga(),Mock(),Path(carpeta)/'roi.json',1);gui.captura=foto
                if fallo=='antigua':estado=replace(estado,confirmada_monotonic=80)
                elif fallo=='desconectada':estado=replace(estado,conectado=False)
                elif fallo=='error':estado=replace(estado,error_captura=True)
                else:estado=replace(estado,captura=None)
                ad.obtener_estado.return_value=estado
                with patch('main.time.monotonic',return_value=100):gui.tecla(ord('1'))
                self.assertIsNone(gui.activa);self.assertFalse(gui.pausa)
    def test_edicion_congela_la_adquisicion_actual_y_rechaza_cambio_epoca(self):
        foto=replace(captura_svga(),iniciada_monotonic=98,recibida_monotonic=99)
        estado=EstadoAdquisicion(foto,True,'',1,100);ad=Mock();ad.obtener_estado.return_value=estado
        gui=Visualizador(ad,regiones_svga(),Mock(),Path('no_escribir.json'),1)
        gui.captura=replace(foto,identificador='foto_neuronal_anterior')
        with patch('main.time.monotonic',return_value=100):gui.tecla(ord('1'))
        self.assertIs(gui.captura,foto);self.assertIs(gui.referencia_recalibracion,foto)
        gui.activa=None;ad.obtener_estado.return_value=replace(estado,epoca=1)
        with patch('main.time.monotonic',return_value=100):gui.tecla(ord('2'))
        self.assertIsNone(gui.activa)
    def test_reanudar_exige_referencia_actual_nueva_al_volver_a_editar(self):
        foto=replace(captura_svga(),iniciada_monotonic=98,recibida_monotonic=99)
        estado=EstadoAdquisicion(foto,True,'',1,100);ad=Mock();ad.obtener_estado.return_value=estado
        gui=Visualizador(ad,regiones_svga(),Mock(),Path('no_escribir.json'),1);gui.captura=foto
        with patch('main.time.monotonic',return_value=100):gui.tecla(ord('1'))
        self.assertEqual(gui.activa,1);gui._pausar(False)
        ad.obtener_estado.return_value=replace(estado,conectado=False)
        with patch('main.time.monotonic',return_value=101):gui.tecla(ord('2'))
        self.assertIsNone(gui.activa)
