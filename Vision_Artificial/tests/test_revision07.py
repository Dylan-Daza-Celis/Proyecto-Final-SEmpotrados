"""Regresiones de guardado, bordes ROI y separación desarrollo/final."""
from dataclasses import asdict, replace
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from soporte import captura_ejemplo
from camera_client import EstadoAdquisicion
from contador_vehiculos import asignar_roi,contar_vehiculos
from detector_vehiculos import Deteccion
from diagnosticar_deteccion import dibujar,main as diagnosticar
from evaluar import main as evaluar,registrar_escena
from main import Visualizador
from roi_manager import GestorROI
from test_conteo_yolo import captura_svga,regiones_svga


class PruebasGuardado07(unittest.TestCase):
    def preparar(self,carpeta):
        ruta=Path(carpeta)/'roi.json'
        regiones=regiones_svga(); regiones.guardar(ruta)
        original=ruta.read_bytes()
        anterior=replace(captura_svga(),iniciada_monotonic=98,recibida_monotonic=99)
        estado=EstadoAdquisicion(anterior,True,'',1,100)
        adquisidor=Mock(); adquisidor.obtener_estado.return_value=estado
        gui=Visualizador(adquisidor,regiones,Mock(),ruta,1)
        gui.captura=anterior
        with patch('main.time.monotonic',return_value=100):gui.tecla(ord('v'))
        nueva=replace(captura_svga(2),iniciada_monotonic=101,recibida_monotonic=101.5)
        adquisidor.obtener_estado.return_value=replace(estado,captura=nueva,secuencia=2,confirmada_monotonic=102)
        with patch('main.time.monotonic',return_value=102):
            gui.tecla(ord('1'));gui.tecla(13);gui.tecla(ord('2'));gui.tecla(13)
        self.assertIsNone(gui.activa)
        self.assertEqual(regiones.pendientes,set())
        self.assertTrue(regiones.requiere_guardado)
        return gui,adquisidor,ruta,original

    def test_g_rechaza_fallos_despues_de_ambas_confirmaciones(self):
        for fallo in ('desconexion','captura','epoca','status_antiguo','referencia','resolucion','reanudar'):
            with self.subTest(fallo=fallo),tempfile.TemporaryDirectory() as carpeta:
                gui,adquisidor,ruta,original=self.preparar(carpeta)
                estado=adquisidor.obtener_estado.return_value
                if fallo=='desconexion':estado=replace(estado,conectado=False)
                if fallo=='captura':estado=replace(estado,error_captura=True)
                if fallo=='epoca':estado=replace(estado,epoca=1)
                if fallo=='status_antiguo':estado=replace(estado,confirmada_monotonic=80)
                if fallo=='referencia':gui.captura=replace(gui.captura,identificador='otra')
                if fallo=='resolucion':estado=replace(estado,captura=captura_ejemplo())
                if fallo=='reanudar':gui._pausar(False)
                adquisidor.obtener_estado.return_value=estado
                with patch('main.time.monotonic',return_value=103):gui.tecla(ord('g'))
                self.assertEqual(ruta.read_bytes(),original)
                self.assertTrue(ruta.with_name('roi.json.invalidada').exists())
                self.assertTrue(gui.regiones.requiere_guardado)
                self.assertIsNotNone(gui.invalidada_desde)

    def test_g_guarda_referencia_historica_con_conexion_y_epoca_validas(self):
        with tempfile.TemporaryDirectory() as carpeta:
            gui,adquisidor,ruta,_=self.preparar(carpeta)
            # La geometría pausada puede tardar en editarse; el HTTP sí debe ser reciente.
            adquisidor.obtener_estado.return_value=replace(adquisidor.obtener_estado.return_value,confirmada_monotonic=199)
            with patch('main.time.monotonic',return_value=200):gui.tecla(ord('g'))
            self.assertIsNone(gui.invalidada_desde)
            self.assertEqual(GestorROI.cargar(ruta).estado_calibracion((800,600)),'')
            self.assertFalse(ruta.with_name('roi.json.invalidada').exists())

    def test_error_de_guardado_no_libera_contexto_ni_marca(self):
        with tempfile.TemporaryDirectory() as carpeta:
            gui,_,ruta,original=self.preparar(carpeta)
            with patch('main.time.monotonic',return_value=103),patch.object(gui.regiones,'guardar',side_effect=OSError('simulado')):
                gui.tecla(ord('g'))
            self.assertEqual(ruta.read_bytes(),original)
            self.assertIsNotNone(gui.referencia_recalibracion)
            self.assertTrue(ruta.with_name('roi.json.invalidada').exists())


