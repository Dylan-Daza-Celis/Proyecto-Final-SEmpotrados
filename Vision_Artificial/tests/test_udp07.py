"""Red simulada y codec C anfitrion; no verifica hardware ni una LAN fisica."""
import ctypes
from dataclasses import replace
import hmac
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import Mock,patch

import soporte
from camera_client import EstadoAdquisicion
from main import Visualizador
from protocolo_udp import *
from servidor_udp import SesionServidor,ServidorUDP,Snapshot
from test_conteo_yolo import captura_svga,regiones_svga

RAIZ=Path(__file__).resolve().parents[2]
CLAVE=bytes(range(32))  # Publica, exclusivamente para pruebas.
EMISOR=bytes(range(16));RECEPTOR=b'R'*16


class Banco:
    def __init__(self):
        self.t=100.;self.s=SesionServidor(EMISOR,CLAVE,reloj=lambda:self.t)
        self.nonce=0;self.r=RECEPTOR;self.sesion=CERO
    def enviar(self,tipo=CONSULTA,**campos):
        self.nonce+=1
        m=Mensaje(tipo,EMISOR,self.sesion,self.r,nonce=self.nonce,evento=1,**campos)
        return decodificar(self.s.procesar(codificar(m,CLAVE)),CLAVE)
    def asociar(self):
        desafio=self.enviar(HELLO);self.sesion=desafio.sesion_emisor
        invalidacion=self.enviar(CONFIRMAR,barrera=desafio.barrera)
        self.assert_inval=invalidacion
        return invalidacion
    def reconocer(self):return self.enviar(reconocimiento=self.s.invalidacion,estado=SEGURO)
    def foto(self,numero=1,origen=None,**otros):
        self.s.actualizar(Snapshot(True,0,('contexto',),numero,1,self.t if origen is None else origen,0,0,**otros))


class PruebasProtocolo07(unittest.TestCase):
    def test_vectores_hmac_y_anchos(self):
        vectores=json.loads((RAIZ/'Proyecto_Final_C6/tests/vectores_udp07.json').read_text())
        for v in vectores['vectores']:
            datos=bytes.fromhex(v['datagrama_hex']);clave=bytes.fromhex(vectores['clave_prueba_hex'])
            self.assertEqual(len(datos),152)
            self.assertEqual(hmac.digest(clave,datos[:120],'sha256').hex(),v['hmac_sha256'])
            self.assertEqual(codificar(decodificar(datos,clave),clave),datos)
    def test_datagramas_malformados_y_mac(self):
        original=codificar(Mensaje(HELLO,EMISOR,sesion_receptor=RECEPTOR,nonce=1),CLAVE)
        for datos in (b'',original[:-1],original+b'x',bytes(513),original[:120]+bytes(32)):
            with self.subTest(longitud=len(datos)),self.assertRaises(ValueError):decodificar(datos,CLAVE)
        for posicion,valor in ((0,0),(4,2),(5,8),(6,3),(7,8),(108,255),(112,8),(113,1)):
            p=bytearray(original);p[posicion]=valor;p[120:]=hmac.digest(CLAVE,p[:120],'sha256')
            with self.subTest(posicion=posicion),self.assertRaises(ValueError):decodificar(bytes(p),CLAVE)
    def test_rangos_y_cero_valido(self):
        resultado=Mensaje(RESULTADO,EMISOR,resultado=1,evento=2,valido=True)
        self.assertEqual(decodificar(codificar(resultado,CLAVE),CLAVE).n1,0)
        for campos in ({'n1':True},{'n1':1001},{'n2':-1},{'edad_ms':2**32},{'nonce':2**64}, {'tipo':True}):
            with self.subTest(campos=campos),self.assertRaises(ValueError):codificar(replace(resultado,**campos),CLAVE)


