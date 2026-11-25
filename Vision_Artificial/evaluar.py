"""Evaluación local con verdad manual por escena. No descarga fotos ni entrena."""
import argparse
import csv
from datetime import datetime, timezone
import json
import hashlib
from importlib.metadata import version
import platform
from pathlib import Path
import statistics
import time
import uuid

import cv2
import numpy as np

from contador_vehiculos import contar_vehiculos
from detector_vehiculos import DetectorVehiculos
from main import RAIZ, cargar_configuracion
from roi_manager import GestorROI

CAMPOS = ["archivo", "n1_real", "n2_real", "grupo", "uso"]
CAMPOS_CON_HASH = CAMPOS + ["sha256"]


def huella_archivo(ruta):
    resumen = hashlib.sha256()
    with Path(ruta).open('rb') as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b''):
            resumen.update(bloque)
    return resumen.hexdigest()


def metadatos_reproducibilidad(pesos, calibracion):
    return {"python": platform.python_version(), "ultralytics": version("ultralytics"),
            "pytorch": version("torch"), "modelo": Path(pesos).name,
            "pesos_sha256": huella_archivo(pesos), "calibracion_sha256": huella_archivo(calibracion)}


def leer_escenas(ruta):
    ruta = Path(ruta).resolve()
    if not ruta.exists():
        return []
    with ruta.open(encoding="utf-8", newline="") as archivo:
        lector = csv.DictReader(archivo)
        if lector.fieldnames not in (CAMPOS, CAMPOS_CON_HASH):
            raise ValueError("Cabecera CSV esperada: " + ",".join(CAMPOS))
        filas = list(lector)
    grupos, vistos, hashes = {}, set(), set()
    for fila in filas:
        try:
            fila["archivo"] = (ruta.parent / fila["archivo"]).resolve()
            for clave in ("n1_real", "n2_real"):
                fila[clave] = int(fila[clave])
                if fila[clave] < 0:
                    raise ValueError("Conteo real negativo")
            if not fila["grupo"].strip() or fila["uso"] not in ("desarrollo", "final"):
                raise ValueError("Indique grupo y uso desarrollo/final")
        except (TypeError, KeyError, ValueError) as error:
            raise ValueError("Registro de evaluación inválido") from error
        if fila["archivo"] in vistos:
            raise ValueError("Fotografía repetida en evaluación")
        vistos.add(fila["archivo"])
        huella = huella_archivo(fila["archivo"])
        if "sha256" in fila and fila["sha256"] != huella:
            raise ValueError("SHA-256 no coincide: la fotografía registrada cambió")
        fila["sha256"] = huella
        if fila["sha256"] in hashes:
            raise ValueError("Fotografías idénticas por SHA-256; no se admiten entre desarrollo/final ni dentro del mismo uso")
        hashes.add(fila["sha256"])
        if fila["grupo"] in grupos and grupos[fila["grupo"]] != fila["uso"]:
            raise ValueError("No mezclar un mismo grupo/sesión entre desarrollo y evaluación final")
        grupos[fila["grupo"]] = fila["uso"]
    return filas


def registrar_escena(ruta_csv, imagen, n1, n2, grupo, uso):
    imagen = Path(imagen).resolve()
    if not imagen.is_file() or type(n1) is not int or type(n2) is not int or min(n1, n2) < 0:
        raise ValueError("Indique fotografía existente y conteos reales no negativos")
    filas = leer_escenas(ruta_csv)
    if any(f["archivo"] == imagen for f in filas):
        raise ValueError("La fotografía ya está registrada")
    huella = huella_archivo(imagen)
    if any(f["sha256"] == huella for f in filas):
        raise ValueError("Fotografía idéntica por SHA-256 ya registrada; no reutilizar en desarrollo/final")
    if not grupo or uso not in ("desarrollo", "final"):
        raise ValueError("Indique grupo y uso")
    if any(f["grupo"] == grupo and f["uso"] != uso for f in filas):
        raise ValueError("El grupo ya está asignado a otro uso")
    ruta_csv = Path(ruta_csv)
    ruta_csv.parent.mkdir(parents=True, exist_ok=True)
    filas.append(dict(archivo=str(imagen), n1_real=n1, n2_real=n2, grupo=grupo, uso=uso, sha256=huella))
    temporal = ruta_csv.with_name(ruta_csv.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporal.open("x", newline="", encoding="utf-8") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=CAMPOS_CON_HASH)
            escritor.writeheader()
            escritor.writerows(filas)
        temporal.replace(ruta_csv)  # Actualiza también los CSV anteriores, sin tocar imágenes.
    finally:
        temporal.unlink(missing_ok=True)


def calcular_metricas(registros, duracion_s):
    if not registros:
        raise ValueError("No hay escenas para evaluar")
    validos = [r for r in registros if r["valido"]]
    total = len(registros)
    resultado = {"fotografias": total, "validas": len(validos), "invalidas": total - len(validos),
                 "cobertura_porcentaje": 100 * len(validos) / total,
                 "exactitud_carril_1_porcentaje": 100 * sum(r["n1"] == r["n1_real"] for r in validos) / total,
                 "exactitud_carril_2_porcentaje": 100 * sum(r["n2"] == r["n2_real"] for r in validos) / total,
                 "ambos_correctos_porcentaje": 100 * sum(r["n1"] == r["n1_real"] and r["n2"] == r["n2_real"] for r in validos) / total,
                 "mae_carril_1": None, "mae_carril_2": None, "inferencia_media_s": None,
                 "latencia_mediana_s": None, "latencia_p95_s": None,
                 "frecuencia_efectiva_hz": len(validos) / duracion_s if duracion_s > 0 else None,
                 "meta_ambos_correctos_porcentaje": 90}
    if validos:
        resultado.update(mae_carril_1=statistics.fmean(abs(r["n1"] - r["n1_real"]) for r in validos),
                         mae_carril_2=statistics.fmean(abs(r["n2"] - r["n2_real"]) for r in validos),
                         inferencia_media_s=statistics.fmean(r["inferencia_s"] for r in validos),
                         latencia_mediana_s=float(np.median([r["latencia_s"] for r in validos])),
                         latencia_p95_s=float(np.percentile([r["latencia_s"] for r in validos], 95)))
    return resultado


