"""Adaptador YOLO11x: carga local única, BGR y cajas en la fotografía original."""
from dataclasses import dataclass
import math
from pathlib import Path
import time

import numpy as np

CLASES_COCO = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
PARAMETROS_INICIALES = dict(pesos="yolo11x.pt", dispositivo="cpu", imgsz=960,
                           confianza=0.15, iou=0.45, clases=[2, 3, 5, 7], agnostic_nms=False,
                           backend="pytorch", modelo_exportado="", hilos_cpu=0, hilos_interop=0, hilos_opencv=0)


class ErrorDeteccion(RuntimeError):
    pass


def validar_parametros(parametros):
    if not isinstance(parametros, dict) or set(parametros) - set(PARAMETROS_INICIALES):
        raise ValueError("Parámetros neuronales desconocidos.")
    salida = PARAMETROS_INICIALES | parametros
    if salida['backend'] not in ('pytorch', 'onnx', 'openvino'):
        raise ValueError('Backend desconocido; no se sustituye automáticamente.')
    for clave in ('hilos_cpu', 'hilos_interop', 'hilos_opencv'):
        if type(salida[clave]) is not int or not 0 <= salida[clave] <= 64:
            raise ValueError(f'{clave}: entero 0..64; 0 conserva el valor original.')
    if not isinstance(salida['modelo_exportado'], (str, Path)):
        raise ValueError('modelo_exportado debe ser una ruta local.')
    if type(salida["agnostic_nms"]) is not bool:
        raise ValueError("agnostic_nms debe ser booleano.")
    for clave in ("confianza", "iou"):
        if (isinstance(salida[clave], bool) or not isinstance(salida[clave], (float, int)) or
                not math.isfinite(salida[clave]) or not 0 < salida[clave] <= 1):
            raise ValueError(f"{clave} debe estar en (0, 1].")
    if type(salida["imgsz"]) is not int or not 32 <= salida["imgsz"] <= 2048 or salida["imgsz"] % 32:
        raise ValueError("imgsz debe ser múltiplo de 32 entre 32 y 2048.")
    clases = salida["clases"]
    if (not isinstance(clases, list) or not clases or
            any(type(c) is not int or c not in CLASES_COCO for c in clases) or len(set(clases)) != len(clases)):
        raise ValueError("clases debe ser una selección sin duplicados de 2, 3, 5, 7.")
    if not isinstance(salida["dispositivo"], str) or not salida["dispositivo"].strip():
        raise ValueError("Dispositivo neuronal vacío.")
    if not isinstance(salida["pesos"], (str, Path)) or not str(salida["pesos"]).strip():
        raise ValueError("Indique una ruta local a yolo11x.pt.")
    return salida


@dataclass(frozen=True)
class Deteccion:
    caja: tuple[float, float, float, float]
    clase: int
    nombre: str
    confianza: float

    @property
    def centro(self):
        x1, y1, x2, y2 = self.caja
        return ((x1 + x2) / 2, (y1 + y2) / 2)

    def validar(self, resolucion):
        ancho, alto = resolucion
        if len(self.caja) != 4 or not all(math.isfinite(v) for v in self.caja):
            raise ErrorDeteccion("Caja no finita o inválida.")
        x1, y1, x2, y2 = self.caja
        if not (0 <= x1 < x2 <= ancho and 0 <= y1 < y2 <= alto):
            raise ErrorDeteccion("Caja fuera de imagen o con área nula.")
        if (type(self.clase) is not int or self.clase not in CLASES_COCO or self.nombre != CLASES_COCO[self.clase] or
                not math.isfinite(self.confianza) or not 0 <= self.confianza <= 1):
            raise ErrorDeteccion("Clase o confianza inválida.")


def filtrar_filas(filas, resolucion, parametros, nombres):
    """Formato público Boxes.data sin tracking: x1,y1,x2,y2,confianza,clase."""
    filas = np.asarray(filas)
    if filas.ndim != 2 or filas.shape[1] != 6:
        raise ErrorDeteccion("Formato inesperado de cajas YOLO.")
    detecciones = []
    for x1, y1, x2, y2, confianza, clase in filas:
        if not math.isfinite(float(clase)) or clase != int(clase):
            raise ErrorDeteccion("Identificador de clase inválido.")
        if not math.isfinite(float(confianza)) or not 0 <= confianza <= 1:
            raise ErrorDeteccion("Confianza no finita o fuera de rango.")
        clase = int(clase)
        if clase not in parametros["clases"] or confianza < parametros["confianza"]:
            continue
        deteccion = Deteccion(tuple(map(float, (x1, y1, x2, y2))), clase,
                              nombres[clase], float(confianza))
        deteccion.validar(resolucion)
        detecciones.append(deteccion)
    return tuple(detecciones)


