# Tarea 04 — YOLO11x y ocupación vehicular por ROI

Aplicación Windows/Python que conserva cliente HTTP, visualizador, calibración y
guardado de originales de la tarea 03. Añade YOLO11x preentrenado y conteo de
**ocupación en cada fotografía**, sin tracking, entrenamiento ni UDP.
Los firmware de cámara y C6 permanecen sin cambios.

## Entorno y modelo elegido

| Parámetro inicial | Valor |
| --- | --- |
| Python | 3.11.15, venv propio en Vision_Artificial/.venv |
| Ultralytics / PyTorch verificados | 8.4.218 / 2.15.0+cpu |
| OpenCV-Python / NumPy / Requests | 4.12.0.88 / 2.2.6 / 2.32.5 |
| Pesos locales | yolo11x.pt, ya descargados por el usuario |
| Dispositivo | cpu |
| Foto física requerida | **SVGA 800 × 600**, sensor OV3660 |
| Calidad JPEG sugerida | 10, configurada manualmente en la web |
| Inferencia imgsz | 960, diferente de la resolución física |
| Confianza / IoU | 0.15 / 0.45 |
| Clases COCO | 2 car, 3 motorcycle, 5 bus, 7 truck |

Todos esos tipos de detección se consideran vehículos con el mismo peso. Se
verifican los nombres del modelo para los IDs seleccionados. No se instala otro
modelo ni se descargan pesos si falta el archivo: se informa el error. Una
instancia del modelo se carga en el trabajador neuronal y se reutiliza.

## Ejecutar en Windows con el entorno existente

Abrir PowerShell normal desde la raíz del repositorio:

```powershell
cd Vision_Artificial
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip show ultralytics torch
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe main.py --pesos .\yolo11x.pt
```

