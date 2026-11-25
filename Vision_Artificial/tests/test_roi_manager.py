import json
from pathlib import Path
import tempfile
import unittest

from soporte import captura_ejemplo
import numpy as np
from roi_manager import GestorROI, normalizar_puntos, reconstruir_puntos, validar_poligono


class PruebasROI(unittest.TestCase):
    def setUp(self):
        self.gestor = GestorROI()
        self.izquierda = [(5, 5), (40, 5), (40, 50), (5, 50)]
        self.derecha = [(70, 5), (110, 5), (110, 50), (70, 50)]
        self.resolucion = (120, 80)

    def test_normalizacion_incluye_bordes_y_reconstruye(self):
        puntos = [(0, 0), (119, 79), (23, 19)]
        normalizados = normalizar_puntos(puntos, self.resolucion)
        self.assertEqual(normalizados[:2], [(0.0, 0.0), (1.0, 1.0)])
        self.assertEqual(reconstruir_puntos(normalizados, self.resolucion), puntos)
        self.assertEqual(reconstruir_puntos([(1, 1)], (640, 480)), [(639, 479)])

    def test_guardar_cargar_y_clasificar(self):
        self.gestor.establecer(1, self.izquierda, self.resolucion)
        self.gestor.establecer(2, self.derecha, self.resolucion)
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'roi.json'
            self.gestor.guardar(ruta)
            guardado = json.loads(ruta.read_text())
            self.assertEqual(guardado['resolucion_referencia'], [120, 80])
            recuperado = GestorROI.cargar(ruta)
        self.assertTrue(recuperado.contiene_punto(1, (20, 20), self.resolucion))
        self.assertTrue(recuperado.contiene_punto(1, (5, 5), self.resolucion))
        self.assertFalse(recuperado.contiene_punto(1, (90, 20), self.resolucion))
        self.assertFalse(recuperado.contiene_punto(1, (-1, 20), self.resolucion))
        self.assertTrue(recuperado.contiene_punto(2, (90, 20), self.resolucion))
        self.assertEqual(recuperado.puntos_pixel(1, self.resolucion), self.izquierda)

    def test_rechaza_degenerados_autointerseccion_y_limites(self):
        invalidos = [[], [(0, 0), (1, 1)], [(0, 0), (1, 0), (0.5, 0)],
                     [(0, 0), (1, 1), (0, 1), (1, 0)],
                     [(0, 0), (1, 0), (1, 1), (0, 0)],
                     [(0, 0), (float('nan'), 0), (1, 1)],
                     [(-0.1, 0), (1, 0), (1, 1)]]
        for puntos in invalidos:
            with self.subTest(puntos=puntos):
                with self.assertRaises(ValueError):
                    validar_poligono(puntos)
        with self.assertRaises(ValueError):
            self.gestor.establecer(1, [(0, 0), (120, 0), (0, 20)], self.resolucion)

    def test_rechaza_superposicion_contencion_y_contacto(self):
        self.gestor.establecer(1, self.izquierda, self.resolucion)
        for segundo in ([(20, 20), (60, 20), (60, 60), (20, 60)],
                        [(10, 10), (20, 10), (20, 20), (10, 20)],
                        [(40, 5), (60, 5), (60, 30), (40, 30)]):
            with self.assertRaises(ValueError):
                self.gestor.establecer(2, segundo, self.resolucion)
        self.assertNotIn(2, self.gestor.regiones)

    def test_poligono_concavo_y_cruces_sin_vertices_contenidos(self):
        self.gestor.establecer(1, [(10, 10), (60, 10), (60, 25), (25, 25), (25, 60), (10, 60)], self.resolucion)
        self.assertTrue(self.gestor.contiene_punto(1, (15, 40), self.resolucion))
        self.assertFalse(self.gestor.contiene_punto(1, (40, 40), self.resolucion))
        cruz = GestorROI()
        cruz.establecer(1, [(5, 30), (110, 30), (110, 40), (5, 40)], self.resolucion)
        with self.assertRaises(ValueError):
            cruz.establecer(2, [(50, 5), (60, 5), (60, 70), (50, 70)], self.resolucion)

    def test_dibujo_no_modifica_fotografia_y_borrado(self):
        self.gestor.establecer(1, self.izquierda, self.resolucion)
        captura = captura_ejemplo()
        original = captura.imagen.copy()
        anotada = self.gestor.dibujar(captura.imagen)
        np.testing.assert_array_equal(captura.imagen, original)
        self.assertFalse(np.array_equal(anotada, original))
        self.gestor.borrar(1)
        self.assertFalse(self.gestor.contiene_punto(1, (20, 20), self.resolucion))
        with tempfile.TemporaryDirectory() as carpeta:
            with self.assertRaises(ValueError):
                self.gestor.guardar(Path(carpeta) / 'roi.json')

    def test_archivo_roi_invalido_no_se_acepta(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'roi.json'
            ruta.write_text('{"version":1,"resolucion_referencia":[120,80],"rois":{}}')
            with self.assertRaises(ValueError):
                GestorROI.cargar(ruta)