class DetectorVehiculos:
    def __init__(self, parametros, fabrica_modelo=None):
        self.parametros = validar_parametros(parametros)
        self.ruta = Path(self.parametros["pesos"]).resolve()
        if not self.ruta.is_file():
            raise ErrorDeteccion(f"No existen los pesos locales: {self.ruta}. No se descargan automáticamente.")
        self.clase_predictor = None
        if fabrica_modelo is None:
            from motores_inferencia import configurar_cpu
            configurar_cpu(self.parametros)
            if self.parametros['backend'] != 'pytorch':
                from motores_inferencia import MotorExportado
                self.exportado = MotorExportado(self.parametros)
                self.nombres = self.exportado.nombres
                self.forma_entrada = None
                self.tiempos = {}
                return
            # Importación diferida: el visualizador y las pruebas base funcionan sin IA.
            from ultralytics import YOLO
            from ultralytics.models.yolo.detect import DetectionPredictor
            detector = self
            class PredictorFP32(DetectionPredictor):
                def setup_model(self, *args, **kwargs):
                    super().setup_model(*args, **kwargs)
                    # select_device restablece hilos en 8. Aplicar la selección antes del primer forward.
                    configurar_cpu(detector.parametros)

                def preprocess(self, imagenes):
                    tensor = super().preprocess(imagenes)
                    detector.forma_entrada = tuple(tensor.shape)
                    if str(tensor.dtype) != 'torch.float32':
                        raise ErrorDeteccion('La comparación exige FP32.')
                    return tensor
            self.clase_predictor = PredictorFP32
            fabrica_modelo = YOLO
        self.modelo = fabrica_modelo(str(self.ruta))
        self.exportado = None
        self.forma_entrada = None
        self.tiempos = {}
        self.nombres = self.modelo.names
        if any(self.nombres.get(c) != CLASES_COCO[c] for c in self.parametros["clases"]):
            raise ErrorDeteccion("Los nombres del modelo no coinciden con las clases COCO autorizadas.")

    def calentar(self, repeticiones, detener):
        for _ in range(repeticiones):
            if detener.is_set():
                break
            self.detectar(np.zeros((600, 800, 3), np.uint8))

    def detectar(self, imagen):
        if (not isinstance(imagen, np.ndarray) or imagen.dtype != np.uint8 or
                imagen.ndim != 3 or imagen.shape[2] != 3 or imagen.size == 0):
            raise ErrorDeteccion("Se requiere una fotografía BGR uint8 válida.")
        inicio = time.perf_counter()
        try:
            if self.exportado is not None:
                filas = self.exportado.predecir(imagen)
                self.forma_entrada = self.exportado.forma_entrada
                self.tiempos = self.exportado.tiempos
                return filtrar_filas(filas, (imagen.shape[1], imagen.shape[0]), self.parametros, self.nombres), time.perf_counter()-inicio
            resultados = self.modelo.predict(source=imagen, device=self.parametros["dispositivo"],
                imgsz=self.parametros["imgsz"], conf=self.parametros["confianza"], iou=self.parametros["iou"],
                classes=self.parametros["clases"], agnostic_nms=self.parametros["agnostic_nms"],
                verbose=False, save=False, stream=False, rect=True,
                **({'predictor': self.clase_predictor} if self.clase_predictor else {}))
            self.tiempos = getattr(resultados[0], 'speed', {})
            if len(resultados) != 1 or tuple(resultados[0].orig_shape) != tuple(imagen.shape[:2]):
                raise ErrorDeteccion("YOLO no devolvió las coordenadas de la fotografía original.")
            filas = resultados[0].boxes.data.cpu().numpy()
            detecciones = filtrar_filas(filas, (imagen.shape[1], imagen.shape[0]), self.parametros, self.nombres)
        except ErrorDeteccion:
            raise
        except Exception as error:
            raise ErrorDeteccion(f"Falló la inferencia: {type(error).__name__}: {error}") from error
        return detecciones, time.perf_counter() - inicio
