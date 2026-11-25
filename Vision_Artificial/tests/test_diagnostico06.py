from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
from soporte import captura_ejemplo

from camera_client import EstadoAdquisicion
from comparar_motores import comparar
from detector_vehiculos import PARAMETROS_INICIALES
from diagnosticar_deteccion import hipotesis,CONFIGURACIONES,comparar_registros
from main import Visualizador
from test_conteo_yolo import captura_svga,regiones_svga


class PruebasDiagnostico06(unittest.TestCase):
    def test_conserva_repeticiones_y_mide_inestabilidad(self):
        caja=dict(caja=[0,0,10,10],clase=2,confianza=.8)
        muestras=[dict(sha256='foto',forma_entrada=[1,3,736,960],detecciones=[caja]),
                  dict(sha256='foto',forma_entrada=[1,3,736,960],detecciones=[])]
        a=dict(parametros=PARAMETROS_INICIALES,pesos_sha256='igual',muestras=muestras,sostenido={})
        b=deepcopy(a)
        r=comparar(a,b)['escenas'][0]
        self.assertEqual(len(r['referencia']),2)
        self.assertEqual(r['estabilidad_referencia'][0]['faltantes'],[0])
        self.assertEqual(len(r['comparaciones']),2)
        b['muestras'].pop()
        with self.assertRaisesRegex(ValueError,'repeticiones'): comparar(a,b)

    def test_informa_experimentos_con_varias_variables(self):
        a=dict(parametros=PARAMETROS_INICIALES,pesos_sha256='x',muestras=[],sostenido={})
        b=deepcopy(a); b['parametros'].update(hilos_cpu=2,hilos_interop=1,hilos_opencv=1)
        self.assertEqual(set(comparar(a,b)['variables_modificadas']),{'hilos_cpu','hilos_interop','hilos_opencv'})

    def test_v_rechaza_foto_previa_y_solicitud_iniciada_antes(self):
        captura=captura_svga(); estado=EstadoAdquisicion(captura,True,'',1,time.monotonic())
        adquisidor=Mock(); adquisidor.obtener_estado.return_value=estado
        gui=Visualizador(adquisidor,regiones_svga(),Mock(),'sin_archivo.json',1)
        gui.captura=captura; gui.tecla(ord('v')); gui.tecla(ord('1'))
        self.assertIsNone(gui.activa)
        vieja=replace(captura_svga(2),iniciada_monotonic=gui.invalidada_desde-1)
        adquisidor.obtener_estado.return_value=replace(estado,captura=vieja,secuencia=2)
        gui.tecla(ord('2')); self.assertIsNone(gui.activa)
        nueva=replace(captura_svga(3),iniciada_monotonic=gui.invalidada_desde+.01,recibida_monotonic=gui.invalidada_desde+.01)
        adquisidor.obtener_estado.return_value=replace(estado,captura=nueva,secuencia=3,confirmada_monotonic=time.monotonic())
        with patch('main.time.monotonic',return_value=gui.invalidada_desde+.02): gui.tecla(ord('1'))
        self.assertEqual(gui.activa,1)
        self.assertIs(gui.captura,nueva)
        # La congelación manual no rehabilita conteos y sí permite editar su geometría.
        gui.tecla(13)
        self.assertIsNone(gui.activa)
        gui.tecla(ord('2'))
        adquisidor.obtener_estado.return_value=replace(estado,captura=nueva,epoca=1)
        gui.tecla(13)
        self.assertEqual(gui.activa,2)  # Falla de conexión invalida confirmación restante.

    def test_exploracion_no_construye_conteo_operativo(self):
        extras=[dict(caja=[0,0,10,10],clase=0,nombre='person',confianza=.9),
                dict(caja=[20,0,30,10],clase=2,nombre='car',confianza=.05)]
        notas=hipotesis([],extras,.15)
        self.assertIn('hipotesis',notas[0]['hipotesis'])
        self.assertIn('umbral',notas[1]['hipotesis'])
        self.assertEqual(CONFIGURACIONES['E'],dict(imgsz=1280,confianza=.10,iou=.45))
        fila=dict(revision='actual',configuracion='A',sha256='foto',repeticion=0,
            parametros=PARAMETROS_INICIALES,detecciones=[])
        otra=deepcopy(fila);otra['configuracion']='B';otra['parametros']['confianza']=.10
        nms=deepcopy(fila);nms['parametros']['agnostic_nms']=True
        comparaciones=comparar_registros([fila,otra,nms])
        self.assertEqual({r['tipo'] for r in comparaciones},{'parametros','nms'})
