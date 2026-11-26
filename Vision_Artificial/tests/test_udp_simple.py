"""UDP ASCII local y reconocimiento sin calibracion; no requiere dispositivos."""
from dataclasses import replace
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock,patch

import soporte
from camera_client import EstadoAdquisicion
from detector_vehiculos import Deteccion,PARAMETROS_INICIALES
from emisor_udp import codificar,decodificar,Snapshot,PreparadorEnvio,EmisorUDP,cargar_config
from inference_worker import TrabajadorInferencia,motivo_deteccion,motivo_diagnostico,motivo_resultado
from main import Visualizador
from roi_manager import GestorROI
from test_conteo_yolo import captura_svga,regiones_svga
from test_inference_worker import esperar


class PruebasASCII(unittest.TestCase):
    def test_codificar_decodificar_y_cero_valido(self):
        self.assertEqual(codificar(42,5,1,1),b'42,5,1,1')
        for campos in ((1,0,0,1),(2,0,0,0),(2**64-1,1000,1000,1)):
            self.assertEqual(decodificar(codificar(*campos)),campos)
    def test_rechaza_campos_tamano_y_rangos(self):
        for datos in (b'',b'0,0,0,1',b'1,0,0',b'1,0,0,1,2',b'1,1001,0,1',b'1,-1,0,1',b'1,0,0,2',
                      b'1,0,0,1\n',b' 1,0,0,1',b'01,0,0,1',b'1,00,0,1',b'1,0,0,1\x00',b'1,0,0,\xff',
                      b'18446744073709551616,0,0,1',b'X'*49):
            with self.subTest(datos=datos),self.assertRaises(ValueError):decodificar(datos)
        for campos in ((True,0,0,1),(1,False,0,1),(1,0,0,True),(1,1001,0,1),(0,0,0,1)):
            with self.assertRaises(ValueError):codificar(*campos)
    def test_configuracion_simple_no_sobrescribe_archivos(self):
        with tempfile.TemporaryDirectory() as carpeta:
            p=Path(carpeta)/'udp.json';p.write_text('{"activo":true,"ip_destino":"127.0.0.1","puerto":5005}')
            antes=p.read_bytes();self.assertEqual(cargar_config(p)['puerto'],5005);self.assertEqual(p.read_bytes(),antes)
            p.write_text('{"activo":true,"ip_destino":"no-es-IP","puerto":5005}')
            with self.assertRaises(ValueError):cargar_config(p)
    def test_nueva_observacion_sin_repetir_foto_y_reinicio_python(self):
        s=Snapshot(True,'',('ROI',),(0,7),3,1,120)
        p=PreparadorEnvio();self.assertEqual(p.preparar(s,100),[b'1,3,1,1'])
        self.assertEqual(p.preparar(s,101),[])
        self.assertEqual(p.preparar(replace(s,identidad=(0,8)),102),[b'2,3,1,1'])
        self.assertEqual(PreparadorEnvio().preparar(s,100),[b'1,3,1,1'])
    def test_invalidacion_no_es_cero_y_caducidad_no_se_rejuvenece(self):
        p=PreparadorEnvio();s=Snapshot(True,'',(),(0,1),0,0,102)
        self.assertEqual(p.preparar(s,100),[b'1,0,0,1'])
        self.assertEqual(p.preparar(s,102),[b'2,0,0,0']);self.assertEqual(p.preparar(s,103),[])
        invalido=Snapshot(motivo='Pausa',contexto=('pausa',))
        self.assertEqual(p.preparar(invalido,104),[b'3,0,0,0'])
        self.assertEqual(p.preparar(invalido,105),[])
    def test_fallo_breve_y_resultado_valido_no_ocultan_invalidacion(self):
        p=PreparadorEnvio();p.preparar(Snapshot(True,'',(0,),(0,1),4,1,110),100)
        salida=p.preparar(Snapshot(True,'',(1,),(1,2),2,3,112),102)
        self.assertEqual(salida,[b'2,0,0,0',b'3,2,3,1'])
    def test_loopback_unidireccional_y_cierre_invalido(self):
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as receptor:
            receptor.bind(('127.0.0.1',0));receptor.settimeout(1)
            foto=[Snapshot(True,'',(),(0,1),5,1,time.monotonic()+5)]
            emisor=EmisorUDP(dict(ip_destino='127.0.0.1',puerto=receptor.getsockname()[1]),lambda:foto[0])
            emisor.start()
            try:
                self.assertEqual(receptor.recv(49),b'1,5,1,1')
                receptor.settimeout(.12)
                with self.assertRaises(socket.timeout):receptor.recv(49)
                foto[0]=replace(foto[0],identidad=(0,2),n1=1,n2=3)
                receptor.settimeout(1);self.assertEqual(receptor.recv(49),b'2,1,3,1')
            finally:emisor.cerrar();emisor.join(2)
            self.assertFalse(emisor.is_alive());self.assertEqual(receptor.recv(49),b'3,0,0,0')
            self.assertEqual(emisor.obtener_estado()['enviados'],3)
    def test_error_local_de_sendto_no_confirma_entrega(self):
        emisor=EmisorUDP(dict(ip_destino='127.0.0.1',puerto=5005),lambda:Snapshot())
        sock=Mock();sock.sendto.side_effect=OSError('simulado')
        emisor._enviar(sock,b'1,0,0,0')
        self.assertEqual((emisor.obtener_estado()['enviados'],emisor.obtener_estado()['errores']),(0,1))


