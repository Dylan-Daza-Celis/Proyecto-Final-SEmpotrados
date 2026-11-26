"""Motores CPU FP32 con LetterBox rectangular y NMS compartidos con Ultralytics."""
import json
from pathlib import Path
import time

import cv2
import numpy as np


def configurar_cpu(parametros):
    import torch
    if parametros['hilos_cpu']:
        torch.set_num_threads(parametros['hilos_cpu'])
    if parametros['hilos_interop']:
        if torch.get_num_interop_threads() != parametros['hilos_interop']:
            torch.set_num_interop_threads(parametros['hilos_interop'])
    if parametros['hilos_opencv']:
        cv2.setNumThreads(parametros['hilos_opencv'])


class MotorExportado:
    def __init__(self, parametros):
        from evaluar import huella_archivo
        self.parametros = parametros
        ruta = Path(parametros['modelo_exportado'])
        if not ruta.is_file() or parametros['dispositivo'] != 'cpu':
            raise ValueError('Se requiere modelo exportado local y dispositivo cpu.')
        manifiesto = json.loads(ruta.with_suffix('.manifest.json').read_text(encoding='utf-8'))
        if (manifiesto['pesos_sha256'] != huella_archivo(parametros['pesos']) or
                manifiesto['modelo_sha256'] != huella_archivo(ruta) or not manifiesto['fp32']):
            raise ValueError('Modelo exportado sin procedencia FP32 verificable.')
        self.nombres = {int(k): v for k, v in manifiesto['nombres'].items()}
        from detector_vehiculos import CLASES_COCO
        if any(self.nombres.get(c) != CLASES_COCO[c] for c in parametros['clases']):
            raise ValueError('Clases del modelo exportado incompatibles.')
        self.forma_entrada = None
        self.tiempos = {}
        self.backend = parametros['backend']
        if self.backend == 'onnx':
            import onnxruntime as ort
            opciones = ort.SessionOptions()
            opciones.intra_op_num_threads = parametros['hilos_cpu']
            opciones.inter_op_num_threads = parametros['hilos_interop'] or 1
            opciones.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            self.sesion = ort.InferenceSession(str(ruta), sess_options=opciones, providers=['CPUExecutionProvider'])
            entrada = self.sesion.get_inputs()[0]
            if entrada.type != 'tensor(float)' or self.sesion.get_providers() != ['CPUExecutionProvider']:
                raise ValueError('Se requiere ONNX CPU FP32.')
            self.nombre = entrada.name
            self.forma_modelo = entrada.shape
        else:
            import openvino as ov
            if manifiesto.get('bin_sha256') != huella_archivo(ruta.with_suffix('.bin')):
                raise ValueError('Pesos BIN de OpenVINO sin hash verificable.')
            modelo = ov.Core().read_model(str(ruta))
            self.sesion = ov.Core().compile_model(modelo, 'CPU', {
                'INFERENCE_PRECISION_HINT': ov.Type.f32, 'PERFORMANCE_HINT': 'LATENCY',
                **({'INFERENCE_NUM_THREADS': parametros['hilos_cpu']} if parametros['hilos_cpu'] else {})})
            if self.sesion.get_property('INFERENCE_PRECISION_HINT') != ov.Type.f32:
                raise ValueError('OpenVINO no confirma precisión FP32; motor rechazado.')
            self.forma_modelo = [int(d.get_length()) if d.is_static else None for d in modelo.input().partial_shape]
            if modelo.input().get_element_type() != ov.Type.f32:
                raise ValueError('Entrada OpenVINO no FP32.')

    def predecir(self, imagen):
        import torch
        from ultralytics.data.augment import LetterBox
        from ultralytics.utils.nms import non_max_suppression
        from ultralytics.utils.ops import scale_boxes
        p = self.parametros
        inicio = time.perf_counter()
        ajustada = LetterBox((p['imgsz'], p['imgsz']), auto=True, stride=32)(image=imagen)
        tensor = np.ascontiguousarray(ajustada[..., ::-1].transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
        self.forma_entrada = tensor.shape
        if any(isinstance(d, int) and d != r for d, r in zip(self.forma_modelo, tensor.shape)):
            raise ValueError('Forma exportada distinta del LetterBox rectangular original; no se añade relleno cuadrado.')
        previo = time.perf_counter()
        salida = (self.sesion.run(None, {self.nombre: tensor})[0] if self.backend == 'onnx'
                  else self.sesion(tensor)[self.sesion.output(0)])
        neuronal = time.perf_counter()
        if salida.dtype != np.float32 or salida.ndim != 3 or salida.shape[1] != 84:
            raise ValueError('Salida FP32 COCO sin NMS esperada: batch 1 x 84 x candidatos.')
        cajas = non_max_suppression(torch.from_numpy(salida), p['confianza'], p['iou'],
                                  classes=p['clases'], agnostic=p['agnostic_nms'], max_det=300)[0]
        cajas[:, :4] = scale_boxes(tensor.shape[2:], cajas[:, :4], imagen.shape)
        final = time.perf_counter()
        self.tiempos = dict(preprocess=(previo-inicio)*1000, inference=(neuronal-previo)*1000,
                            postprocess=(final-neuronal)*1000)
        return cajas.cpu().numpy()