class PruebasSesion07(unittest.TestCase):
    def test_invalidacion_rapida_retenida_y_captura_posterior_al_ack(self):
        b=Banco();b.foto();inv=b.asociar()
        b.t+=.01;b.foto(2)
        b.s.actualizar(Snapshot(motivo=CAMARA,contexto=('contexto',)))
        b.t+=.01;b.foto(3)
        respuesta=b.enviar();self.assertEqual(respuesta.tipo,INVALIDACION)
        self.assertGreater(respuesta.evento,inv.evento)
        self.assertEqual(b.reconocer().tipo,ESPERA) # La foto 3 precede al ACK.
        b.t+=.01;b.foto(4)
        self.assertEqual(b.enviar().tipo,RESULTADO)
    def test_duplicado_es_mantenimiento_y_edad_se_recalcula(self):
        b=Banco();b.foto();b.asociar();b.reconocer();b.t+=.1;b.foto(2);b.t+=.321
        r=b.enviar();self.assertEqual(r.tipo,RESULTADO);self.assertTrue(321<=r.edad_ms<=322)
        b.t+=1;self.assertEqual(b.enviar().tipo,ESPERA)
        b.t+=13;b.foto(3,origen=b.t-12);self.assertEqual(b.enviar().tipo,INVALIDACION)
    def test_no_reconocer_desde_verde_o_barrera_antigua(self):
        b=Banco();b.asociar();id=b.s.invalidacion
        self.assertEqual(b.enviar(reconocimiento=id,estado=1).tipo,INVALIDACION)
        self.assertEqual(b.enviar(reconocimiento=id-1,estado=7).tipo,INVALIDACION)
        self.assertTrue(b.s.pendiente)
    def test_auth_antes_de_mutaciones_y_nonce_generacion_antigua(self):
        b=Banco();b.asociar();b.reconocer()
        ultimo=b.s.ultimo_nonce;sesion=b.s.activa;evento=b.s.evento
        m=Mensaje(CONSULTA,EMISOR,b.sesion,b.r,nonce=ultimo+1,evento=1)
        p=codificar(m,CLAVE)
        with self.assertRaises(ValueError):b.s.procesar(p[:-1]+bytes([p[-1]^1]))
        self.assertEqual((b.s.ultimo_nonce,b.s.activa,b.s.evento),(ultimo,sesion,evento))
        with self.assertRaises(ValueError):b.s.procesar(codificar(replace(m,nonce=ultimo),CLAVE))
        with self.assertRaises(ValueError):b.s.procesar(codificar(replace(m,evento=0),CLAVE))
        self.assertEqual(b.s.ultimo_nonce,ultimo)
    def test_reinicio_receptor_retira_sesion_y_reinicio_emisor_desafia(self):
        b=Banco();b.asociar();anterior=b.r
        b.r=b'X'*16;b.sesion=CERO;b.nonce=0;b.asociar()
        with self.assertRaises(ValueError):
            b.s.procesar(codificar(Mensaje(HELLO,EMISOR,sesion_receptor=anterior,nonce=100),CLAVE))
        reiniciado=SesionServidor(EMISOR,CLAVE,reloj=lambda:b.t)
        with self.assertRaises(ValueError):
            reiniciado.procesar(codificar(Mensaje(CONSULTA,EMISOR,b.sesion,b.r,nonce=100),CLAVE))
        self.assertNotEqual(reiniciado.sesion,b.sesion)
        r=decodificar(reiniciado.procesar(codificar(Mensaje(HELLO,EMISOR,sesion_receptor=b.r,nonce=101),CLAVE)),CLAVE)
        self.assertEqual(r.tipo,ASOCIACION)
    def test_desafio_caducado_y_duplicado(self):
        b=Banco();m=Mensaje(HELLO,EMISOR,sesion_receptor=b.r,nonce=1)
        d=decodificar(b.s.procesar(codificar(m,CLAVE)),CLAVE)
        with self.assertRaises(ValueError):b.s.procesar(codificar(m,CLAVE))
        b.sesion=d.sesion_emisor;b.nonce=1;b.t+=3.1
        with self.assertRaises(ValueError):b.enviar(CONFIRMAR,barrera=d.barrera)
    def test_cambio_contexto_aunque_haya_resultado_dispara_barrera(self):
        b=Banco();b.foto();b.asociar();b.reconocer();b.t+=1;b.foto(2)
        self.assertEqual(b.enviar().tipo,RESULTADO)
        b.s.actualizar(Snapshot(True,0,('epoca nueva',),3,2,b.t,3,1))
        self.assertEqual(b.enviar().tipo,INVALIDACION)
    def test_caducidad_entre_polls_no_se_oculta_con_un_resultado_nuevo(self):
        b=Banco();b.foto();b.asociar();b.reconocer();b.t+=1
        b.s.actualizar(Snapshot(True,0,('contexto',),2,1,b.t,0,0,b.t+.01))
        self.assertEqual(b.enviar().tipo,RESULTADO)
        b.t+=.02;b.foto(3)
        self.assertEqual(b.enviar().tipo,INVALIDACION)
    def test_loopback_real_con_resultado_simulado_y_cierre(self):
        foto=[Snapshot()]
        servicio=ServidorUDP(dict(emisor=EMISOR,clave=CLAVE,max_edad_ms=12000,direccion='127.0.0.1',puerto=0),lambda:foto[0])
        servicio.start();self.assertTrue(servicio.iniciado.wait(2));self.assertFalse(servicio.error)
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as cliente:
                cliente.settimeout(1)
                def pedir(m):
                    cliente.sendto(codificar(m,CLAVE),servicio.direccion)
                    return decodificar(cliente.recv(513),CLAVE)
                d=pedir(Mensaje(HELLO,EMISOR,sesion_receptor=RECEPTOR,nonce=1))
                inv=pedir(Mensaje(CONFIRMAR,EMISOR,d.sesion_emisor,RECEPTOR,nonce=2,barrera=d.barrera,evento=1))
                self.assertEqual(inv.tipo,INVALIDACION)
                r=pedir(Mensaje(CONSULTA,EMISOR,d.sesion_emisor,RECEPTOR,nonce=3,reconocimiento=inv.evento,evento=1))
                self.assertEqual(r.tipo,ESPERA)
                # El origen se toma despues del ACK observado, sin inferencia ni camara real.
                import time
                # monotonic() puede tener granularidad de unos milisegundos en Windows.
                while time.monotonic()<=servicio.sesion.posterior_a:time.sleep(.001)
                foto[0]=Snapshot(True,0,(),1,1,time.monotonic(),0,0)
                r=pedir(Mensaje(CONSULTA,EMISOR,d.sesion_emisor,RECEPTOR,nonce=4,evento=1))
                self.assertEqual((r.tipo,r.n1,r.n2),(RESULTADO,0,0))
        finally:servicio.cerrar();servicio.join(2)
        self.assertFalse(servicio.is_alive())


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


