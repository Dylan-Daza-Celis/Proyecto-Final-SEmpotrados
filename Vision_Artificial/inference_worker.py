"""Un trabajador YOLO y un buzón pendiente reemplazable; no hay cola ilimitada."""
from dataclasses import dataclass, replace
import threading
import time
import numpy as np

from contador_vehiculos import Conteo, FiltroMediana, contar_vehiculos
from detector_vehiculos import DetectorVehiculos


@dataclass(frozen=True)
class ResultadoInferencia:
    captura: object
    secuencia: int
    detecciones: tuple
    instantaneo: Conteo | None
    filtrado: Conteo | None
    muestras_validas: int
    inferencia_s: float
    finalizada_monotonic: float
    latencia_total_s: float
    modelo: str
    contexto: tuple
    generacion: int

    def a_dict(self, valido, motivo=""):
        """Estructura local para futura integración; no envía UDP ni otros mensajes."""
        valido=bool(valido and self.instantaneo is not None)
        return {"valido": valido, "motivo": motivo, "secuencia": self.secuencia,
                "identificador": self.captura.identificador, "fecha_utc": self.captura.fecha_utc,
                "instantaneo": self.instantaneo.a_dict() if valido else None,
                "filtrado": self.filtrado.a_dict() if valido else None,
                "referencia_visual": self.instantaneo.a_dict() if self.instantaneo is not None else None,
                "total_detecciones":len(self.detecciones),"muestras_validas": self.muestras_validas if valido else 0,
                "inferencia_s": self.inferencia_s, "latencia_total_s": self.latencia_total_s,
                "edad_al_utilizar_s": time.monotonic() - self.captura.origen_monotonic,
                "referencia_temporal": "inicio de solicitud HTTP; no timestamp del sensor", "modelo": self.modelo}


@dataclass(frozen=True)
class EstadoInferencia:
    resultado: ResultadoInferencia | None
    error: str
    motivo: str
    procesando: int | None
    omitidos: int
    frecuencia_hz: float
    generacion: int
    fallos: int = 0


