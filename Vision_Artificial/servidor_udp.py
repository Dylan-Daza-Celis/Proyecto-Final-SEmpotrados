"""Servicio de último resultado; asociación e invalidación retenida, sin inferencia."""
from dataclasses import dataclass,replace
import json
import math
from pathlib import Path
import secrets
import socket
import threading
import time

from protocolo_udp import *


@dataclass(frozen=True)
class Snapshot:
    valido:bool=False
    motivo:int=SIN_DATOS
    contexto:tuple=()
    resultado:int=0
    epoca:int=0
    origen:float=0
    n1:int=0
    n2:int=0
    vence:float=float('inf')


class SesionServidor:
    """Una C6 asociada; resultados reemplazables y barrera retenida hasta ACK seguro."""
    def __init__(self,emisor,clave,max_edad_ms=12000,reloj=time.monotonic):
        self.emisor,self.clave,self.limite,self.reloj=emisor,clave,max_edad_ms,reloj
        self.sesion=secrets.token_bytes(16)
        self.activa=None;self.retiradas=set();self.candidata=None
        self.ultimo_nonce=0;self.generacion_cliente=0
        self.evento=1;self.invalidacion=1;self.barrera=1;self.pendiente=True
        self.motivo=SIN_DATOS;self.snapshot=Snapshot();self.firma=None
        self.posterior_a=float('inf');self.ultimo_resultado=0;self.identidad_observada=None
        self.ultimo_contacto=None
        self._mutex=threading.RLock()
        self.estado={'asociado':False,'solicitudes':0,'respuestas':0,'rechazados':0,'rtt_ms':None,'estado_c6':None,
                     'sesion':'','ultima_invalidacion':1}

    def _invalidar(self,motivo):
        self.evento+=1;self.invalidacion=self.evento;self.barrera=self.evento
        self.pendiente=True;self.motivo=motivo;self.posterior_a=float('inf')
        self.estado['ultima_invalidacion']=self.invalidacion

    def actualizar(self,s):
        with self._mutex:
            ahora=self.reloj()
            vencio_anterior=self.snapshot.valido and self.snapshot.vence<=ahora
            if s.valido and s.vence<=ahora:s=replace(s,valido=False,motivo=EDAD)
            cambio=self.firma is not None and s.contexto!=self.firma
            if cambio or vencio_anterior or (not s.valido and (self.snapshot.valido or s.motivo!=self.snapshot.motivo)):
                self._invalidar(EDAD if vencio_anterior else s.motivo if not s.valido else CONTEXTO)
            identidad=(s.epoca,s.resultado)
            if s.valido and identidad!=self.identidad_observada:
                self.evento+=1;self.identidad_observada=identidad
            self.snapshot=s;self.firma=s.contexto

    def procesar(self,datos):
        # Autenticar y validar antes de tocar asociación, secuencias o estado.
        m=decodificar(datos,self.clave)
        if m.emisor!=self.emisor or m.tipo not in (HELLO,CONFIRMAR,CONSULTA) or not m.nonce or m.sesion_receptor==CERO:
            raise ValueError('Solicitud no permitida')
        with self._mutex:
            ahora=self.reloj()
            self.estado['solicitudes']+=1
            base=Mensaje(ESPERA,self.emisor,self.sesion,m.sesion_receptor,nonce=m.nonce,barrera=self.barrera)
            if m.sesion_receptor in self.retiradas:raise ValueError('Sesion retirada')
            if m.tipo==HELLO:
                if m.sesion_emisor!=CERO:raise ValueError('HELLO debe descubrir sesion')
                if m.sesion_receptor==self.activa and m.nonce<=self.ultimo_nonce:raise ValueError('Nonce repetido')
                if self.candidata and m.sesion_receptor==self.candidata[0] and m.nonce<=self.candidata[3]:
                    raise ValueError('Desafio repetido')
                token=secrets.randbits(64) or 1
                self.candidata=(m.sesion_receptor,token,ahora+3,m.nonce)
                respuesta=replace(base,tipo=ASOCIACION,barrera=token)
            elif m.tipo==CONFIRMAR:
                c=self.candidata
                if m.sesion_emisor!=self.sesion or not c or (m.sesion_receptor,m.barrera)!=(c[0],c[1]) or ahora>c[2] or m.nonce<=c[3]:
                    raise ValueError('Asociacion no confirmada')
                if self.activa and self.activa!=m.sesion_receptor:
                    if len(self.retiradas)>=64:raise ValueError('Reiniciar servidor para mas sesiones')
                    self.retiradas.add(self.activa)
                self.activa=m.sesion_receptor;self.candidata=None;self.ultimo_nonce=m.nonce
                self.generacion_cliente=m.evento;self.ultimo_resultado=0
                self._invalidar(CONTEXTO)
                respuesta=replace(base,tipo=INVALIDACION,evento=self.invalidacion,barrera=self.barrera,motivo=self.motivo)
                self.estado.update(asociado=True,sesion=self.activa.hex()[:8])
            else:
                if m.sesion_emisor!=self.sesion or m.sesion_receptor!=self.activa or m.nonce<=self.ultimo_nonce:
                    raise ValueError('Sesion/nonce no vigente')
                if m.evento<self.generacion_cliente:raise ValueError('Generacion de receptor antigua')
                self.ultimo_nonce=m.nonce
                self.estado.update(rtt_ms=m.rtt_ms,estado_c6=m.estado)
                if m.evento>self.generacion_cliente:
                    self.generacion_cliente=m.evento;self._invalidar(COMUNICACION)
                if self.pendiente and m.reconocimiento==self.invalidacion and m.estado==SEGURO:
                    self.pendiente=False;self.posterior_a=ahora
                s=self.snapshot
                if self.pendiente:
                    respuesta=replace(base,tipo=INVALIDACION,evento=self.invalidacion,barrera=self.barrera,motivo=self.motivo)
                elif (s.valido and s.origen>self.posterior_a and s.resultado>self.ultimo_resultado):
                    edad=math.ceil(max(0,ahora-s.origen)*1000)
                    if edad>=self.limite:
                        self._invalidar(EDAD)
                        respuesta=replace(base,tipo=INVALIDACION,evento=self.invalidacion,barrera=self.barrera,motivo=EDAD)
                    else:
                        # Los reenvíos del mismo resultado se responden como ESPERA, sin renovar TTL.
                        self.ultimo_resultado=s.resultado
                        respuesta=replace(base,tipo=RESULTADO,valido=True,epoca=s.epoca,resultado=s.resultado,
                            evento=self.evento,barrera=self.barrera,edad_ms=edad,n1=s.n1,n2=s.n2)
                else:respuesta=replace(base,barrera=self.barrera)
            self.estado['respuestas']+=1
            if m.tipo in (CONFIRMAR,CONSULTA):self.ultimo_contacto=ahora
            return codificar(respuesta,self.clave)

    def obtener_estado(self):
        with self._mutex:
            edad=None if self.ultimo_contacto is None else max(0,self.reloj()-self.ultimo_contacto)
            return dict(self.estado)|{'asociado':self.estado['asociado'] and edad is not None and edad<3,
                                      'edad_reporte_s':edad}


