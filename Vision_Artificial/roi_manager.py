"""Geometría de dos polígonos simples, persistidos en coordenadas normalizadas."""

import json
import math
from pathlib import Path
import uuid

import cv2
import numpy as np

EPSILON = 1e-9


def _cruz(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _sobre_segmento(a, b, p):
    return (abs(_cruz(a, b, p)) <= EPSILON and
            min(a[0], b[0]) - EPSILON <= p[0] <= max(a[0], b[0]) + EPSILON and
            min(a[1], b[1]) - EPSILON <= p[1] <= max(a[1], b[1]) + EPSILON)


def _intersectan(a, b, c, d):
    giros = (_cruz(a, b, c), _cruz(a, b, d), _cruz(c, d, a), _cruz(c, d, b))
    opuestos_ab = (giros[0] > EPSILON and giros[1] < -EPSILON) or (giros[0] < -EPSILON and giros[1] > EPSILON)
    opuestos_cd = (giros[2] > EPSILON and giros[3] < -EPSILON) or (giros[2] < -EPSILON and giros[3] > EPSILON)
    if opuestos_ab and opuestos_cd:
        return True
    return any((_sobre_segmento(a, b, c), _sobre_segmento(a, b, d),
                _sobre_segmento(c, d, a), _sobre_segmento(c, d, b)))


def validar_resolucion(resolucion):
    if (not isinstance(resolucion, (list, tuple)) or len(resolucion) != 2 or
            any(type(valor) is not int or valor < 2 for valor in resolucion)):
        raise ValueError("La resolución debe contener ancho y alto enteros mayores de uno.")
    return tuple(resolucion)


def normalizar_puntos(puntos, resolucion):
    ancho, alto = validar_resolucion(resolucion)
    salida = []
    for punto in puntos:
        if not isinstance(punto, (list, tuple)) or len(punto) != 2:
            raise ValueError("Cada vértice debe contener x e y.")
        x, y = punto
        if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in punto)
                or not (0 <= x < ancho and 0 <= y < alto)):
            raise ValueError("Vértice fuera de la fotografía o no finito.")
        salida.append((x / (ancho - 1), y / (alto - 1)))
    return salida


def reconstruir_puntos(puntos, resolucion):
    ancho, alto = validar_resolucion(resolucion)
    return [(round(x * (ancho - 1)), round(y * (alto - 1))) for x, y in puntos]


def validar_poligono(puntos):
    if not isinstance(puntos, (list, tuple)) or not 3 <= len(puntos) <= 64:
        raise ValueError("Seleccione entre 3 y 64 vértices.")
    salida = []
    for punto in puntos:
        if (not isinstance(punto, (list, tuple)) or len(punto) != 2 or
                any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                    not math.isfinite(v) or not 0 <= v <= 1 for v in punto)):
            raise ValueError("Coordenadas normalizadas inválidas: se requiere 0..1.")
        salida.append(tuple(punto))
    if len(set(salida)) != len(salida):
        raise ValueError("Hay vértices repetidos; no repita el primero al cerrar.")
    cantidad = len(salida)
    for indice in range(cantidad):
        if abs(_cruz(salida[indice - 1], salida[indice], salida[(indice + 1) % cantidad])) <= EPSILON:
            raise ValueError("Hay tres vértices consecutivos alineados o un borde degenerado.")
        for otro in range(indice + 1, cantidad):
            if otro == indice + 1 or (indice == 0 and otro == cantidad - 1):
                continue
            if _intersectan(salida[indice], salida[(indice + 1) % cantidad],
                            salida[otro], salida[(otro + 1) % cantidad]):
                raise ValueError("El polígono se autointersecta.")
    area_doble = abs(sum(salida[i][0] * salida[(i + 1) % cantidad][1] -
                        salida[(i + 1) % cantidad][0] * salida[i][1] for i in range(cantidad)))
    if area_doble < 2e-6:
        raise ValueError("El polígono tiene un área nula o demasiado pequeña.")
    return salida


