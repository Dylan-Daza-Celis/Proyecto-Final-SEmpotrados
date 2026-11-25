from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from soporte import captura_ejemplo
from dataset_manager import GestorDataset, FotografiaDuplicada, preparar_dataset


class PruebasDataset(unittest.TestCase):
    def test_original_exacto_nombres_unicos_y_metadatos(self):
        with tempfile.TemporaryDirectory() as carpeta:
            gestor = GestorDataset(carpeta)
            primera = captura_ejemplo(50, '../id:19')
            segunda = captura_ejemplo(90, '../id:19')
            ruta1 = gestor.guardar(primera)
            ruta2 = gestor.guardar(segunda)
            self.assertNotEqual(ruta1, ruta2)
            self.assertEqual(ruta1.parent, Path(carpeta))
            self.assertEqual(ruta1.read_bytes(), primera.jpeg)
            self.assertEqual(ruta2.read_bytes(), segunda.jpeg)
            lineas = [json.loads(linea) for linea in gestor.metadatos.read_text().splitlines()]
            self.assertEqual(len(lineas), 2)
            self.assertEqual(lineas[0]['ancho'], 120)
            self.assertEqual(lineas[0]['alto'], 80)
            self.assertEqual(lineas[0]['tamano_jpeg_bytes'], len(primera.jpeg))
            self.assertEqual(lineas[0]['calidad_reportada_status'], 12)
            self.assertEqual(lineas[0]['identificador_captura'], '../id:19')
            self.assertEqual(lineas[0]['sesion'], lineas[1]['sesion'])
            self.assertIsNotNone(datetime.fromisoformat(lineas[0]['fecha_captura_utc']).tzinfo)

    def test_duplicado_se_rechaza_incluso_tras_reabrir(self):
        with tempfile.TemporaryDirectory() as carpeta:
            captura = captura_ejemplo()
            gestor = GestorDataset(carpeta)
            ruta = gestor.guardar(captura)
            with self.assertRaises(FotografiaDuplicada):
                gestor.guardar(replace(captura, identificador='otro-id'))
            with self.assertRaises(FotografiaDuplicada):
                GestorDataset(carpeta).guardar(captura)
            self.assertEqual(ruta.read_bytes(), captura.jpeg)
            self.assertEqual(len(list(Path(carpeta).glob('*.jpg'))), 1)

    def test_jpeg_invalido_no_crea_archivos(self):
        with tempfile.TemporaryDirectory() as carpeta:
            gestor = GestorDataset(carpeta)
            with self.assertRaises(ValueError):
                gestor.guardar(replace(captura_ejemplo(), jpeg=b'\xff\xd8no es una fotografia\xff\xd9'))
            self.assertEqual(list(Path(carpeta).iterdir()), [])

    def test_colision_nunca_sobrescribe_ni_borra_original(self):
        with tempfile.TemporaryDirectory() as carpeta:
            gestor = GestorDataset(carpeta)
            fecha = datetime(2026, 1, 1, tzinfo=timezone.utc)
            with patch('dataset_manager.datetime') as reloj, patch('dataset_manager.uuid.uuid4') as uuid:
                reloj.now.return_value = fecha
                uuid.return_value.hex = 'igual'
                original = captura_ejemplo(50)
                ruta = gestor.guardar(original)
                with self.assertRaises(FileExistsError):
                    gestor.guardar(captura_ejemplo(90))
            self.assertEqual(ruta.read_bytes(), original.jpeg)
            self.assertEqual(len(gestor.metadatos.read_text().splitlines()), 1)

    def test_fallo_metadatos_retira_jpeg_huerfano(self):
        with tempfile.TemporaryDirectory() as carpeta:
            gestor = GestorDataset(carpeta)
            gestor.metadatos.mkdir()
            with self.assertRaises(OSError):
                gestor.guardar(captura_ejemplo())
            self.assertEqual(list(Path(carpeta).glob('*.jpg')), [])

    def test_estructura_no_distribuye_imagenes_y_metadatos_corruptos_se_advierten(self):
        with tempfile.TemporaryDirectory() as carpeta:
            preparar_dataset(carpeta)
            for categoria in ('images', 'labels'):
                for division in ('train', 'val', 'test'):
                    ruta = Path(carpeta) / categoria / division
                    self.assertTrue(ruta.is_dir())
                    self.assertEqual(list(ruta.iterdir()), [])
            (Path(carpeta) / 'metadatos.jsonl').write_text('{incompleto\n')
            with self.assertRaisesRegex(ValueError, 'línea 1'):
                GestorDataset(carpeta)
