"""Un trabajador YOLO y un buzón pendiente reemplazable; no hay cola ilimitada."""
from dataclasses import dataclass, replace
import threading
import time

from contador_vehiculos import Conteo, FiltroMediana, contar_vehiculos
from detector_vehiculos import DetectorVehiculos


@dataclass(frozen=True)
class ResultadoInferencia:
    captura: object
    secuencia: int
    detecciones: tuple
    instantaneo: Conteo
    filtrado: Conteo
    muestras_validas: int
    inferencia_s: float
    finalizada_monotonic: float
    latencia_total_s: float
    modelo: str
    contexto: tuple
    generacion: int

    def a_dict(self, valido, motivo=""):
        """Estructura local para futura integración; no envía UDP ni otros mensajes."""
        return {"valido": valido, "motivo": motivo, "secuencia": self.secuencia,
                "identificador": self.captura.identificador, "fecha_utc": self.captura.fecha_utc,
                "instantaneo": self.instantaneo.a_dict() if valido else None,
                "filtrado": self.filtrado.a_dict() if valido else None,
                "referencia_visual": self.instantaneo.a_dict(), "muestras_validas": self.muestras_validas if valido else 0,
                "inferencia_s": self.inferencia_s, "latencia_total_s": self.latencia_total_s, "modelo": self.modelo}


@dataclass(frozen=True)
class EstadoInferencia:
    resultado: ResultadoInferencia | None
    error: str
    motivo: str
    procesando: int | None
    omitidos: int
    frecuencia_hz: float
    generacion: int


class TrabajadorInferencia(threading.Thread):
    def __init__(self, parametros, max_antiguedad_s=30.0, filtro=True, fabrica_detector=DetectorVehiculos):
        super().__init__(name="inferencia_yolo", daemon=False)
        self.parametros = dict(parametros)
        self.limite = max_antiguedad_s
        self.fabrica_detector = fabrica_detector
        self.detener = threading.Event()
        self._condicion = threading.Condition()
        self._pendiente = None
        self._resultado = None
        self._contexto = None
        self._generacion = 0
        self._ultima_secuencia = -1
        self._omitidos = 0
        self._procesando = None
        self._error = ""
        self._motivo = "Cargando modelo"
        self._suspendido = False
        self._frecuencia = 0.0
        self._ultimo_fin = None
        self._filtro = FiltroMediana(filtro)
        self._tiempos_muestras = []

    def _reiniciar_filtro(self):
        self._filtro.reiniciar()
        self._tiempos_muestras.clear()
        self._ultimo_fin = None
        self._frecuencia = 0.0
        if self._resultado is not None:
            # Una mediana publicada tampoco debe conservar muestras caducadas.
            self._resultado = replace(self._resultado, filtrado=self._resultado.instantaneo, muestras_validas=0)

    def suspender(self, motivo):
        with self._condicion:
            if not self._suspendido or motivo != self._motivo:
                self._generacion += 1
                if self._pendiente is not None:
                    self._omitidos += 1
                self._pendiente = None
                self._reiniciar_filtro()
            self._suspendido = True
            self._motivo = motivo

    def enviar(self, captura, secuencia, regiones, epoca=0):
        contexto = (regiones.firma(), epoca)
        with self._condicion:
            if contexto != self._contexto or self._suspendido:
                self._generacion += 1
                self._contexto = contexto
                if self._pendiente is not None:
                    self._omitidos += 1
                self._pendiente = None
                self._suspendido = False
                self._reiniciar_filtro()
                self._motivo = "Inferencia pendiente"
            if secuencia <= self._ultima_secuencia or self.detener.is_set():
                return False
            if self._ultima_secuencia >= 0:
                self._omitidos += max(0, secuencia - self._ultima_secuencia - 1)
            if self._pendiente is not None:
                self._omitidos += 1
            self._ultima_secuencia = secuencia
            self._pendiente = (captura, secuencia, regiones.copiar(), contexto, self._generacion)
            self._condicion.notify_all()
            return True

    def obtener_estado(self):
        with self._condicion:
            if any(time.monotonic() - t > self.limite for t in self._tiempos_muestras):
                self._reiniciar_filtro()
            return EstadoInferencia(self._resultado, self._error, self._motivo,
                                    self._procesando, self._omitidos, self._frecuencia, self._generacion)

    def cerrar(self):
        self.detener.set()
        with self._condicion:
            self._pendiente = None
            self._condicion.notify_all()

    def run(self):
        try:
            detector = self.fabrica_detector(self.parametros)  # Una sola carga, dentro del trabajador.
        except Exception as error:
            with self._condicion:
                self._error = f"Error al cargar modelo: {error}"
                self._motivo = "Error de inferencia"
            return
        while not self.detener.is_set():
            with self._condicion:
                while self._pendiente is None and not self.detener.is_set():
                    self._condicion.wait(timeout=0.2)
                if self.detener.is_set():
                    break
                captura, secuencia, regiones, contexto, generacion = self._pendiente
                self._pendiente = None
                self._procesando = secuencia
            try:
                if time.monotonic() - captura.recibida_monotonic > self.limite:
                    raise ValueError("Imagen antigua antes de inferir")
                resolucion = (captura.imagen.shape[1], captura.imagen.shape[0])
                if resolucion != (800, 600):
                    raise ValueError("Configurar SVGA 800x600 desde la interfaz web")
                detecciones, segundos = detector.detectar(captura.imagen)
                conteo = contar_vehiculos(detecciones, regiones, resolucion)
                final = time.monotonic()
                with self._condicion:
                    self._procesando = None
                    if generacion != self._generacion or self.detener.is_set():
                        self._omitidos += 1
                        continue
                    if final - captura.recibida_monotonic > self.limite:
                        self._motivo = "Resultado neuronal antiguo"
                        self._reiniciar_filtro()
                        continue
                    if any(final - t > self.limite for t in self._tiempos_muestras):
                        self._reiniciar_filtro()
                    filtrado, muestras = self._filtro.agregar(secuencia, conteo)
                    self._tiempos_muestras = (self._tiempos_muestras + [captura.recibida_monotonic])[-3:]
                    self._frecuencia = 0.0 if self._ultimo_fin is None else 1 / max(final - self._ultimo_fin, 1e-6)
                    self._ultimo_fin = final
                    self._resultado = ResultadoInferencia(captura, secuencia, detecciones, conteo, filtrado,
                        muestras, segundos, final, final - captura.recibida_monotonic,
                        str(self.parametros["pesos"]), contexto, generacion)
                    self._error = ""
                    self._motivo = ""
            except Exception as error:
                with self._condicion:
                    self._procesando = None
                    if generacion == self._generacion:
                        self._error = f"Error de inferencia: {error}"
                        self._motivo = "Error de inferencia"
                        self._reiniciar_filtro()