class ServidorUDP(threading.Thread):
    def __init__(self,config,proveedor):
        super().__init__(name='servicio_udp',daemon=False)
        self.config=config;self.proveedor=proveedor;self.detener=threading.Event();self.iniciado=threading.Event()
        self.sesion=SesionServidor(config['emisor'],config['clave'],config['max_edad_ms'])
        self.error='';self.direccion=None

    def run(self):
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as conexion:
                conexion.bind((self.config['direccion'],self.config['puerto']));conexion.settimeout(.05)
                self.direccion=conexion.getsockname();self.iniciado.set()
                while not self.detener.is_set():
                    self.sesion.actualizar(self.proveedor())
                    try:datos,remoto=conexion.recvfrom(513)
                    except socket.timeout:continue
                    try:
                        self.sesion.actualizar(self.proveedor())
                        conexion.sendto(self.sesion.procesar(datos),remoto)
                    except ValueError:
                        with self.sesion._mutex:self.sesion.estado['rechazados']+=1
        except (OSError,ValueError):self.error='Servicio UDP no disponible; revisar configuracion local'
        finally:self.iniciado.set()

    def cerrar(self):self.detener.set()

    def obtener_estado(self):
        return self.sesion.obtener_estado()|{'activo':self.is_alive() and not self.error,'error':self.error,'direccion':self.direccion}


def cargar_config_udp(ruta):
    ruta=Path(ruta).resolve();c=json.loads(ruta.read_text(encoding='utf-8'))
    clave=bytes.fromhex((ruta.parent/c['archivo_clave']).read_text(encoding='ascii').strip())
    emisor=bytes.fromhex(c['emisor_id'])
    if len(clave)!=32 or len(emisor)!=16 or emisor==CERO:raise ValueError('Clave/identidad UDP local invalida')
    puerto=c.get('puerto',5005);limite=c.get('max_edad_ms',12000)
    if type(puerto) is not int or not 1<=puerto<=65535 or type(limite) is not int or not 100<=limite<=60000:
        raise ValueError('Puerto/presupuesto UDP invalido')
    direccion=c.get('direccion','0.0.0.0');socket.inet_aton(direccion)
    return dict(clave=clave,emisor=emisor,direccion=direccion,puerto=puerto,max_edad_ms=limite)