class PruebasCodecC07(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tcc=RAIZ/'Proyecto_Final_C6/.herramientas/tcc/tcc/tcc.exe'
        if not tcc.exists():raise unittest.SkipTest('Compilador anfitrion TinyCC no disponible; ver PROTOCOLO_UDP07.md')
        salida=RAIZ/'Proyecto_Final_C6/.herramientas/codec_udp07.dll'
        subprocess.run([str(tcc),'-shared','-Wall','-Werror','-I'+str(RAIZ/'Proyecto_Final_C6/main'),
            str(RAIZ/'Proyecto_Final_C6/tests/puente_codec.c'),str(RAIZ/'Proyecto_Final_C6/main/protocolo_udp.c'),'-o',str(salida)],check=True,capture_output=True)
        cls.lib=ctypes.CDLL(str(salida))
        cls.F=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p)
        def firmar(k,p,n,t):ctypes.memmove(t,hmac.digest(ctypes.string_at(k,32),ctypes.string_at(p,n),'sha256'),32);return True
        def verificar(k,p,n,t):return hmac.compare_digest(hmac.digest(ctypes.string_at(k,32),ctypes.string_at(p,n),'sha256'),ctypes.string_at(t,32))
        cls.f=cls.F(firmar);cls.v=cls.F(verificar)
        cls.lib.codec_ida_vuelta.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_void_p,cls.F,cls.F]
        cls.lib.codec_ida_vuelta.restype=ctypes.c_int
    def test_vectores_python_c_exactos(self):
        v=json.loads((RAIZ/'Proyecto_Final_C6/tests/vectores_udp07.json').read_text())
        for vector in v['vectores']:
            p=bytes.fromhex(vector['datagrama_hex']);salida=ctypes.create_string_buffer(152)
            self.assertEqual(self.lib.codec_ida_vuelta(p,len(p),CLAVE,salida,self.f,self.v),1)
            self.assertEqual(salida.raw,p)
    def test_c_rechaza_mac_tamano_y_formato_sin_escribir_salida(self):
        p=codificar(Mensaje(HELLO,EMISOR,sesion_receptor=RECEPTOR,nonce=1),CLAVE)
        malos=[p[:-1],p+b'x',p[:120]+bytes(32)]
        q=bytearray(p);q[113]=1;q[120:]=hmac.digest(CLAVE,q[:120],'sha256');malos.append(bytes(q))
        for q in malos:
            salida=ctypes.create_string_buffer(b'X'*152,152)
            self.assertEqual(self.lib.codec_ida_vuelta(q,len(q),CLAVE,salida,self.f,self.v),0)
            self.assertEqual(salida.raw,b'X'*152)
