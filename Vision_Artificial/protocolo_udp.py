"""SE07 v1: cuerpo binario de 120 bytes + HMAC-SHA256 de 32 bytes."""
from dataclasses import dataclass
import hmac
import struct

HELLO, ASOCIACION, CONFIRMAR, CONSULTA, RESULTADO, INVALIDACION, ESPERA = range(1,8)
SIN_DATOS, CAMARA, INFERENCIA, PAUSA, CONTEXTO, EDAD, COMUNICACION = range(1,8)
SEGURO=7
CUERPO=struct.Struct('!4sBBBB16s16s16sQQQQQQIHHB3xI')
TAMANO=CUERPO.size+32
CERO=bytes(16)


@dataclass(frozen=True)
class Mensaje:
    tipo:int
    emisor:bytes
    sesion_emisor:bytes=CERO
    sesion_receptor:bytes=CERO
    epoca:int=0
    resultado:int=0
    evento:int=0
    nonce:int=0
    reconocimiento:int=0
    barrera:int=0
    edad_ms:int=0
    n1:int=0
    n2:int=0
    estado:int=SEGURO
    rtt_ms:int=0
    valido:bool=False
    motivo:int=0


def validar(m):
    if any(type(v) is not int for v in (m.tipo,m.motivo,m.estado,m.n1,m.n2)) or not 1<=m.tipo<=7 or type(m.valido) is not bool or not 0<=m.motivo<=7 or not 0<=m.estado<=7:
        raise ValueError('Tipo/estado/motivo UDP invalido')
    if any(not isinstance(v,bytes) or len(v)!=16 for v in (m.emisor,m.sesion_emisor,m.sesion_receptor)):
        raise ValueError('Identificadores UDP invalidos')
    if any(type(v) is not int or not 0<=v<2**64 for v in (m.epoca,m.resultado,m.evento,m.nonce,m.reconocimiento,m.barrera)):
        raise ValueError('Entero UDP fuera de rango')
    if any(type(v) is not int or not 0<=v<2**32 for v in (m.edad_ms,m.rtt_ms)) or not 0<=m.n1<=1000 or not 0<=m.n2<=1000:
        raise ValueError('Edad/conteo UDP fuera de rango')
    if m.valido != (m.tipo==RESULTADO) or (m.tipo!=RESULTADO and (m.n1 or m.n2)):
        raise ValueError('Conteos reservados para resultado valido')
    if m.tipo==RESULTADO and (not m.resultado or not m.evento or m.motivo):
        raise ValueError('Identidad de resultado invalida')


def codificar(m,clave):
    if len(clave)!=32:raise ValueError('Clave UDP requiere 32 bytes')
    validar(m)
    cuerpo=CUERPO.pack(b'SE07',1,m.tipo,int(m.valido),m.motivo,m.emisor,m.sesion_emisor,m.sesion_receptor,
        m.epoca,m.resultado,m.evento,m.nonce,m.reconocimiento,m.barrera,m.edad_ms,m.n1,m.n2,m.estado,m.rtt_ms)
    return cuerpo+hmac.digest(clave,cuerpo,'sha256')


def decodificar(datos,clave):
    if len(clave)!=32 or len(datos)!=TAMANO:raise ValueError('Tamano UDP incorrecto')
    if not hmac.compare_digest(hmac.digest(clave,datos[:120],'sha256'),datos[120:]):
        raise ValueError('Autenticacion UDP incorrecta')
    f=CUERPO.unpack(datos[:120])
    if f[0]!=b'SE07' or f[1]!=1 or f[3] not in (0,1) or datos[113:116]!=b'\0\0\0':
        raise ValueError('Formato UDP no compatible')
    m=Mensaje(f[2],*f[5:8],*f[8:14],*f[14:19],bool(f[3]),f[4])
    validar(m)
    return m
