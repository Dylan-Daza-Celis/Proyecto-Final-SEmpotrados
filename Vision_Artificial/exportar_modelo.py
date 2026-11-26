"""Exportación explícita FP32 a una copia local, nunca sobre los pesos originales."""
import argparse
from importlib.util import find_spec
import json
from pathlib import Path
import shutil

from evaluar import huella_archivo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pesos', type=Path, required=True)
    parser.add_argument('--directorio', type=Path, required=True, help='Directorio nuevo de salida')
    parser.add_argument('--formato', choices=['onnx','openvino'], default='onnx')
    parser.add_argument('--imgsz', type=int, default=960)
    args = parser.parse_args()
    requeridos = ['onnx', 'onnxruntime'] if args.formato == 'onnx' else ['openvino', 'onnx']
    if any(find_spec(m) is None for m in requeridos):
        parser.error('Faltan dependencias opcionales. Instalar explícitamente en entorno separado; no se instala nada aquí.')
    import os
    os.environ['YOLO_AUTOINSTALL'] = 'false'
    from ultralytics import YOLO
    huella = huella_archivo(args.pesos)
    args.directorio.mkdir(parents=True, exist_ok=False)
    copia = args.directorio/'yolo11x.pt'
    shutil.copy2(args.pesos, copia)
    modelo = YOLO(str(copia))
    # La exportación dinámica permite exactamente el rectángulo mínimo de LetterBox.
    ruta = Path(modelo.export(format=args.formato, imgsz=args.imgsz, batch=1, dynamic=True,
        half=False, int8=False, nms=False, simplify=False, device='cpu', **({'opset':17} if args.formato=='onnx' else {})))
    if ruta.is_dir():
        ruta = next(ruta.glob('*.xml'))
    if args.formato == 'onnx':
        import onnx
        grafo = onnx.load(str(ruta))
        onnx.checker.check_model(grafo)
        if (grafo.graph.input[0].type.tensor_type.elem_type != onnx.TensorProto.FLOAT or
            any(t.data_type in (onnx.TensorProto.FLOAT16, onnx.TensorProto.BFLOAT16) for t in grafo.graph.initializer)):
            raise RuntimeError('El grafo exportado no cumple FP32')
    manifiesto = dict(pesos_sha256=huella, modelo_sha256=huella_archivo(ruta), fp32=True,
                      nombres=modelo.names, dinamico=True, batch_ejecucion=1, imgsz=args.imgsz)
    if args.formato == 'openvino':
        manifiesto['bin_sha256'] = huella_archivo(ruta.with_suffix('.bin'))
    ruta.with_suffix('.manifest.json').write_text(json.dumps(manifiesto, indent=2), encoding='utf-8')
    if huella_archivo(args.pesos) != huella:
        raise RuntimeError('Los pesos originales cambiaron durante la exportación')
    print(ruta)


if __name__ == '__main__':
    main()