El entorno funcional del usuario ya contiene los paquetes. **No ejecutar pip
install para reinstalarlos si estas comprobaciones son correctas.**
requirements.txt conserva las dependencias base; requirements-ai.txt separa las
dependencias neuronales. Solo para un entorno nuevo/incompleto, crear un venv de
Python 3.11 x64, instalar la base y después el complemento:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
```

La distribución CPU de PyTorch debe corresponder al entorno elegido; consultar
las [instrucciones oficiales](https://pytorch.org/get-started/locally/) si no está
instalada. No mezclar paquetes con el venv de ESP-IDF. Seleccionar el intérprete
Vision_Artificial/.venv en VS Code. No hace falta activar scripts PowerShell.

### Configuración local

Conservar **config.json** y **roi.json** existentes: no copiarlos encima con la
plantilla. config.example.json es una referencia sin IP real ni credenciales.
Los nuevos campos se completan por defecto al leer una configuración anterior,
sin escribir ni sustituir sus valores. Los parámetros efectivamente utilizados
se anuncian en consola al iniciar.

La dirección se obtiene de url_base o de un argumento explícito:

```powershell
.\.venv\Scripts\python.exe main.py --url http://IP-DE-LA-CAMARA --pesos .\yolo11x.pt
.\.venv\Scripts\python.exe main.py --sin-ia
.\.venv\Scripts\python.exe main.py --help
```

Sustituir IP-DE-LA-CAMARA por la IPv4 real. El modo --sin-ia conserva el cliente y
editor sin cargar el modelo; D permite activarlo después. La URL no debe llevar
/capture, consultas ni credenciales. Las rutas relativas de config.json se
resuelven contra su carpeta; --pesos se resuelve contra la terminal actual.

Campos neuronales configurables en config.json:

```json
{
  "detector": {
    "pesos": "yolo11x.pt",
    "dispositivo": "cpu",
    "imgsz": 960,
    "confianza": 0.15,
    "iou": 0.45,
    "clases": [2, 3, 5, 7]
  },
  "deteccion_activa": true,
  "filtro_mediana": true,
  "max_antiguedad_imagen_s": 30.0,
  "max_antiguedad_resultado_s": 30.0,
  "directorio_diagnosticos": "diagnosticos"
}
```

Este fragmento se integra con los campos HTTP previos, no sustituye el archivo
completo. Confianza e IoU: (0,1]; imgsz: múltiplo de 32 entre 32 y 2048; clases:
subconjunto sin duplicados de 2/3/5/7; límites de antigüedad: 0.1..600 s. Los
cambios de configuración requieren reiniciar la aplicación y reinician el filtro.

Se conservan timeout_conexion_s=3, timeout_lectura_s=15, intervalo_captura_s=1,
reintentos=2 y pausa_reintento_s=1 como valores iniciales, editables. El cliente
consulta GET /status y GET /capture secuencialmente con Requests, valida HTTP,
Content-Type, tamaño, SOI/EOI y cv2.imdecode. No usa VideoCapture ni cambia la
cámara mediante POST /control. Las sesiones/respuestas se cierran correctamente.

### Configurar SVGA y recalibrar

Desde la página web del firmware seleccionar **SVGA 800 × 600** y, si se desea,
calidad JPEG **10**; pulsar Aplicar ajustes y comprobar una fotografía. Esta es
una acción del usuario: el cliente no reconfigura la cámara automáticamente.
Si el JPEG no es de 800 × 600, la ventana solicita configurar SVGA y no ofrece
conteos válidos. imgsz=960 controla el procesamiento interno de YOLO; las cajas
devueltas se validan en coordenadas de la fotografía original de 800 × 600.

En esta inspección la calibración local conservada tenía referencia **320 × 240**.
La corrección 03.1 impide darla por válida para SVGA al editar únicamente una ROI.
Reconfirmar **ambas** sobre la foto actual y guardar con G:

1. Cámara fija y escena visible. Pulsar 1 para congelar una fotografía.
2. R limpia la primera región. Clic izquierdo añade vértices; clic derecho deshace.
3. Dibujar solo la espera del carril 1, excluyendo convergencia/salida; Enter confirma.
4. Pulsar 2, R y dibujar la espera del carril 2; Enter confirma.
5. G guarda ambas regiones y Espacio reanuda.

Se conservan coordenadas normalizadas, resolución de referencia y archivo versión
1 compatible con la tarea 03. Se rechazan polígonos degenerados, autointersectados,
superpuestos, contenidos o con bordes que se tocan. Incluye polígonos cóncavos
simples de 3..64 vértices. Un punto sobre el borde pertenece a la ROI; la separación
entre regiones evita ambigüedad. El contador reutiliza GestorROI.contiene_punto.

Cambiar resolución marca la calibración pendiente hasta reconfirmar ambas ROI;
volver a la resolución anterior no borra esa invalidación. Si se mueve, gira o
cambia la perspectiva/campo visual sin alterar dimensiones, pulsar **V** y
recalibrar ambas. Ese cambio físico no puede detectarse de forma fiable solo con
las dimensiones de la foto. Los archivos locales se conservan hasta guardar
explícitamente con G; no hay coordenadas inventadas.

## Ventana y controles

La ventana muestra la fotografía analizada con sus cajas, clase, confianza,
centros y ROI, además de ID, secuencia, HTTP, resolución, tamaño JPEG, Hz,
tiempo neuronal, latencia total, antigüedad, muestras del filtro y fotos omitidas.
Cuando YOLO tarda, se conserva el framebuffer que realmente analizó: **nunca se
dibujan sus cajas sobre una fotografía posterior**.

| Tecla / ratón | Acción |
| --- | --- |
| S | Guardar exclusivamente JPEG original, sin recodificar ni anotar |
| 1 / 2 | Pausar y editar ROI 1 / ROI 2 |
| Clic izquierdo / derecho | Añadir / quitar último vértice del borrador |
| Enter | Confirmar polígono |
| R | Borrar ROI activa en memoria |
| G | Guardar ambas ROI confirmadas |
| Espacio | Pausar/reanudar; abandona borrador no confirmado al reanudar |
| D | Activar/desactivar detección |
| C | Mostrar/ocultar cajas |
| O | Mostrar/ocultar ROI |
| V | Marcar ambas ROI pendientes de recalibración |
| A | Guardar PNG anotado y JSON de diagnóstico separados |
| Q / Escape / cerrar ventana | Salir y cerrar trabajadores |

HTTP continúa en su hilo; al pausar se consulta /status, pero no se solicitan
nuevas fotos. La ventana sigue atendiendo teclado/ratón cada 30 ms. Al salir
terminan la lectura HTTP y la inferencia PyTorch en curso antes de cerrar sus
trabajadores; puede tardar varios segundos. No se matan hilos ni se carga otra
instancia del modelo al pulsar D.

### Conteos y validez

Por cada fotografía se calcula el centro de cada caja válida y se asigna una
única categoría: carril 1, carril 2 o fuera. N_total=N1+N2+N_fuera y D=N1-N2.
No se acumula entre fotos ni se cuenta el paso de un vehículo a lo largo del tiempo.
Detecciones malformadas invalidan la inferencia, en lugar de simular una escena vacía.

La ventana distingue un **cero válido** de desconexión, JPEG inválido, inferencia
pendiente/error, ROI ausentes/pendientes, pausa e imagen/resultado antiguos.
Los conteos previos se conservan como referencia **NO válida para control**.
ResultadoInferencia.a_dict(valido=False, motivo=...) devuelve conteos de decisión
nulos y una referencia visual separada; está preparado para una integración
posterior, sin enviar UDP.

**Corrección 03.1:** una respuesta /status correcta confirma HTTP, pero no modifica
el instante monotónico de recepción del JPEG ni quita un error de captura.
La vigencia se calcula desde la foto, no desde la última consulta de estado.
S tampoco se rehabilita para una foto caducada solo porque /status responda.

El límite inicial de 30 s es configurable y debe ajustarse con las mediciones
reales de CPU; una ejecución de más de ese límite se descarta. La latencia total
desde recepción incluye decodificación, espera y procesamiento hasta publicar
el resultado. La antigüedad actual sigue creciendo después. Una foto nueva puede
llegar mientras se muestra un resultado anterior todavía vigente.

### Concurrencia y filtro

Hay un hilo HTTP, un trabajador neuronal y el hilo de la ventana. Cada buzón
contiene solo el elemento más reciente; si entra otro trabajo pendiente lo
reemplaza y se contabiliza como omitido. Cada secuencia se procesa como máximo
una vez; no hay inferencias simultáneas ni cola que crezca con la carga.

El trabajo incorpora la foto, ID, secuencia y una copia de las ROI. Revisión de
ROI y época de adquisición forman el contexto. Pausar, desconectar, invalidar
calibración o cambiar ROI invalida trabajos en curso: su resultado se descarta
si el contexto ya cambió. Al reanudar se espera una secuencia nueva.

La mediana opcional usa las últimas tres inferencias válidas nuevas para N1, N2
y N_fuera; total y D filtrados se derivan de esos tres valores. Con una o dos
muestras muestra el instantáneo mientras se llena la ventana. Se reinicia ante
desconexión, captura inválida, cambio de ROI/configuración, desactivación o pérdida
de vigencia. No incorpora duplicados ni resultados antiguos. Deshabilitar
filtro_mediana permite comparar; el filtro no corrige falsos positivos sistemáticos.
Si caduca una muestra de una mediana ya publicada, se vuelve al instantáneo con
cero muestras hasta recibir otra inferencia; no se conserva aquella mediana vigente.

## Originales y diagnósticos

S conserva el JPEG original de la fotografía visible y sus metadatos JSON Lines,
con fecha UTC, ID, UUID, sesión, SHA-256, dimensiones, calidad reportada y tiempos.
Impide duplicados exactos y sobrescrituras. Calidad procede de /status y puede
desactualizarse si otro cliente reconfigura entre estado y captura; evitar cambios
simultáneos durante una medición. La foto debe estar vigente y sin error conocido.

A guarda el lienzo anotado y un JSON en **diagnosticos/**, con el indicador de
validez, conteos y secuencia/ID mostrado. Estos archivos no se usan como imágenes
de entrenamiento. Las carpetas dataset/ heredadas se conservan, pero esta tarea
no recopila automáticamente un dataset ni distribuye train/val/test.
Pesos, runs/, capturas, diagnósticos, reportes de evaluación y configuraciones
locales se excluyen de Git. Los archivos generados por pruebas anteriores del
usuario permanecen intactos.

## Evaluación experimental sin cámara

evaluar.py utiliza fotografías JPEG locales y verdad manual en CSV, sin HTTP ni
ventana. Solo carga el modelo una vez por ejecución. Puede usarse con la cámara
desconectada; requiere ambas ROI calibradas y guardadas para 800 × 600.

Registrar manualmente una foto, sustituyendo NOMBRE_REAL.jpg y sus conteos reales:

```powershell
.\.venv\Scripts\python.exe evaluar.py --registrar "capturas\NOMBRE_REAL.jpg" --n1 2 --n2 1 --grupo sesion-01 --uso desarrollo
```

Los números anteriores son un ejemplo de uso, no anotaciones de una foto real.
El CSV por defecto se guarda en evaluaciones/escenas.csv y contiene:
archivo,n1_real,n2_real,grupo,uso. No copia imágenes ni entrena. Rechaza registros
duplicados y grupos mezclados entre desarrollo y final.

```powershell
.\.venv\Scripts\python.exe evaluar.py --uso desarrollo --salida evaluaciones/desarrollo.json
.\.venv\Scripts\python.exe evaluar.py --uso final --salida evaluaciones/final.json
.\.venv\Scripts\python.exe evaluar.py --help
```

Se pueden indicar --config, --roi, --pesos y --escenas. Primero seleccionar
parámetros con escenas de desarrollo. Para la evaluación final:

1. Preparar entre **30 y 50 escenas reales diferentes**, cubriendo carriles vacíos,
   equilibrio, predominio de cada carril, vehículos juntos, tamaños y posiciones.
2. Anotar manualmente N1/N2 sin consultar la predicción al establecer la verdad.
3. Reservar escenas/grupos independientes con uso=final antes de ajustar parámetros.
   No llevar fotos casi iguales de una sesión a desarrollo y final.
4. Fijar modelo, ROI, luz, conf, IoU e imgsz; ejecutar una vez la evaluación final.
5. Publicar número de escenas, cobertura/errores y métricas reales. La meta es
   **al menos 90 % de fotografías con ambos conteos correctos**; no está demostrada.

El informe calcula MAE por carril, exactitud de cada carril, porcentaje con ambos
correctos, tiempo medio neuronal, mediana y P95 de latencia, y frecuencia efectiva.
Las escenas inválidas cuentan como incorrectas en los porcentajes globales; no
se convierten en cero. MAE y tiempos se calculan sobre escenas válidas y se
informa cobertura; si no hay ninguna válida son null. El P95 usa interpolación
lineal de NumPy. La latencia de evaluación incluye lectura local/decodificación,
inferencia y conteo, **sin HTTP ni carga del modelo**, diferente de la latencia
en vivo. La frecuencia es fotos válidas / duración total del recorrido local.

## Pruebas y resultado real

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Verificación del **25 de noviembre de 2026**:

- **51 pruebas correctas**, incluidas las 29 anteriores. Las nuevas usan detecciones
  simuladas y no necesitan PyTorch, Ultralytics, red ni descargar YOLO11x.
- Cobertura de centros, clases/confianza, ocupación y fuera, cero válido, ROI
  inválidas/pendientes, error neuronal, edad, desconexión, cambio de contexto
  durante inferencia, buzón/omitidos, no repetir secuencias, filtro y métricas.
- Prueba real adicional con los pesos locales: imagen sintética negra SVGA,
  imgsz=960, CPU, carga ~0.53 s e inferencia ~4.49 s, cero predicciones.
- Prueba sobre un JPEG local SVGA existente: **4 predicciones car**, ~4.35 s.
  No hubo verdad manual ni conteo ROI: el archivo de calibración local seguía
  referenciado a 320 × 240 y se conservó. No es una medición de precisión.
- Versiones instaladas verificadas; pip check correcto. No se reinstalaron
  paquetes ni se volvieron a descargar pesos. main.py --help y evaluar.py --help
  comprobados. Los dos proyectos de firmware no cambian.

La aplicación previa y experimentos con modelos fueron confirmados por el usuario.
La integración en vivo de la tarea 04, recalibración SVGA, validez en desconexiones
reales y evaluación de 30–50 escenas siguen pendientes. Los tiempos citados son
pruebas individuales, no un benchmark ni garantía de frecuencia.

## Licencia y diagnóstico

Consultar [LICENCIAS_IA.md](LICENCIAS_IA.md): Ultralytics ofrece AGPL-3.0 y Enterprise.
El carácter universitario/público no exime de conservar avisos y cumplir los términos
de distribución/fuente correspondiente aplicables. La licencia de las aportaciones
del equipo debe acordarse; este cambio no la asigna automáticamente.

| Síntoma | Acción |
| --- | --- |
| No existen pesos | Indicar ruta local correcta con --pesos; no se descargan automáticamente |
| No coincide nombre de clase | Usar pesos COCO YOLO11x correctos; no reinterpretar IDs silenciosamente |
| Solicita SVGA | Seleccionar 800 × 600 desde la web; el cliente no cambia la cámara |
| ROI pendientes | Reconfirmar ambas en resolución actual; V invalida tras mover cámara |
| Modelo lento / fotos omitidas | Comportamiento esperado de CPU: medir latencia; revisar límite de vigencia |
| Cero NO válido | Revisar causa visible; no interpretarlo como carriles vacíos |
| HTTP 503 / timeout | Revisar IP, red local y monitor; el cliente reintenta y conserva referencia inválida |
| Imagen no cambia en pausa | Espacio reanuda; /status no renueva esa foto antigua |
| Guardado S rechazado | Foto caducada, captura inválida o hash duplicado; obtener una nueva foto |
| Ventana ausente | Usar opencv-python en escritorio y el intérprete del venv, no headless |

Referencias oficiales:
[YOLO11](https://docs.ultralytics.com/models/yolo11/),
[predict / coordenadas originales](https://docs.ultralytics.com/modes/predict/),
[pointPolygonTest](https://docs.opencv.org/4.12.0/d3/dc0/group__imgproc__shape.html),
[Ultralytics 8.4.218](https://pypi.org/project/ultralytics/8.4.218/) y
[licencia Ultralytics](https://www.ultralytics.com/license).