class TrabajadorInferencia(threading.Thread):
    def __init__(self, parametros, max_antiguedad_s=12.0, filtro=True, fabrica_detector=DetectorVehiculos, calentamiento=0):
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
        self._fallos = 0
        self.calentamiento = calentamiento
        self._preparando = bool(calentamiento)
        self._no_antes = 0.0
        self._fase_preparacion = 'CARGANDO MODELO'

    def _reiniciar_filtro(self):
        self._filtro.reiniciar()
        self._tiempos_muestras.clear()
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
                self._ultimo_fin = None
                self._frecuencia = 0.0
            self._suspendido = True
            self._motivo = motivo

    def enviar(self, captura, secuencia, regiones, epoca=0):
        contexto = (regiones.firma(), epoca)
        with self._condicion:
            if captura.origen_monotonic < self._no_antes:
                return False
            if contexto != self._contexto or self._suspendido:
                self._generacion += 1
                self._contexto = contexto
                if self._pendiente is not None:
                    self._omitidos += 1
                self._pendiente = None
                self._suspendido = False
                self._reiniciar_filtro()
                self._ultimo_fin = None
                self._frecuencia = 0.0
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
            if self._filtro.habilitado and any(time.monotonic() - t > self.limite for t in self._tiempos_muestras):
                self._reiniciar_filtro()
            return EstadoInferencia(self._resultado, self._error, self._fase_preparacion if self._preparando else self._motivo,
                                    self._procesando, self._omitidos, self._frecuencia, self._generacion, self._fallos)

    def cerrar(self):
        self.detener.set()
        with self._condicion:
            self._pendiente = None
            self._condicion.notify_all()

    def run(self):
        try:
            detector = self.fabrica_detector(self.parametros)  # Una sola carga, dentro del trabajador.
            if self.calentamiento:
                with self._condicion:
                    self._fase_preparacion = 'CALENTANDO MODELO'
                detector.calentar(self.calentamiento, self.detener)
                with self._condicion:
                    self._no_antes = time.monotonic()
                    if self._pendiente is not None:
                        self._omitidos += 1
                    self._pendiente = None
                    self._motivo = 'Inferencia pendiente: esperando captura posterior al calentamiento'
            with self._condicion:
                self._preparando = False
        except Exception as error:
            with self._condicion:
                self._error = f"Error al cargar modelo: {error}"
                self._fallos += 1
                self._motivo = "Error de inferencia"
                self._preparando = False
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
                if time.monotonic() - captura.origen_monotonic > self.limite:
                    raise ValueError("Imagen antigua antes de inferir")
                resolucion = (captura.imagen.shape[1], captura.imagen.shape[0])
                if resolucion != (800, 600):
                    raise ValueError("Configurar SVGA 800x600 desde la interfaz web")
                detecciones, segundos = detector.detectar(captura.imagen)
                # YOLO reconoce aunque falten ROI. El conteo operativo exige calibracion.
                conteo = None if regiones.estado_calibracion(resolucion) else contar_vehiculos(detecciones, regiones, resolucion)
                final = time.monotonic()
                with self._condicion:
                    self._procesando = None
                    if generacion != self._generacion or self.detener.is_set():
                        self._omitidos += 1
                        continue
                    if final - captura.origen_monotonic > self.limite:
                        self._fallos += 1
                        self._motivo = "Resultado neuronal antiguo"
                        self._reiniciar_filtro()
                        continue
                    if self._filtro.habilitado and any(final - t > self.limite for t in self._tiempos_muestras):
                        self._reiniciar_filtro()
                    if conteo is None:
                        self._reiniciar_filtro();filtrado=None;muestras=0
                    else:
                        filtrado,muestras=self._filtro.agregar(secuencia,conteo)
                    if self._filtro.habilitado and conteo is not None:
                        self._tiempos_muestras = (self._tiempos_muestras + [captura.origen_monotonic])[-3:]
                    self._frecuencia = 0.0 if self._ultimo_fin is None else 1 / max(final - self._ultimo_fin, 1e-6)
                    self._ultimo_fin = final
                    self._resultado = ResultadoInferencia(captura, secuencia, detecciones, conteo, filtrado,
                        muestras, segundos, final, final - captura.origen_monotonic,
                        self.parametros.get('backend', 'pytorch') + ': ' + str(self.parametros["pesos"]), contexto, generacion)
                    self._error = ""
                    self._motivo = ""
            except Exception as error:
                with self._condicion:
                    self._procesando = None
                    if generacion == self._generacion:
                        self._fallos += 1
                        self._error = f"Error de inferencia: {error}"
                        self._motivo = "Error de inferencia"
                        self._reiniciar_filtro()


def motivo_deteccion(estado,captura_actual,max_imagen_s,pausado=False,activado=True,ahora=None):
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
    return ""


def motivo_entrada(estado, captura_actual, regiones, max_imagen_s, pausado=False, activado=True, ahora=None):
    """Entrada OPERATIVA: deteccion disponible y ademas ambas ROI validas."""
    motivo=motivo_deteccion(estado,captura_actual,max_imagen_s,pausado,activado,ahora)
    if motivo:return motivo
    return regiones.estado_calibracion((captura_actual.imagen.shape[1],captura_actual.imagen.shape[0]))


def motivo_diagnostico(estado,captura_actual,estado_ia,max_imagen_s,max_resultado_s,pausado=False,activado=True,ahora=None):
    ahora=time.monotonic() if ahora is None else ahora
    motivo=motivo_deteccion(estado,captura_actual,max_imagen_s,pausado,activado,ahora)
    if motivo:return motivo
    if estado_ia.error:return estado_ia.error
    resultado=estado_ia.resultado
    if resultado is None:return estado_ia.motivo or 'Esperando reconocimiento'
    if resultado.generacion!=estado_ia.generacion or resultado.contexto[1]!=estado.epoca:
        return 'Reconocimiento pendiente: contexto cambiado'
    if not 0<=ahora-resultado.captura.origen_monotonic<=max_resultado_s:return 'Reconocimiento antiguo'
    return estado_ia.motivo


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
    if not 0 <= ahora - resultado.captura.origen_monotonic <= max_resultado_s:
        return "Resultado neuronal antiguo"
    if estado_ia.motivo:
        return estado_ia.motivo
    if resultado.instantaneo is None:return 'Calibracion pendiente; solo reconocimiento diagnostico'
    return ""
