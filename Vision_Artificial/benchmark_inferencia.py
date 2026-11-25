"""Benchmark CPU aislado: tres calentamientos y al menos veinte medidas por configuración."""
import argparse
from dataclasses import asdict
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import cv2
import numpy as np

from detector_vehiculos import DetectorVehiculos
from evaluar import huella_archivo, leer_escenas, evaluar_escenas, calcular_metricas
from main import RAIZ, cargar_configuracion
from roi_manager import GestorROI


def resumen(valores):
    return dict(media_s=float(np.mean(valores)), mediana_s=float(np.median(valores)),
                p95_s=float(np.percentile(valores, 95)))


def recursos():
    import torch
    datos = dict(cpu=platform.processor(), logicos=os.cpu_count(), python=platform.python_version(),
                 torch=version('torch'), ultralytics=version('ultralytics'),
                 torch_hilos=torch.get_num_threads(), torch_interop=torch.get_num_interop_threads(),
                 opencv_hilos=cv2.getNumThreads(), temperatura_c=None,
                 limitacion_termica='No hay sensor térmico fiable en esta herramienta para Windows.')
    try:
        import psutil
        memoria = psutil.Process().memory_info()
        datos.update(fisicos=psutil.cpu_count(logical=False), ram_disponible=psutil.virtual_memory().available,
                     rss_bytes=memoria.rss, pico_wset_bytes=getattr(memoria, 'peak_wset', None))
        frecuencia = psutil.cpu_freq()
        datos['cpu_mhz_instantanea'] = frecuencia.current if frecuencia else None
    except ImportError:
        datos['memoria'] = 'psutil no instalado; no se estima memoria'
    return datos


def ejecutar(args):
    config = cargar_configuracion(args.config, requiere_url=False)
    parametros = config['detector'] | {'backend': args.backend}
    if args.normalizar_auxiliares:
        parametros.update(hilos_interop=1,hilos_opencv=1)
    if args.hilos != 'actual':
        parametros.update(hilos_cpu=int(args.hilos), hilos_interop=1, hilos_opencv=1)
    if args.modelo:
        parametros['modelo_exportado'] = args.modelo.resolve()
    escenas = leer_escenas(args.escenas) if args.escenas else []
    if args.escenas:
        escenas = [s for s in escenas if s['uso'] == args.uso]
        if not escenas:
            raise ValueError('No hay escenas para el uso seleccionado.')
    fotos = [s['archivo'] for s in escenas] if escenas else (args.archivos or sorted(args.fotos.glob('*.jpg')))
    if not fotos:
        raise ValueError('Se requieren JPEG reales locales SVGA')
    imagenes = [cv2.imread(str(f)) for f in fotos]
    if any(i is None or i.shape[:2] != (600, 800) for i in imagenes):
        raise ValueError('Todas las fotografías deben ser 800x600')
    inicial = recursos()
    inicio = time.perf_counter()
    detector = DetectorVehiculos(parametros)
    carga = time.perf_counter()-inicio
    calentamiento = []
    for indice in range(3):
        _, segundos = detector.detectar(imagenes[indice % len(imagenes)])
        calentamiento.append(segundos)
    medidas, etapas, resultados = [], [], []
    inicio = time.perf_counter()
    for indice in range(args.medidas):
        numero = indice % len(imagenes)
        detecciones, segundos = detector.detectar(imagenes[numero])
        medidas.append(segundos)
        etapas.append(dict(detector.tiempos))
        resultados.append(dict(sha256=huella_archivo(fotos[numero]), detecciones=[asdict(d) for d in detecciones],
                               forma_entrada=detector.forma_entrada, tiempo_s=segundos))
    duracion = time.perf_counter()-inicio
    informe = dict(parametros={k: str(v) if isinstance(v, Path) else v for k,v in parametros.items()},
        pesos_sha256=huella_archivo(parametros['pesos']), recursos_antes=inicial, recursos_despues=recursos(),
        condiciones=args.condiciones, fotos=[dict(archivo=f.name, sha256=huella_archivo(f)) for f in fotos],
        carga_s=carga, primera_s=calentamiento[0], calentamiento_s=calentamiento,
        sostenido=resumen(medidas), frecuencia_hz=len(medidas)/duracion,
        muestras=resultados, etapas_ms=etapas,
        etapas_resumen_s={k: resumen([e[k]/1000 for e in etapas]) for k in ('preprocess','inference','postprocess')},
        latencia='Inferencia local sin HTTP; fotos precargadas. Frecuencia incluye registro/hash por iteración.',
        carga_interfaz_http='No medida: ejecutar además visualizador y revisar diagnósticos en vivo.')
    if escenas:
        regiones = GestorROI.cargar(config['ruta_roi'])
        registros, duracion_eval = evaluar_escenas(escenas, regiones, detector)
        informe['evaluacion'] = dict(metricas=calcular_metricas(registros, duracion_eval), escenas=registros,
                                    calibracion_sha256=huella_archivo(config['ruta_roi']))
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(informe, indent=2, default=str, allow_nan=False), encoding='utf-8')
    print(json.dumps(dict(hilos=args.hilos, backend=args.backend, carga_s=carga,
                          sostenido=informe['sostenido'], frecuencia_hz=informe['frecuencia_hz'])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=RAIZ/'config.json')
    parser.add_argument('--fotos', type=Path, default=RAIZ/'capturas')
    parser.add_argument('--archivos', type=Path, nargs='+', help='Selección explícita de fotografías SVGA')
    parser.add_argument('--escenas', type=Path, help='CSV manual; mismas fotos para todos los motores')
    parser.add_argument('--uso', choices=['desarrollo','final'], default='desarrollo')
    parser.add_argument('--backend', choices=['pytorch','onnx','openvino'], default='pytorch')
    parser.add_argument('--modelo', type=Path)
    parser.add_argument('--hilos', choices=['actual','2','4','6','12'], default='actual')
    parser.add_argument('--matriz', action='store_true', help='Procesos separados: actual, 2, 4, 6 y 12')
    parser.add_argument('--normalizar-auxiliares',action='store_true',help='Fijar interop y OpenCV a 1 incluso en referencia; comparar solo intraop')
    parser.add_argument('--medidas', type=int, default=20)
    parser.add_argument('--condiciones', required=True, help='Alimentación, aplicaciones activas, ventilación y carga del equipo')
    parser.add_argument('--salida', type=Path, default=RAIZ/'benchmarks/referencia.json')
    args = parser.parse_args()
    if args.medidas < 20:
        parser.error('Se requieren al menos 20 inferencias medidas, además de tres calentamientos')
    if args.matriz:
        argumentos = sys.argv[1:]
        argumentos.remove('--matriz')
        for opcion in ('--hilos','--salida'):
            if opcion in argumentos:
                indice = argumentos.index(opcion); del argumentos[indice:indice+2]
        for hilos in ('actual','2','4','6','12'):
            salida = args.salida.with_name(args.salida.stem+'_'+hilos+'.json')
            subprocess.run([sys.executable, __file__, *argumentos, '--hilos',hilos,'--salida',str(salida)], check=True)
    else:
        ejecutar(args)


if __name__ == '__main__':
    main()