def _contiene_normalizado(punto, puntos):
    contorno = np.asarray(puntos, dtype=np.float32)
    return cv2.pointPolygonTest(contorno, tuple(map(float, punto)), False) >= 0


def _se_solapan(primero, segundo):
    for indice, a in enumerate(primero):
        b = primero[(indice + 1) % len(primero)]
        for otro, c in enumerate(segundo):
            if _intersectan(a, b, c, segundo[(otro + 1) % len(segundo)]):
                return True
    return _contiene_normalizado(primero[0], segundo) or _contiene_normalizado(segundo[0], primero)


class GestorROI:
    def __init__(self):
        self.regiones = {}
        self.resolucion_referencia = None

    def establecer(self, numero, puntos_pixel, resolucion):
        if numero not in (1, 2):
            raise ValueError("Solo existen ROI 1 y ROI 2.")
        puntos = validar_poligono(normalizar_puntos(puntos_pixel, resolucion))
        otra = self.regiones.get(3 - numero)
        if otra is not None and _se_solapan(puntos, otra):
            raise ValueError("Las ROI se superponen o se tocan; deje separación entre carriles.")
        self.regiones[numero] = puntos
        self.resolucion_referencia = validar_resolucion(resolucion)

    def borrar(self, numero):
        self.regiones.pop(numero, None)

    def puntos_pixel(self, numero, resolucion):
        return reconstruir_puntos(self.regiones.get(numero, []), resolucion)

    def contiene_punto(self, numero, punto_pixel, resolucion):
        """Incluye el borde de la ROI. Fuera de la imagen devuelve False."""
        if numero not in self.regiones:
            return False
        try:
            punto = normalizar_puntos([punto_pixel], resolucion)[0]
        except ValueError:
            return False
        return _contiene_normalizado(punto, self.regiones[numero])

    def guardar(self, ruta):
        if set(self.regiones) != {1, 2} or self.resolucion_referencia is None:
            raise ValueError("Confirme las dos ROI antes de guardar la calibración.")
        datos = {"version": 1, "resolucion_referencia": list(self.resolucion_referencia),
                 "rois": {str(numero): puntos for numero, puntos in self.regiones.items()}}
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = ruta.with_name(ruta.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            temporal.write_text(json.dumps(datos, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
            temporal.replace(ruta)
        finally:
            temporal.unlink(missing_ok=True)

    @classmethod
    def cargar(cls, ruta):
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
        if not isinstance(datos, dict) or datos.get("version") != 1:
            raise ValueError("Formato o versión de ROI no admitidos.")
        gestor = cls()
        gestor.resolucion_referencia = validar_resolucion(datos.get("resolucion_referencia"))
        regiones = datos.get("rois")
        if not isinstance(regiones, dict) or set(regiones) != {"1", "2"}:
            raise ValueError("El archivo debe contener exactamente ROI 1 y ROI 2.")
        gestor.regiones = {int(numero): validar_poligono(puntos) for numero, puntos in regiones.items()}
        if _se_solapan(gestor.regiones[1], gestor.regiones[2]):
            raise ValueError("Las ROI guardadas se superponen o se tocan.")
        return gestor

    def dibujar(self, imagen):
        """Retorna una copia: nunca altera la fotografía original."""
        salida = imagen.copy()
        capa = imagen.copy()
        resolucion = (imagen.shape[1], imagen.shape[0])
        colores = {1: (40, 220, 70), 2: (240, 150, 40)}
        for numero in self.regiones:
            puntos = np.asarray(self.puntos_pixel(numero, resolucion), dtype=np.int32)
            cv2.fillPoly(capa, [puntos], colores[numero])
        cv2.addWeighted(capa, 0.25, salida, 0.75, 0, dst=salida)
        for numero in self.regiones:
            puntos = np.asarray(self.puntos_pixel(numero, resolucion), dtype=np.int32)
            cv2.polylines(salida, [puntos], True, colores[numero], 1, cv2.LINE_AA)
            for punto in puntos:
                cv2.circle(salida, tuple(punto), 3, colores[numero], -1)
            cv2.putText(salida, f"ROI {numero}", tuple(puntos[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colores[numero], 1)
        return salida