class PruebasDiagnostico07(unittest.TestCase):
    def test_centros_flotantes_iguales_en_contador_y_texto_diagnostico(self):
        regiones=regiones_svga()
        for centro,categoria in ((349.8,'ROI1'),(350.2,'FUERA'),(449.8,'FUERA'),(450.2,'ROI2')):
            with self.subTest(centro=centro):
                d=Deteccion((centro-10,30,centro+10,50),2,'car',.9)
                self.assertEqual(asignar_roi(d,regiones,(800,600)),categoria)
                c=contar_vehiculos([d],regiones,(800,600))
                self.assertEqual((c.n1,c.n2,c.n_fuera),{'ROI1':(1,0,0),'ROI2':(0,1,0),'FUERA':(0,0,1)}[categoria])
                with patch.object(regiones,'contiene_punto',wraps=regiones.contiene_punto) as pertenencia,patch('diagnosticar_deteccion.cv2.putText') as texto:
                    dibujar(captura_svga().imagen,[asdict(d)|{'centro':(0,0)}],regiones,True)
                self.assertTrue(texto.call_args.args[1].endswith(categoria))
                self.assertTrue(all(llamada.args[1]==d.centro for llamada in pertenencia.call_args_list))

    def test_final_rechaza_barrido_y_exploracion_antes_de_cargar_modelo(self):
        for opcion in ('--barrido','--explorar'):
            with self.subTest(opcion=opcion),contextlib.redirect_stderr(io.StringIO()),patch('diagnosticar_deteccion.DetectorVehiculos') as modelo:
                with self.assertRaises(SystemExit):
                    diagnosticar(['--uso','final',opcion,'--salida','no_crear'])
                modelo.assert_not_called()

    def test_candidato_b_evaluacion_simulada_con_verdad_sin_modificar_config(self):
        with tempfile.TemporaryDirectory() as carpeta:
            raiz=Path(carpeta);config=raiz/'config.json';roi=raiz/'roi.json';foto=raiz/'escena.jpg'
            contenido='{"url_base":"","detector":{"confianza":0.27,"agnostic_nms":true}}'
            config.write_text(contenido);regiones_svga().guardar(roi);foto.write_bytes(captura_svga().jpeg)
            registrar_escena(raiz/'escenas.csv',foto,1,0,'grupo_simulado','desarrollo')
            detector=Mock();detector.detectar.return_value=((Deteccion((30,30,100,100),2,'car',.9),),.1)
            with patch('evaluar.DetectorVehiculos',return_value=detector) as fabrica,patch('evaluar.metadatos_reproducibilidad',return_value={}),contextlib.redirect_stdout(io.StringIO()):
                codigo=evaluar(['--config',str(config),'--escenas',str(raiz/'escenas.csv'),'--salida',str(raiz/'informe.json'),'--candidato-b'])
            self.assertEqual(codigo,0)
            parametros=fabrica.call_args.args[0]
            self.assertEqual((parametros['imgsz'],parametros['confianza'],parametros['iou'],parametros['agnostic_nms']),(960,.10,.45,False))
            self.assertEqual(parametros['backend'],'pytorch')
            self.assertEqual(config.read_text(),contenido)
            self.assertEqual(json.loads((raiz/'informe.json').read_text())['metricas']['ambos_correctos_porcentaje'],100)
            # Ese 100% corresponde solo al JPEG y detector simulados de esta prueba.

    def test_candidato_b_no_se_usa_para_seleccionar_sobre_final(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):evaluar(['--candidato-b','--uso','final'])
