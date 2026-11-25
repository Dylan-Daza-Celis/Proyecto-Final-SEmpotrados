"""Conserva JPEG originales y metadatos; no distribuye ni etiqueta fotografías."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import uuid

import cv2
import numpy as np

from camera_client import Captura


class FotografiaDuplicada(ValueError):
    pass


def preparar_dataset(raiz):
    for categoria in ("images", "labels"):
        for division in ("train", "val", "test"):
            (Path(raiz) / categoria / division).mkdir(parents=True, exist_ok=True)


def guardar_diagnostico(imagen_anotada, directorio, informacion):
    """PNG anotado + JSON separados de los JPEG originales y del dataset."""
    directorio = Path(directorio)
    directorio.mkdir(parents=True, exist_ok=True)
    nombre = f"diagnostico_{datetime.now(timezone.utc):%Y%m%dT%H%M%S_%fZ}_{uuid.uuid4().hex}"
    correcto, buffer = cv2.imencode('.png', imagen_anotada)
    if not correcto:
        raise ValueError("No se pudo codificar el diagnóstico.")
    ruta = directorio / (nombre + '.png')
    with ruta.open('xb') as archivo:
        archivo.write(buffer.tobytes())
    with ruta.with_suffix('.json').open('x', encoding='utf-8') as archivo:
        json.dump(informacion, archivo, indent=2, ensure_ascii=False, allow_nan=False)
    return ruta


class GestorDataset:
    def __init__(self, directorio):
        self.directorio = Path(directorio)
        self.directorio.mkdir(parents=True, exist_ok=True)
        self.metadatos = self.directorio / "metadatos.jsonl"
        self.sesion = uuid.uuid4().hex
        self._huellas = set()
        if self.metadatos.exists():
            for numero, linea in enumerate(self.metadatos.read_text(encoding="utf-8").splitlines(), 1):
                try:
                    registro = json.loads(linea)
                    self._huellas.add(registro["sha256"])
                except (ValueError, KeyError, TypeError) as error:
                    raise ValueError(f"Metadatos inválidos en línea {numero}; revise el archivo antes de continuar.") from error

    def guardar(self, captura: Captura):
        if (not captura.jpeg.startswith(b"\xff\xd8") or not captura.jpeg.endswith(b"\xff\xd9") or
                captura.imagen is None or captura.imagen.size == 0):
            raise ValueError("No se guarda una captura inválida.")
        try:
            comprobacion = cv2.imdecode(np.frombuffer(captura.jpeg, np.uint8), cv2.IMREAD_COLOR)
        except cv2.error as error:
            raise ValueError("El JPEG original no es decodificable.") from error
        if comprobacion is None or comprobacion.shape != captura.imagen.shape:
            raise ValueError("El JPEG original y la matriz recibida no son coherentes.")
        huella = hashlib.sha256(captura.jpeg).hexdigest()
        if huella in self._huellas:
            raise FotografiaDuplicada("Este JPEG original ya fue guardado; no se duplicará.")
        identificador = re.sub(r"[^A-Za-z0-9_-]", "_", captura.identificador or "sin-id")[:40]
        fecha_guardado = datetime.now(timezone.utc)
        nombre = f"{fecha_guardado:%Y%m%dT%H%M%S_%fZ}_id-{identificador}_{uuid.uuid4().hex}.jpg"
        ruta = self.directorio / nombre
        registro = {
            "archivo": nombre, "sesion": self.sesion, "sha256": huella,
            "fecha_captura_utc": captura.fecha_utc, "fecha_guardado_utc": fecha_guardado.isoformat(),
            "identificador_captura": captura.identificador, "ancho": captura.imagen.shape[1],
            "alto": captura.imagen.shape[0], "tamano_jpeg_bytes": len(captura.jpeg),
            "calidad_reportada_status": captura.calidad_reportada,
            "estado_reportado": captura.estado_reportado,
            "tiempo_recepcion_s": captura.recepcion_s, "tiempo_decodificacion_s": captura.decodificacion_s,
        }
        linea = (json.dumps(registro, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        # Modo exclusivo: aun con coincidencia de nombres no sobrescribe otro JPEG.
        try:
            with ruta.open("xb") as archivo:
                archivo.write(captura.jpeg)
        except FileExistsError:
            raise  # No borrar un archivo ajeno si coincide el nombre.
        except OSError:
            ruta.unlink(missing_ok=True)
            raise
        try:
            with self.metadatos.open("ab", buffering=0) as archivo:
                posicion = archivo.tell()
                try:
                    if archivo.write(linea) != len(linea):
                        raise OSError("Escritura incompleta de metadatos.")
                except OSError:
                    archivo.truncate(posicion)
                    raise
        except (OSError, ValueError):
            ruta.unlink(missing_ok=True)
            raise
        self._huellas.add(huella)
        return ruta
