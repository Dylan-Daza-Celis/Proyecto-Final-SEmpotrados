"""HTTP secuencial y adquisición en segundo plano; no utiliza VideoCapture."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import threading
import time
from urllib.parse import urlsplit

import cv2
import numpy as np
import requests


class ErrorCamara(RuntimeError):
    """Error recuperable de transporte, contrato HTTP o decodificación."""


def normalizar_url(direccion: str) -> str:
    if not isinstance(direccion, str):
        raise ValueError("url_base debe ser texto.")
    direccion = direccion.strip()
    if not direccion:
        raise ValueError("Configure url_base en config.json o use --url.")
    if "://" not in direccion:
        direccion = "http://" + direccion
    partes = urlsplit(direccion)
    try:
        puerto = partes.port
    except ValueError as error:
        raise ValueError("Puerto de cámara inválido.") from error
    if (partes.scheme not in ("http", "https") or not partes.hostname or
            partes.username or partes.password or partes.query or partes.fragment or
            partes.path not in ("", "/") or puerto == 0):
        raise ValueError("Use una URL base sin credenciales, rutas, consultas ni fragmentos.")
    return direccion.rstrip("/")


@dataclass(frozen=True)
class Captura:
    jpeg: bytes
    imagen: np.ndarray
    identificador: str | None
    fecha_utc: str
    recibida_monotonic: float
    recepcion_s: float
    decodificacion_s: float
    calidad_reportada: int | None = None
    estado_reportado: dict | None = None


class ClienteCamara:
    """Una sesión por hilo. Los reintentos y el tamaño de las respuestas son finitos."""

    def __init__(self, url_base: str, timeout_conexion_s=3.0, timeout_lectura_s=15.0,
                 reintentos=2, pausa_reintento_s=1.0, detener=None, sesion=None):
        self.url_base = normalizar_url(url_base)
        self.timeout = (timeout_conexion_s, timeout_lectura_s)
        self.reintentos = reintentos
        self.pausa = pausa_reintento_s
        self.detener = detener if detener is not None else threading.Event()
        self.sesion = sesion if sesion is not None else requests.Session()
        # La cámara está en la LAN: no enviar consultas a proxies del entorno.
        self.sesion.trust_env = False

    def cerrar(self):
        self.sesion.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrar()

    def _solicitar(self, ruta, tipo, limite):
        ultimo_error = None
        for intento in range(self.reintentos + 1):
            if self.detener.is_set():
                raise ErrorCamara("Adquisición detenida.")
            inicio = time.perf_counter()
            try:
                with self.sesion.get(self.url_base + ruta, timeout=self.timeout,
                                     headers={"Cache-Control": "no-cache", "Accept": tipo},
                                     stream=True, allow_redirects=False) as respuesta:
                    if respuesta.status_code != 200:
                        raise ErrorCamara(f"HTTP {respuesta.status_code} en {ruta}.")
                    contenido_tipo = respuesta.headers.get("Content-Type", "").split(";")[0].strip().lower()
                    if contenido_tipo != tipo:
                        raise ErrorCamara(f"Content-Type inesperado en {ruta}: {contenido_tipo!r}.")
                    contenido = bytearray()
                    # Requests limita inactividad por lectura; añadimos comprobación
                    # de tiempo total entre bloques para una respuesta que llega a gotas.
                    for bloque in respuesta.iter_content(chunk_size=16384):
                        if self.detener.is_set():
                            raise ErrorCamara("Adquisición detenida.")
                        if time.perf_counter() - inicio > sum(self.timeout):
                            raise ErrorCamara("Tiempo total de recepción agotado.")
                        contenido.extend(bloque)
                        if len(contenido) > limite:
                            raise ErrorCamara("Respuesta HTTP demasiado grande.")
                    return bytes(contenido), respuesta.headers.get("X-Capture-Id"), time.perf_counter() - inicio
            except (requests.RequestException, ErrorCamara) as error:
                # No imprimir URL/errores crudos de Requests: pueden contener datos locales.
                ultimo_error = error if isinstance(error, ErrorCamara) else ErrorCamara(
                    "Timeout de cámara." if isinstance(error, requests.Timeout) else "Error de conexión HTTP.")
                if intento < self.reintentos and not self.detener.wait(self.pausa * (intento + 1)):
                    continue
                break
        raise ErrorCamara(str(ultimo_error)) from ultimo_error

    def consultar_estado(self):
        contenido, _, _ = self._solicitar("/status", "application/json", 65536)
        try:
            estado = json.loads(contenido)
        except (ValueError, UnicodeDecodeError) as error:
            raise ErrorCamara("/status no contiene JSON válido.") from error
        if (not isinstance(estado, dict) or type(estado.get("camera_ready")) is not bool or
                not isinstance(estado.get("sensor"), str)):
            raise ErrorCamara("/status no respeta el contrato de cámara.")
        return estado

    def capturar(self, estado=None):
        contenido, identificador, recepcion_s = self._solicitar("/capture", "image/jpeg", 5 * 1024 * 1024)
        if len(contenido) < 4 or not contenido.startswith(b"\xff\xd8") or not contenido.endswith(b"\xff\xd9"):
            raise ErrorCamara("JPEG incompleto: faltan SOI/EOI.")
        inicio = time.perf_counter()
        try:
            imagen = cv2.imdecode(np.frombuffer(contenido, dtype=np.uint8), cv2.IMREAD_COLOR)
        except cv2.error as error:
            raise ErrorCamara("OpenCV rechazó el JPEG.") from error
        if imagen is None or imagen.ndim != 3 or imagen.shape[2] != 3 or imagen.size == 0:
            raise ErrorCamara("El contenido no se puede decodificar como fotografía.")
        decodificacion_s = time.perf_counter() - inicio
        imagen.setflags(write=False)  # Las anotaciones se dibujan siempre en una copia.
        calidad = None
        if estado and (estado.get("width"), estado.get("height")) == (imagen.shape[1], imagen.shape[0]):
            valor = estado.get("quality")
            if type(valor) is int and 10 <= valor <= 40:
                calidad = valor
        return Captura(contenido, imagen, identificador, datetime.now(timezone.utc).isoformat(),
                       time.monotonic(), recepcion_s, decodificacion_s, calidad,
                       dict(estado) if estado is not None else None)


@dataclass(frozen=True)
class EstadoAdquisicion:
    captura: Captura | None = None
    conectado: bool = False
    mensaje: str = "Esperando cámara"
    secuencia: int = 0
    confirmada_monotonic: float = 0.0
    frecuencia_hz: float = 0.0


class Adquisidor(threading.Thread):
    """Buzón de una imagen; solo este hilo posee y usa la sesión HTTP."""

    def __init__(self, url_base, configuracion, fabrica_cliente=ClienteCamara):
        super().__init__(name="adquisicion_http", daemon=False)
        self.url_base = url_base
        self.configuracion = configuracion
        self.fabrica_cliente = fabrica_cliente
        self.detener = threading.Event()
        self.pausado = threading.Event()
        self._mutex = threading.Lock()
        self._estado = EstadoAdquisicion()

    def obtener_estado(self):
        with self._mutex:
            return self._estado

    def _publicar(self, **cambios):
        with self._mutex:
            self._estado = replace(self._estado, **cambios)

    def run(self):
        anterior = None
        try:
            with self.fabrica_cliente(self.url_base, detener=self.detener, **{
                    clave: self.configuracion[clave] for clave in (
                        "timeout_conexion_s", "timeout_lectura_s", "reintentos", "pausa_reintento_s")}) as cliente:
                while not self.detener.is_set():
                    inicio = time.monotonic()
                    try:
                        estado = cliente.consultar_estado()
                        if not estado["camera_ready"]:
                            raise ErrorCamara("La cámara informa camera_ready=false.")
                        self._publicar(conectado=True, mensaje="Conectado",
                                       confirmada_monotonic=time.monotonic())
                        if not self.pausado.is_set():
                            captura = cliente.capturar(estado)
                            frecuencia = 0.0 if anterior is None else 1 / max(captura.recibida_monotonic - anterior, 1e-6)
                            anterior = captura.recibida_monotonic
                            actual = self.obtener_estado()
                            self._publicar(captura=captura, secuencia=actual.secuencia + 1,
                                           conectado=True, mensaje="Imagen recibida",
                                           confirmada_monotonic=time.monotonic(), frecuencia_hz=frecuencia)
                    except ErrorCamara as error:
                        self._publicar(conectado=False, mensaje=str(error), frecuencia_hz=0.0)
                        anterior = None
                    intervalo = self.configuracion["intervalo_captura_s"]
                    self.detener.wait(max(0.05, intervalo - (time.monotonic() - inicio)))
        except Exception as error:
            self._publicar(conectado=False, mensaje=f"Adquisición detenida: {type(error).__name__}")
