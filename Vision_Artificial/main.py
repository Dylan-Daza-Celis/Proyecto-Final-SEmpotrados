"""Visualizador y editor de ROI. El hilo principal atiende siempre teclado/ratón."""

import argparse
import json
import math
from pathlib import Path
import sys
import time

import cv2
import numpy as np

from camera_client import Adquisidor, normalizar_url, captura_vigente
from dataset_manager import GestorDataset, guardar_diagnostico
from roi_manager import GestorROI
from detector_vehiculos import validar_parametros
from inference_worker import TrabajadorInferencia, motivo_entrada, motivo_resultado

RAIZ = Path(__file__).resolve().parent
VENTANA = "Semaforo inteligente - calibracion"
ALTO_PANEL = 300


def cargar_configuracion(ruta, url=None, requiere_url=True):
    ruta = Path(ruta).resolve()
    plantilla = json.loads((RAIZ / "config.example.json").read_text(encoding="utf-8"))
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    if not isinstance(datos, dict) or set(datos) - set(plantilla):
        raise ValueError("Configuración inválida o con campos desconocidos.")
    configuracion = plantilla | datos
    direccion = url if url is not None else configuracion["url_base"]
    configuracion["url_base"] = normalizar_url(direccion) if requiere_url or direccion else ""
    for clave in ("timeout_conexion_s", "timeout_lectura_s", "intervalo_captura_s", "pausa_reintento_s"):
        valor = configuracion[clave]
        if (isinstance(valor, bool) or not isinstance(valor, (int, float)) or
                not math.isfinite(valor) or not 0.05 <= valor <= 60):
            raise ValueError(f"{clave} debe estar entre 0.05 y 60 segundos.")
    if type(configuracion["reintentos"]) is not int or not 0 <= configuracion["reintentos"] <= 5:
        raise ValueError("reintentos debe ser un entero entre 0 y 5.")
    for clave in ("max_antiguedad_imagen_s", "max_antiguedad_resultado_s"):
        valor = configuracion[clave]
        if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor) or not 0.1 <= valor <= 600:
            raise ValueError(f"{clave} debe estar entre 0.1 y 600 segundos.")
    for clave in ("deteccion_activa", "filtro_mediana"):
        if type(configuracion[clave]) is not bool:
            raise ValueError(f"{clave} debe ser booleano.")
    configuracion["detector"] = validar_parametros(configuracion["detector"])
    configuracion["detector"]["pesos"] = (ruta.parent / configuracion["detector"]["pesos"]).resolve()
    if configuracion['detector']['modelo_exportado']:
        configuracion['detector']['modelo_exportado'] = (ruta.parent / configuracion['detector']['modelo_exportado']).resolve()
    if type(configuracion['calentamiento_inferencias']) is not int or not 0 <= configuracion['calentamiento_inferencias'] <= 10:
        raise ValueError('calentamiento_inferencias debe estar entre 0 y 10.')
    for clave in ("directorio_almacenamiento", "ruta_roi", "directorio_diagnosticos"):
        if not isinstance(configuracion[clave], str) or not configuracion[clave].strip():
            raise ValueError(f"{clave} debe ser una ruta no vacía.")
        configuracion[clave] = (ruta.parent / configuracion[clave]).resolve()
    return configuracion


