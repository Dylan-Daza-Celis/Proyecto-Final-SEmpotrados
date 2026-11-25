"""Visualizador y editor de ROI. El hilo principal atiende siempre teclado/ratón."""

import argparse
import json
import math
from pathlib import Path
import sys
import time

import cv2
import numpy as np

from camera_client import Adquisidor, normalizar_url
from dataset_manager import GestorDataset, preparar_dataset
from roi_manager import GestorROI

RAIZ = Path(__file__).resolve().parent
VENTANA = "Semaforo inteligente - calibracion"
ALTO_PANEL = 165


def cargar_configuracion(ruta, url=None):
    ruta = Path(ruta).resolve()
    plantilla = json.loads((RAIZ / "config.example.json").read_text(encoding="utf-8"))
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if not isinstance(datos, dict) or set(datos) - set(plantilla):
        raise ValueError("Configuración inválida o con campos desconocidos.")
    configuracion = plantilla | datos
    configuracion["url_base"] = normalizar_url(url if url is not None else configuracion["url_base"])
    for clave in ("timeout_conexion_s", "timeout_lectura_s", "intervalo_captura_s", "pausa_reintento_s"):
        valor = configuracion[clave]
        if (isinstance(valor, bool) or not isinstance(valor, (int, float)) or
                not math.isfinite(valor) or not 0.05 <= valor <= 60):
            raise ValueError(f"{clave} debe estar entre 0.05 y 60 segundos.")
    if type(configuracion["reintentos"]) is not int or not 0 <= configuracion["reintentos"] <= 5:
        raise ValueError("reintentos debe ser un entero entre 0 y 5.")
    for clave in ("directorio_almacenamiento", "ruta_roi"):
        if not isinstance(configuracion[clave], str) or not configuracion[clave].strip():
            raise ValueError(f"{clave} debe ser una ruta no vacía.")
        configuracion[clave] = (ruta.parent / configuracion[clave]).resolve()
    return configuracion