def evaluar_escenas(escenas, regiones, detector):
    registros = []
    inicio = time.perf_counter()  # Excluye carga del modelo; incluye lectura/decodificación/conteo.
    for escena in escenas:
        marca = time.perf_counter()
        registro = dict(escena) | {"archivo": str(escena["archivo"]), "valido": False,
                                 "n1": None, "n2": None, "error": ""}
        try:
            contenido = escena["archivo"].read_bytes()
            registro["sha256"] = hashlib.sha256(contenido).hexdigest()
            if escena.get("sha256", registro["sha256"]) != registro["sha256"]:
                raise ValueError("La fotografía cambió después de leer el manifiesto")
            if not contenido.startswith(b"\xff\xd8") or not contenido.endswith(b"\xff\xd9"):
                raise ValueError("Se requiere JPEG original completo")
            imagen = cv2.imdecode(np.frombuffer(contenido, np.uint8), cv2.IMREAD_COLOR)
            if imagen is None or imagen.shape[:2] != (600, 800):
                raise ValueError("La fotografía debe ser SVGA 800x600")
            motivo = regiones.estado_calibracion((800, 600))
            if motivo:
                raise ValueError(motivo)
            detecciones, segundos = detector.detectar(imagen)
            conteo = contar_vehiculos(detecciones, regiones, (800, 600))
            registro.update(valido=True, n1=conteo.n1, n2=conteo.n2, n_fuera=conteo.n_fuera,
                            n_total=conteo.n_total, diferencia=conteo.diferencia,
                            inferencia_s=segundos, latencia_s=time.perf_counter() - marca)
        except Exception as error:
            registro["error"] = str(error)
        registros.append(registro)
    return registros, time.perf_counter() - inicio


def main(argumentos=None):
    parser = argparse.ArgumentParser(description="Evaluación de ocupación por ROI en fotografías locales")
    parser.add_argument("--config", type=Path, default=RAIZ / "config.json")
    parser.add_argument("--roi", type=Path)
    parser.add_argument("--pesos", type=Path)
    parser.add_argument("--escenas", type=Path, default=RAIZ / "evaluaciones/escenas.csv")
    parser.add_argument("--salida", type=Path, default=RAIZ / "evaluaciones/resumen.json")
    parser.add_argument("--uso", choices=("desarrollo", "final"), default="desarrollo")
    parser.add_argument("--registrar", type=Path, help="Añadir una fotografía y conteos manuales al CSV")
    parser.add_argument("--n1", type=int)
    parser.add_argument("--n2", type=int)
    parser.add_argument("--grupo", help="Sesión/escena; no mezclar casi duplicados con evaluación final")
    args = parser.parse_args(argumentos)
    try:
        if args.registrar:
            registrar_escena(args.escenas, args.registrar, args.n1, args.n2, args.grupo, args.uso)
            print("Escena registrada; no se ha ejecutado inferencia ni copiado la fotografía.")
            return 0
        configuracion = cargar_configuracion(args.config, requiere_url=False)
        if args.pesos:
            configuracion["detector"]["pesos"] = args.pesos.resolve()
        escenas = [f for f in leer_escenas(args.escenas) if f["uso"] == args.uso]
        if not escenas:
            raise ValueError("Registre escenas con --registrar, --n1, --n2 y --grupo antes de evaluar")
        regiones = GestorROI.cargar(args.roi or configuracion["ruta_roi"])
        if regiones.estado_calibracion((800, 600)):
            raise ValueError("Recalibre y guarde ambas ROI para 800x600 antes de evaluar")
        detector = DetectorVehiculos(configuracion["detector"])
        reproducibilidad = metadatos_reproducibilidad(configuracion["detector"]["pesos"],
                                                     args.roi or configuracion["ruta_roi"])
        reproducibilidad['backend'] = configuracion['detector']['backend']
        if configuracion['detector']['backend'] != 'pytorch':
            reproducibilidad['modelo_exportado_sha256'] = huella_archivo(configuracion['detector']['modelo_exportado'])
        registros, duracion = evaluar_escenas(escenas, regiones, detector)
        informe = {"fecha_utc": datetime.now(timezone.utc).isoformat(), "uso": args.uso,
                   "reproducibilidad": reproducibilidad,
                   "parametros": {k: str(v) if isinstance(v, Path) else v for k,v in configuracion['detector'].items()},
                   "metricas": calcular_metricas(registros, duracion), "escenas": registros,
                   "latencia": {"inferencia_s": "predict local y validación de cajas; sin HTTP",
                       "latencia_s": "lectura JPEG, hash, decodificación, inferencia y conteo; sin HTTP ni carga del modelo",
                       "http_completa": "no medida en evaluación local; en vivo desde inicio de solicitud hasta uso del resultado"}}
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_text(json.dumps(informe, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        print(json.dumps(informe["metricas"], indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Evaluación detenida: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
