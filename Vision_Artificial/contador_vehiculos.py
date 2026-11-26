"""Ocupación por fotografía, sin tracking ni acumulación entre imágenes."""
from collections import deque
from dataclasses import asdict, dataclass
import statistics

from detector_vehiculos import ErrorDeteccion


@dataclass(frozen=True)
class Conteo:
    n1: int
    n2: int
    n_fuera: int

    @property
    def n_total(self):
        return self.n1 + self.n2 + self.n_fuera

    @property
    def diferencia(self):
        return self.n1 - self.n2

    def a_dict(self):
        return asdict(self) | {"n_total": self.n_total, "diferencia": self.diferencia}


def asignar_roi(deteccion, regiones, resolucion):
    """Una única pertenencia, usando el centro flotante original, incluido el borde."""
    deteccion.validar(resolucion)
    primero = regiones.contiene_punto(1, deteccion.centro, resolucion)
    segundo = regiones.contiene_punto(2, deteccion.centro, resolucion)
    if primero and segundo:
        raise ErrorDeteccion("Centro asignado a dos ROI: calibración ambigua.")
    return 'ROI1' if primero else 'ROI2' if segundo else 'FUERA'


def contar_vehiculos(detecciones, regiones, resolucion):
    motivo = regiones.estado_calibracion(resolucion)
    if motivo:
        raise ValueError(motivo)
    cantidades = [0, 0, 0]
    for deteccion in detecciones:
        categoria = asignar_roi(deteccion, regiones, resolucion)
        cantidades[{'ROI1':0,'ROI2':1,'FUERA':2}[categoria]] += 1
    return Conteo(*cantidades)


class FiltroMediana:
    def __init__(self, habilitado=True):
        self.habilitado = habilitado
        self.reiniciar()

    def reiniciar(self):
        self.muestras = deque(maxlen=3)
        self.ultima_secuencia = -1

    def agregar(self, secuencia, conteo):
        if secuencia <= self.ultima_secuencia:
            raise ValueError("El filtro solo acepta secuencias nuevas.")
        self.ultima_secuencia = secuencia
        if not self.habilitado:
            return conteo, 0
        self.muestras.append(conteo)
        if len(self.muestras) < 3:
            return conteo, len(self.muestras)
        salida = Conteo(*(int(statistics.median(getattr(m, clave) for m in self.muestras))
                          for clave in ("n1", "n2", "n_fuera")))
        return salida, len(self.muestras)