class Visualizador:
    def __init__(self, adquisidor, regiones, almacenamiento, ruta_roi, intervalo, trabajador=None, configuracion=None):
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
        self.trabajador = trabajador
        self.configuracion = configuracion or {}
        self.deteccion_activa = trabajador is not None and self.configuracion.get("deteccion_activa", True)
        self.mostrar_cajas = True
        self.mostrar_roi = True
        self.resultado_visible = None
        self.informacion_diagnostico = {}
        self.ultima_secuencia_roi = -1
        self.limite_imagen = self.configuracion.get("max_antiguedad_imagen_s", 6.0)
        self.limite_resultado = self.configuracion.get("max_antiguedad_resultado_s", 12.0)
        self.mensaje = "Esperando una fotografia. 1/2: editar ROI sobre imagen pausada."
        self.invalidada_desde = None
        self.referencia_recalibracion = None
        self.epoca_recalibracion = None

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
            if self.trabajador:
                self.trabajador.suspender("Imagen pausada / calibrando ROI")
        else:
            self.adquisidor.pausado.clear()
            self.activa = None
            self.borrador = []

    def tecla(self, tecla):
        if tecla in (ord("q"), ord("Q"), 27):
            return False
        if tecla in (ord("d"), ord("D")) and self.trabajador:
            self.deteccion_activa = not self.deteccion_activa
            self.trabajador.suspender("Deteccion desactivada" if not self.deteccion_activa else "Inferencia pendiente")
            if self.deteccion_activa and self.trabajador.ident is None:
                self.trabajador.start()
        elif tecla in (ord("v"), ord("V")):
            self.regiones.invalidar_calibracion()
            self.invalidada_desde = time.monotonic()
            self.referencia_recalibracion = None
            self._pausar(False)
            self.mensaje = "Calibracion invalidada. Esperar captura nueva valida antes de editar ambas ROI."
        elif tecla in (ord("c"), ord("C")):
            self.mostrar_cajas = not self.mostrar_cajas
        elif tecla in (ord("o"), ord("O")):
            self.mostrar_roi = not self.mostrar_roi
        elif tecla in (ord("a"), ord("A")):
            if self.captura is not None:
                try:
                    lienzo = self.dibujar()
                    ruta = guardar_diagnostico(lienzo, self.configuracion.get("directorio_diagnosticos", RAIZ / "diagnosticos"),
                                               self.informacion_diagnostico)
                    self.mensaje = "Diagnostico separado guardado: " + ruta.name
                except (OSError, ValueError) as error:
                    self.mensaje = str(error)
        if tecla == 32:
            self._pausar(not self.pausa)
            self.mensaje = "Pausada; /status sigue comprobando conexion." if self.pausa else "Visualizacion reanudada."
        elif tecla in (ord("1"), ord("2")):
            if self.invalidada_desde is not None and self.referencia_recalibracion is None:
                estado = self.adquisidor.obtener_estado()
                candidata = estado.captura
                if (not captura_vigente(estado,candidata,self.limite_imagen) or
                        candidata.origen_monotonic <= self.invalidada_desde):
                    self.mensaje = 'Esperar captura valida iniciada despues de V.'
                    return True
                self.captura = candidata
                self.secuencia = estado.secuencia
                self.referencia_recalibracion = candidata
                self.epoca_recalibracion = estado.epoca
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
                if self.invalidada_desde is not None:
                    estado = self.adquisidor.obtener_estado()
                    if (self.captura is not self.referencia_recalibracion or
                        self.captura.origen_monotonic <= self.invalidada_desde or
                        not estado.conectado or estado.error_captura or estado.epoca!=self.epoca_recalibracion):
                        raise ValueError('Recalibracion requiere referencia posterior a V y conexion sin fallos; reanudar y repetir V.')
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
                self.invalidada_desde = None
                self.referencia_recalibracion = None
                self.mensaje = "ROI guardadas. Recalibre si cambia orientacion, perspectiva o encuadre."
            except (OSError, ValueError) as error:
                self.mensaje = str(error)
        elif tecla in (ord("s"), ord("S")):
            estado = self.adquisidor.obtener_estado()
            historica = self.pausa and self.captura is not None
            if not historica and not captura_vigente(estado, self.captura, self.limite_imagen):
                self.mensaje = "No se guarda: sin fotografia o conexion reciente confirmada."
            else:
                try:
                    ruta = (self.almacenamiento.guardar(self.captura, referencia_historica=True) if historica
                            else self.almacenamiento.guardar(self.captura))
                    self.mensaje = ("Original HISTORICO, sin validez de control: " if historica else "Original guardado: ") + ruta.name
                except (OSError, ValueError) as error:
                    self.mensaje = str(error)
        return True

    def dibujar(self):
        estado = self.adquisidor.obtener_estado()
        secuencia_anterior = self.secuencia
        if estado.captura is not None and estado.secuencia != self.ultima_secuencia_roi:
            self.regiones.observar_resolucion((estado.captura.imagen.shape[1], estado.captura.imagen.shape[0]))
            self.ultima_secuencia_roi = estado.secuencia
        estado_ia = None
        motivo = "Deteccion desactivada"
        if self.trabajador:
            entrada = motivo_entrada(estado, estado.captura, self.regiones, self.limite_imagen, self.pausa, self.deteccion_activa)
            if entrada:
                self.trabajador.suspender(entrada)
            else:
                self.trabajador.enviar(estado.captura, estado.secuencia, self.regiones, estado.epoca)
            estado_ia = self.trabajador.obtener_estado()
            motivo = motivo_resultado(estado, estado.captura, self.regiones, estado_ia,
                                      self.limite_imagen, self.limite_resultado, self.pausa, self.deteccion_activa)
        nueva = False
        if not self.pausa and estado.captura is not None and estado.secuencia != self.secuencia:
            self.captura, self.secuencia = estado.captura, estado.secuencia
            nueva = True
        self.resultado_visible = estado_ia.resultado if estado_ia else None
        resultado = self.resultado_visible
        if (not self.pausa and self.deteccion_activa and resultado is not None and
                resultado.contexto[0] == self.regiones.firma() and
                estado.captura is not None and estado.captura.imagen.shape == resultado.captura.imagen.shape):
            # Mostrar el framebuffer ANALIZADO: nunca cajas viejas sobre una foto nueva.
            self.captura, self.secuencia = resultado.captura, resultado.secuencia
        nueva = self.secuencia != secuencia_anterior
        if self.captura is None:
            imagen = np.zeros((240, 640, 3), np.uint8)
            lineas = ["Esperando JPEG valido de la camara"]
        else:
            imagen = self.regiones.dibujar(self.captura.imagen) if self.mostrar_roi else self.captura.imagen.copy()
            if (self.mostrar_cajas and resultado is not None and resultado.captura is self.captura and self.activa is None):
                for deteccion in resultado.detecciones:
                    x1, y1, x2, y2 = map(round, deteccion.caja)
                    cv2.rectangle(imagen, (x1, y1), (x2, y2), (40, 220, 220), 2)
                    cv2.circle(imagen, tuple(map(round, deteccion.centro)), 4, (30, 30, 255), -1)
                    cv2.putText(imagen, f"{deteccion.nombre} {deteccion.confianza:.2f}", (x1, max(14, y1 - 4)),
                                cv2.FONT_HERSHEY_SIMPLEX, .45, (40, 220, 220), 1)
            alto, ancho = imagen.shape[:2]
            if self.activa and self.borrador:
                puntos = np.asarray(self.borrador, np.int32)
                cv2.polylines(imagen, [puntos], False, (50, 50, 255), 1)
                for punto in puntos:
                    cv2.circle(imagen, tuple(punto), 3, (50, 50, 255), -1)
            edad = time.monotonic() - self.captura.origen_monotonic
            lineas = [
                f"{ancho}x{alto} | JPEG {len(self.captura.jpeg)} bytes | ID {self.captura.identificador or 'no disponible'}",
                f"HTTP ultimo intento {self.captura.recepcion_s * 1000:.0f} ms | decode {self.captura.decodificacion_s * 1000:.1f} ms | {estado.frecuencia_hz:.2f} Hz",
                f"{'PAUSADA' if self.pausa else 'NUEVA' if nueva else 'ULTIMA'} | edad {edad:.1f} s",
            ]
        fresca = captura_vigente(estado, self.captura, self.limite_imagen)
        conexion = f"HTTP: {'conectado' if estado.conectado else 'desconectado'} | FOTO: {'vigente' if fresca else 'ANTIGUA / INVALIDA'}"
        lineas.insert(0, conexion)
        if not fresca:
            lineas.append(estado.mensaje)
        referencia = self.regiones.resolucion_referencia
        if self.captura is not None and referencia and referencia != (imagen.shape[1], imagen.shape[0]):
            lineas.append("Resolucion distinta: verificar encuadre; recalibrar si cambia campo visual.")
        lineas.append("CONTEO: " + (motivo if motivo else "VALIDO - ocupacion instantanea"))
        if resultado is not None:
            c = resultado.instantaneo
            f = resultado.filtrado
            lineas.append(f"{'Referencia NO valida' if motivo else 'Instantaneo'}: N1={c.n1} N2={c.n2} fuera={c.n_fuera} total={c.n_total} D={c.diferencia}")
            lineas.append(f"{'Filtro de referencia NO valido' if motivo else 'Filtrado'}: N1={f.n1} N2={f.n2} fuera={f.n_fuera} D={f.diferencia} | muestras={0 if motivo else resultado.muestras_validas}")
            lineas.append(f"Inferencia {resultado.inferencia_s:.2f} s | latencia total {resultado.latencia_total_s:.2f} s | edad {time.monotonic()-resultado.captura.origen_monotonic:.1f} s")
        if estado_ia:
            modelo_nombre = Path(self.configuracion.get("detector", {}).get("pesos", "yolo11x.pt")).name
            lineas.append(f"{self.configuracion.get('detector', {}).get('backend', 'pytorch')} {modelo_nombre} | {estado_ia.frecuencia_hz:.2f} Hz deteccion | omitidos={estado_ia.omitidos} | procesando={estado_ia.procesando}")
            if estado_ia.motivo in ('CARGANDO MODELO', 'CALENTANDO MODELO'):
                lineas[-1] = estado_ia.motivo + ' | ' + lineas[-1]
            lineas.append("D deteccion | C cajas | O ROI | V invalidar calibracion | A diagnostico (S ORIGINAL)")
        self.informacion_diagnostico = (resultado.a_dict(not bool(motivo), motivo) if resultado else
                                      {"valido": False, "motivo": motivo})
        self.informacion_diagnostico = self.informacion_diagnostico | {"secuencia_mostrada": self.secuencia,
            "id_mostrado": self.captura.identificador if self.captura else None}
        lineas.extend([self.mensaje, "S guardar | 1/2 ROI | Enter confirmar | R borrar | G guardar ROI | Espacio pausa | Q salir"])
        # El panel no cubre la fotografía ni altera el sistema de coordenadas ROI.
        ancho_panel = max(960, imagen.shape[1])
        lienzo = np.zeros((imagen.shape[0] + ALTO_PANEL, ancho_panel, 3), np.uint8)
        lienzo[:imagen.shape[0], :imagen.shape[1]] = imagen
        for indice, linea in enumerate(lineas[:16]):
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
    parser.add_argument("--pesos", type=Path, help="Archivo local YOLO11x; no se descarga automáticamente")
    parser.add_argument("--sin-ia", action="store_true", help="Iniciar conservando el visualizador sin inferencia")
    args = parser.parse_args(argumentos)
    adquisidor = None
    trabajador = None
    try:
        configuracion = cargar_configuracion(args.config, args.url)
        ruta_roi = configuracion["ruta_roi"]
        regiones = GestorROI.cargar(ruta_roi) if ruta_roi.exists() else GestorROI()
        if not ruta_roi.exists():
            regiones.vincular_persistencia(ruta_roi)
        almacenamiento = GestorDataset(configuracion["directorio_almacenamiento"])
        if args.pesos:
            configuracion["detector"]["pesos"] = args.pesos.resolve()
        if args.sin_ia:
            configuracion["deteccion_activa"] = False
        adquisidor = Adquisidor(configuracion["url_base"], configuracion)
        trabajador = TrabajadorInferencia(configuracion["detector"], configuracion["max_antiguedad_resultado_s"],
                                          configuracion["filtro_mediana"], calentamiento=configuracion['calentamiento_inferencias'])
        interfaz = Visualizador(adquisidor, regiones, almacenamiento, ruta_roi, configuracion["intervalo_captura_s"],
                               trabajador, configuracion)
        print("Calibración: excluir convergencia y salida. Cambios de cámara/encuadre requieren recalibrar.")
        parametros = configuracion["detector"]
        print(f"Modelo local {Path(parametros['pesos']).name}; device={parametros['dispositivo']}; "
              f"imgsz={parametros['imgsz']}; conf={parametros['confianza']}; iou={parametros['iou']}; "
              f"clases={parametros['clases']}; agnostic_nms={parametros['agnostic_nms']}. "
              "Fotografía física requerida: 800x600, configurada desde la web.")
        adquisidor.start()
        if configuracion["deteccion_activa"]:
            trabajador.start()
        interfaz.ejecutar()
        return 0
    except (OSError, ValueError, cv2.error) as error:
        print(f"No se pudo ejecutar el visualizador: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        cv2.destroyAllWindows()
        if trabajador is not None and trabajador.ident is not None:
            trabajador.cerrar()
        if adquisidor is not None and adquisidor.ident is not None:
            adquisidor.detener.set()
            # No se cierra Session desde otro hilo: el dueño termina su lectura
            # finita, sale del contexto y libera sockets antes de completar join.
            adquisidor.join()
        if trabajador is not None and trabajador.ident is not None:
            trabajador.join()  # La llamada PyTorch en curso termina; no se mata el hilo.


if __name__ == "__main__":
    raise SystemExit(main())
