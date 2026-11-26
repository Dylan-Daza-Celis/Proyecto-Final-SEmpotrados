"""UDP PC -> C6: secuencia,N1,N2,valido. Sin solicitudes ni confirmaciones."""
from dataclasses import dataclass
import ipaddress
import json
from pathlib import Path
import re
import socket
import threading
import time

MAX_BYTES=48
MAX_SECUENCIA=2**64-1


def codificar(secuencia,n1,n2,valido):
    if (type(secuencia) is not int or not 1<=secuencia<=MAX_SECUENCIA or
            any(type(n) is not int or not 0<=n<=1000 for n in (n1,n2)) or
            type(valido) is not int or valido not in (0,1)):
        raise ValueError('Campos UDP fuera de rango')
    return f'{secuencia},{n1},{n2},{valido}'.encode('ascii')


def decodificar(datos):
    if not isinstance(datos,bytes) or not 7<=len(datos)<=MAX_BYTES:
        raise ValueError('Tamano UDP invalido')
    if not re.fullmatch(rb'[1-9][0-9]*,(?:0|[1-9][0-9]*),(?:0|[1-9][0-9]*),[01]',datos):
        raise ValueError('Se requieren cuatro enteros ASCII sin espacios')
    campos=tuple(map(int,datos.split(b',')))
    codificar(*campos)  # Mismos rangos al emitir y al leer en pruebas.
    return campos


@dataclass(frozen=True)
class Snapshot:
    valido:bool=False
    motivo:str='Sin resultado operativo'
    contexto:tuple=()
    identidad:tuple=()
    n1:int=0
    n2:int=0
    vence:float=0


class PreparadorEnvio:
    """Una foto se envia una vez. Los cambios de contexto emiten invalidacion primero."""
    def __init__(self):self.secuencia=0;self.anterior=None;self.ultima_identidad=None
    def mensaje(self,n1,n2,valido):
        self.secuencia+=1
        return codificar(self.secuencia,n1,n2,valido)
    def preparar(self,s,ahora):
        anterior=self.anterior;salida=[]
        vigente=s.valido and ahora<s.vence
        cambio=anterior is not None and s.contexto!=anterior.contexto
        caduco=anterior is not None and anterior.valido and ahora>=anterior.vence
        if not vigente:
            if anterior is None or anterior.valido or cambio or s.motivo!=anterior.motivo:
                salida.append(self.mensaje(0,0,0))
        else:
            if cambio or caduco:salida.append(self.mensaje(0,0,0))
            if s.identidad!=self.ultima_identidad:
                salida.append(self.mensaje(s.n1,s.n2,1));self.ultima_identidad=s.identidad
        self.anterior=s if vigente else Snapshot(motivo=s.motivo,contexto=s.contexto)
        return salida


def cargar_config(ruta):
    c=json.loads(Path(ruta).read_text(encoding='utf-8'))
    if not isinstance(c,dict) or set(c)!={'activo','ip_destino','puerto'} or type(c['activo']) is not bool:
        raise ValueError('UDP requiere solo activo, ip_destino y puerto; usar udp.emisor.example.json')
    if not isinstance(c['ip_destino'],str):raise ValueError('ip_destino debe ser texto IPv4')
    if type(c['puerto']) is not int or not 1<=c['puerto']<=65535:raise ValueError('Puerto UDP invalido')
    if c['activo'] or c['ip_destino']:
        ipaddress.IPv4Address(c['ip_destino'])
    return c


class EmisorUDP(threading.Thread):
    def __init__(self,config,proveedor):
        super().__init__(name='emisor_udp',daemon=False)
        self.destino=(config['ip_destino'],config['puerto']);self.proveedor=proveedor
        self.detener=threading.Event();self._mutex=threading.Lock();self.preparador=PreparadorEnvio()
        self.enviados=0;self.errores=0;self.ultimo_mensaje='';self.error=''
    def _enviar(self,conexion,datos):
        try:
            if conexion.sendto(datos,self.destino)!=len(datos):raise OSError('Envio incompleto')
            with self._mutex:
                self.enviados+=1;self.ultimo_mensaje=datos.decode('ascii');self.error=''
        except OSError:
            with self._mutex:self.errores+=1;self.error='Fallo local de envio UDP'
    def run(self):
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as conexion:
                conexion.settimeout(.2)
                while not self.detener.is_set():
                    snapshot=self.proveedor()
                    for datos in self.preparador.preparar(snapshot,time.monotonic()):self._enviar(conexion,datos)
                    self.detener.wait(.05)
                self._enviar(conexion,self.preparador.mensaje(0,0,0))
        except (OSError,ValueError):
            with self._mutex:self.errores+=1;self.error='Emisor UDP detenido por error local'
    def cerrar(self):self.detener.set()
    def obtener_estado(self):
        with self._mutex:
            return dict(activo=self.is_alive() and not self.detener.is_set(),destino=self.destino,
                        enviados=self.enviados,errores=self.errores,ultimo_mensaje=self.ultimo_mensaje,error=self.error)