def motivo_entrada(estado, captura_actual, regiones, max_imagen_s, pausado=False, activado=True, ahora=None):
    from camera_client import captura_vigente
    ahora = time.monotonic() if ahora is None else ahora
    if not activado:
        return "Deteccion desactivada"
    if pausado:
        return "Imagen pausada / calibrando ROI"
    if not estado.conectado:
        return "Camara desconectada"
    if estado.error_captura:
        return "Captura invalida"
    if captura_actual is None:
        return "Inferencia pendiente: sin imagen"
    if not captura_vigente(estado, captura_actual, max_imagen_s, ahora):
        return "Imagen antigua"
    resolucion = (captura_actual.imagen.shape[1], captura_actual.imagen.shape[0])
    if resolucion != (800, 600):
        return "Configurar SVGA 800x600 desde la interfaz web"
    motivo = regiones.estado_calibracion(resolucion)
    if motivo:
        return motivo
    return ""


def motivo_resultado(estado, captura_actual, regiones, estado_ia, max_imagen_s, max_resultado_s,
                     pausado=False, activado=True, ahora=None):
    """Nunca convertir un fallo o ausencia de resultado en un conteo cero válido."""
    ahora = time.monotonic() if ahora is None else ahora
    motivo = motivo_entrada(estado, captura_actual, regiones, max_imagen_s, pausado, activado, ahora)
    if motivo:
        return motivo
    if estado_ia.error:
        return estado_ia.error
    resultado = estado_ia.resultado
    if resultado is None:
        return estado_ia.motivo or "Inferencia pendiente"
    if (resultado.generacion != estado_ia.generacion or
            resultado.contexto != (regiones.firma(), estado.epoca)):
        return "Inferencia pendiente: contexto cambiado"
    if not 0 <= ahora - resultado.captura.recibida_monotonic <= max_resultado_s:
        return "Resultado neuronal antiguo"
    if estado_ia.motivo:
        return estado_ia.motivo
    return ""