class PruebasReconocimientoSinROI(unittest.TestCase):
    def trabajador(self):
        modelo=Mock();modelo.detectar.return_value=((Deteccion((30,30,90,90),2,'car',.9),),.01)
        fabrica=Mock(return_value=modelo)
        t=TrabajadorInferencia(PARAMETROS_INICIALES,12,filtro=False,fabrica_detector=fabrica,calentamiento=3)
        t.start();self.addCleanup(lambda:(t.cerrar(),t.join(3)))
        esperar(lambda:not t._preparando)
        return t,modelo,fabrica
    def test_reconoce_dibuja_cajas_y_confianza_sin_publicar_carriles(self):
        t,modelo,fabrica=self.trabajador();regiones=GestorROI();foto=captura_svga()
        t.enviar(foto,1,regiones);esperar(lambda:t.obtener_estado().resultado is not None)
        ia=t.obtener_estado();self.assertEqual(len(ia.resultado.detecciones),1)
        self.assertIsNone(ia.resultado.instantaneo);self.assertIsNone(ia.resultado.filtrado)
        estado=EstadoAdquisicion(foto,True,'',1,time.monotonic())
        self.assertEqual(motivo_deteccion(estado,foto,6),'')
        self.assertEqual(motivo_diagnostico(estado,foto,ia,6,12),'')
        self.assertTrue(motivo_resultado(estado,foto,regiones,ia,6,12))
        ad=Mock();ad.obtener_estado.return_value=estado
        gui=Visualizador(ad,regiones,Mock(),Path('no_guardar.json'),1,t)
        with patch('main.cv2.rectangle',wraps=__import__('cv2').rectangle) as cajas,patch('main.cv2.putText',wraps=__import__('cv2').putText) as texto:
            gui.dibujar()
        self.assertTrue(cajas.called)
        self.assertTrue(any('car 0.90'==c.args[1] for c in texto.call_args_list))
        self.assertFalse(gui.snapshot_udp().valido)
        self.assertFalse(gui.informacion_diagnostico['valido'])
        fabrica.assert_called_once();modelo.calentar.assert_called_once();modelo.detectar.assert_called_once()
        self.assertFalse(t.enviar(foto,1,regiones))
    def test_invalidar_roi_persistente_no_deshabilita_yolo(self):
        t,modelo,_=self.trabajador();regiones=regiones_svga()
        with tempfile.TemporaryDirectory() as carpeta:
            ruta=Path(carpeta)/'roi.json';regiones.guardar(ruta);regiones.invalidar_calibracion()
            self.assertTrue(ruta.with_name('roi.json.invalidada').exists())
            foto=captura_svga();t.enviar(foto,1,regiones)
            esperar(lambda:t.obtener_estado().resultado is not None)
            self.assertIsNone(t.obtener_estado().resultado.instantaneo)
            modelo.detectar.assert_called_once()
            self.assertTrue(GestorROI.cargar(ruta).estado_calibracion((800,600)))
    def test_roi_validas_y_foto_nueva_recuperan_conteos_sin_otro_modelo(self):
        t,modelo,fabrica=self.trabajador();t.enviar(captura_svga(),1,GestorROI())
        esperar(lambda:t.obtener_estado().resultado is not None)
        foto=captura_svga(2);regiones=regiones_svga();t.enviar(foto,2,regiones)
        esperar(lambda:t.obtener_estado().resultado.secuencia==2)
        ia=t.obtener_estado();estado=EstadoAdquisicion(foto,True,'',2,time.monotonic())
        self.assertEqual(motivo_resultado(estado,foto,regiones,ia,6,12),'')
        self.assertEqual(ia.resultado.instantaneo.n1,1)
        fabrica.assert_called_once();self.assertEqual(modelo.detectar.call_count,2)