class Visualizador:
    def __init__(self, adquisidor, regiones, almacenamiento, ruta_roi, intervalo):
        self.adquisidor = adquisidor
        self.regiones = regiones
        self.almacenamiento = almacenamiento
        self.ruta_roi = ruta_roi
        self.intervalo = intervalo
        self.captura = None
        self.secuencia = 0
        self.pausa = False
        self.activa = None
        self.borrador = []
        self.mensaje = "Esperando una fotografia. 1/2: editar ROI sobre imagen pausada."

    def raton(self, evento, x, y, _banderas, _parametro):
        if self.activa is None or self.captura is None:
            return
        alto, ancho = self.captura.imagen.shape[:2]
        # WINDOW_AUTOSIZE conserva coordenadas de píxel; el panel queda debajo.
        if evento == cv2.EVENT_LBUTTONDOWN and 0 <= x < ancho and 0 <= y < alto:
            if len(self.borrador) < 64:
                self.borrador.append((x, y))
        elif evento == cv2.EVENT_RBUTTONDOWN and self.borrador:
            self.borrador.pop()

    def _pausar(self, pausa):
        self.pausa = pausa
        if pausa:
            self.adquisidor.pausado.set()
        else:
            self.adquisidor.pausado.clear()
            self.activa = None
            self.borrador = []

    def tecla(self, tecla):
        if tecla in (ord("q"), ord("Q"), 27):
            return False
        if tecla == 32:
            self._pausar(not self.pausa)
            self.mensaje = "Pausada; /status sigue comprobando conexion." if self.pausa else "Visualizacion reanudada."
        elif tecla in (ord("1"), ord("2")):
            if self.captura is None:
                self.mensaje = "Primero debe recibirse una fotografia."
            else:
                self._pausar(True)
                self.activa = int(chr(tecla))
                resolucion = (self.captura.imagen.shape[1], self.captura.imagen.shape[0])
                self.borrador = self.regiones.puntos_pixel(self.activa, resolucion)
                self.mensaje = f"ROI {self.activa}: R limpia; clic agrega; clic derecho deshace; Enter confirma."
        elif tecla in (ord("r"), ord("R")) and self.activa:
            self.regiones.borrar(self.activa)
            self.borrador = []
            self.mensaje = f"ROI {self.activa} borrada en memoria; seleccione sus vertices."
        elif tecla in (10, 13) and self.activa and self.captura is not None:
            try:
                alto, ancho = self.captura.imagen.shape[:2]
                self.regiones.establecer(self.activa, self.borrador, (ancho, alto))
                self.mensaje = f"ROI {self.activa} confirmada. G guarda ambas; Espacio reanuda."
                self.activa = None
                self.borrador = []
            except ValueError as error:
                self.mensaje = str(error)
        elif tecla in (ord("g"), ord("G")):
            try:
                if self.activa is not None:
                    raise ValueError("Confirme el poligono activo con Enter antes de guardar.")
                self.regiones.guardar(self.ruta_roi)
                self.mensaje = "ROI guardadas. Recalibre si cambia orientacion, perspectiva o encuadre."
            except (OSError, ValueError) as error:
                self.mensaje = str(error)
        elif tecla in (ord("s"), ord("S")):
            estado = self.adquisidor.obtener_estado()
            if (self.captura is None or not estado.conectado or
                    time.monotonic() - estado.confirmada_monotonic > max(5, self.intervalo * 3)):
                self.mensaje = "No se guarda: sin fotografia o conexion reciente confirmada."
            else:
                try:
                    ruta = self.almacenamiento.guardar(self.captura)
                    self.mensaje = "Original guardado: " + ruta.name
                except (OSError, ValueError) as error:
                    self.mensaje = str(error)
        return True

    def dibujar(self):
        estado = self.adquisidor.obtener_estado()
        nueva = False
        if not self.pausa and estado.captura is not None and estado.secuencia != self.secuencia:
            self.captura, self.secuencia = estado.captura, estado.secuencia
            nueva = True
        if self.captura is None:
            imagen = np.zeros((240, 640, 3), np.uint8)
            lineas = ["Esperando JPEG valido de la camara"]
        else:
            imagen = self.regiones.dibujar(self.captura.imagen)
            alto, ancho = imagen.shape[:2]
            if self.activa and self.borrador:
                puntos = np.asarray(self.borrador, np.int32)
                cv2.polylines(imagen, [puntos], False, (50, 50, 255), 1)
                for punto in puntos:
                    cv2.circle(imagen, tuple(punto), 3, (50, 50, 255), -1)
            edad = time.monotonic() - self.captura.recibida_monotonic
            lineas = [
                f"{ancho}x{alto} | JPEG {len(self.captura.jpeg)} bytes | ID {self.captura.identificador or 'no disponible'}",
                f"HTTP {self.captura.recepcion_s * 1000:.0f} ms | decode {self.captura.decodificacion_s * 1000:.1f} ms | {estado.frecuencia_hz:.2f} Hz",
                f"{'PAUSADA' if self.pausa else 'NUEVA' if nueva else 'ULTIMA'} | edad {edad:.1f} s",
            ]
        fresca = estado.conectado and time.monotonic() - estado.confirmada_monotonic <= max(5, self.intervalo * 3)
        conexion = "Conexion confirmada" if fresca else "SIN CONEXION CONFIRMADA - IMAGEN ANTIGUA"
        lineas.insert(0, conexion)
        if not fresca:
            lineas.append(estado.mensaje)
        referencia = self.regiones.resolucion_referencia
        if self.captura is not None and referencia and referencia != (imagen.shape[1], imagen.shape[0]):
            lineas.append("Resolucion distinta: verificar encuadre; recalibrar si cambia campo visual.")
        lineas.extend([self.mensaje, "S guardar | 1/2 ROI | Enter confirmar | R borrar | G guardar ROI | Espacio pausa | Q salir"])
        # El panel no cubre la fotografía ni altera el sistema de coordenadas ROI.
        ancho_panel = max(960, imagen.shape[1])
        lienzo = np.zeros((imagen.shape[0] + ALTO_PANEL, ancho_panel, 3), np.uint8)
        lienzo[:imagen.shape[0], :imagen.shape[1]] = imagen
        for indice, linea in enumerate(lineas[:9]):
            # Hershey no representa tildes; conservar los mensajes completos en consola/JSON.
            texto = linea.encode("ascii", "replace").decode("ascii")
            cv2.putText(lienzo, texto[:145], (8, imagen.shape[0] + 18 + indice * 17),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.37, (80, 230, 120) if fresca else (80, 150, 255), 1, cv2.LINE_AA)
        return lienzo

    def ejecutar(self):
        cv2.namedWindow(VENTANA, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(VENTANA, self.raton)
        while True:
            cv2.imshow(VENTANA, self.dibujar())
            tecla = cv2.waitKey(30) & 0xff
            if not self.tecla(tecla) or cv2.getWindowProperty(VENTANA, cv2.WND_PROP_VISIBLE) < 1:
                break


def main(argumentos=None):
    parser = argparse.ArgumentParser(description="Cliente ESP32-CAM y calibración de dos ROI.")
    parser.add_argument("--config", type=Path, default=RAIZ / "config.json", help="Configuración local JSON")
    parser.add_argument("--url", help="IP o URL base; sobrescribe url_base sin modificar config.json")
    args = parser.parse_args(argumentos)
    adquisidor = None
    try:
        configuracion = cargar_configuracion(args.config, args.url)
        ruta_roi = configuracion["ruta_roi"]
        regiones = GestorROI.cargar(ruta_roi) if ruta_roi.exists() else GestorROI()
        almacenamiento = GestorDataset(configuracion["directorio_almacenamiento"])
        preparar_dataset(RAIZ / "dataset")
        adquisidor = Adquisidor(configuracion["url_base"], configuracion)
        interfaz = Visualizador(adquisidor, regiones, almacenamiento, ruta_roi, configuracion["intervalo_captura_s"])
        print("Calibración: excluir convergencia y salida. Cambios de cámara/encuadre requieren recalibrar.")
        adquisidor.start()
        interfaz.ejecutar()
        return 0
    except (OSError, ValueError, cv2.error) as error:
        print(f"No se pudo ejecutar el visualizador: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        cv2.destroyAllWindows()
        if adquisidor is not None and adquisidor.ident is not None:
            adquisidor.detener.set()
            # No se cierra Session desde otro hilo: el dueño termina su lectura
            # finita, sale del contexto y libera sockets antes de completar join.
            adquisidor.join()


if __name__ == "__main__":
    raise SystemExit(main())
