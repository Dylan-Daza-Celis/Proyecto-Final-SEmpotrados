# Tarea 06 A: investigar detecciones antes de cambiar parámetros

No se ha demostrado todavía la causa de la disminución reportada. Se conserva
YOLO11x original, PyTorch CPU FP32, SVGA y la configuración local. El diagnóstico
no entrena ni elige automáticamente umbrales por producir más cajas.

## Diagnóstico local sin cámara

Desde Vision_Artificial en la rama feat/yolo11x-inference-optimization:

```powershell
$env:YOLO_AUTOINSTALL = 'false'
$env:YOLO_CONFIG_DIR = Join-Path (Get-Location) '.ultralytics'
.\.venv\Scripts\python.exe diagnosticar_deteccion.py --archivos capturas/FOTO_REAL.jpg --explorar --salida diagnosticos/escena06
.\.venv\Scripts\python.exe diagnosticar_deteccion.py --archivos capturas/FOTO1.jpg capturas/FOTO2.jpg --barrido --repeticiones 2 --salida diagnosticos/barrido06
```

Sustituir nombres por JPEG originales existentes. El directorio de salida debe
ser nuevo. Se generan original JPEG sin recodificar, PNG con detecciones sin ROI,
PNG con ROI/identificación FUERA y, con --explorar, PNG de clases completas y
confianza 0.03. Esas predicciones adicionales quedan exclusivamente en diagnóstico;
no entran en contar_vehiculos ni en el visualizador operativo. No sobrescribe
fotos, pesos, config.json ni roi.json. Los archivos generados están ignorados.

Se cargan los detectores obtenidos con git show desde cb305f7 y 75f1a0e, el actual
y predict convencional de Ultralytics sin predictor personalizado. Se observa el
tensor por un wrapper de preprocess que devuelve exactamente el tensor original.
Los detectores históricos se copian al directorio de diagnóstico; se requiere que
los commits existan en el repositorio local. No cambia ramas ni instala paquetes.

El informe identifica pesos/fotos por SHA-256, resolución, calidad reportada del
JSONL de capturas (null si no existe), imgsz, tensor real/dtype, LetterBox, umbrales,
clases, NMS, motor, hilos efectivos, versiones, cajas, centros y confianzas. Se
calientan tres inferencias por configuración; las estadísticas posteriores son
del recorrido local, no medición de HTTP/GUI ni benchmark sostenido de 20 muestras.
Para este último utilizar benchmark_inferencia.py como en OPTIMIZACION.md.

El barrido mantiene PyTorch FP32 y clases locales:

| Caso | imgsz | conf | IoU |
| --- | --- | --- | --- |
| A | 960 | 0.15 | 0.45 |
| B | 960 | 0.10 | 0.45 |
| C | 960 | 0.15 | 0.60 |
| D | 1280 | 0.15 | 0.45 |
| E | 1280 | 0.10 | 0.45 |

Incluye además los parámetros locales reales y cada opción agnostic_nms por
separado. Las versiones históricas y predict convencional se contrastan con los
parámetros locales y NMS false/true; el barrido A–E se ejecuta en la versión actual.
Fijar fotografías, pesos, ROI y entorno para interpretar una diferencia.

## Causas observables e hipótesis

- Sin caja en operativo ni exploración: no demuestra ausencia del vehículo; se
  necesita identificarlo manualmente en el original para hablar de falso negativo.
- Caja de otra clase: hipótesis de clasificación incorrecta, requiere verdad visual.
- Caja exploratoria bajo el umbral: demuestra el filtro numérico de esa predicción,
  pero no demuestra que corresponda a un vehículo real o que deba aceptarse.
- Más cajas al modificar NMS/IoU: indicio de supresión, no prueba causal por sí solo.
- Centro fuera de ROI válidas: se identifica FUERA y se cuenta en N_fuera.
- Imagen antigua, desconexión o resultado ausente: pertenece a la vigencia del
  pipeline en vivo; un JPEG local histórico no reproduce esas condiciones.

Si las ROI no están configuradas/coherentes se muestran como referencia inválida,
con conteos null, sin convertirlo en cero. Todas las salidas offline son diagnósticos,
sin validez para decisiones de control. Un tiempo mayor de inferencia no reduce
necesariamente las cajas del JPEG, pero puede caducar resultados en vivo.

## Verdad manual y repeticiones

```powershell
.\.venv\Scripts\python.exe diagnosticar_deteccion.py --escenas evaluaciones/escenas.csv --uso desarrollo --barrido --salida diagnosticos/desarrollo06
```

Reutiliza el registro/validación de evaluar.py y sus métricas de N1/N2, exactitud
conjunta y MAE cuando hay conteos manuales y ROI válidas. Sin anotaciones de cajas
no se calculan falsos positivos/negativos: un error de conteo puede combinar ambos.
Reservar escenas finales independientes y revisar los desacuerdos individualmente.
El barrido y la exploración se rechazan con --uso final, antes de cargar el modelo
o crear resultados. Si se indican JPEG sueltos con --archivos, deben ser escenas
de desarrollo: el programa no puede deducir su partición sin un manifiesto.
No reutilizar fotografías finales para elegir umbrales, NMS o resolución.
La evaluación final utiliza una configuración previamente fijada en desarrollo,
sin barrido ni exploración. Inspeccionar sus errores no permite retocar parámetros
y presentar esas mismas escenas otra vez como una prueba independiente.

comparar_motores.py conserva ahora todas las inferencias repetidas por SHA-256:
listas de referencia/alternativa, comparaciones por repetición y estabilidad contra
la primera muestra dentro de cada motor. Rechaza números de repeticiones distintos.
El formato del informe cambia: faltantes/adicionales están dentro de comparaciones,
no en una única muestra descartando las anteriores.

El comparador registra variables_modificadas. La matriz de tarea 05 cambiaba
intraop, interop y OpenCV respecto a la referencia; no fue un ensayo de una sola
variable. Para aislar intraop usar --normalizar-auxiliares en referencia y pruebas:

```powershell
.\.venv\Scripts\python.exe benchmark_inferencia.py --matriz --normalizar-auxiliares --archivos capturas/FOTO_REAL.jpg --condiciones "Describir energía, ventilación y otras cargas" --salida benchmarks/hilos_controlados.json
```

Así interop/OpenCV quedan en 1 incluso en la referencia. Hilos efectivos y forma
real siguen verificándose; no atribuir a intraop una comparación de tres variables.

## Recalibración después de V

V invalida de forma persistente y reanuda adquisición. No permite seleccionar ROI
sobre la foto anterior ni sobre una solicitud iniciada antes de V. Esperar JPEG
vigente, presionar 1: esa captura posterior se congela como referencia común para
ambas ROI. Mientras se dibuja puede envejecer; sigue siendo referencia histórica,
sin validez para control. Una desconexión/error/cambio de época impide confirmar.
Confirmar ambas con Enter, guardar con G y reanudar con Espacio. Si hay fallo de
conexión, reanudar y repetir V para obtener otra referencia. El calentamiento y
descarte de imágenes previas se conservan. Si se exige una edad al confirmar cada
vértice, una calibración manual normal no cabría en 6 s; la vigencia se comprueba
al elegir la referencia y la conexión se vuelve a validar al confirmar.

Fuente técnica y contrato de predict: https://docs.ultralytics.com/modes/predict/.

## Correcciones pendientes de tarea 07 incorporadas

G vuelve a comprobar conexión HTTP reciente, ausencia de error, época de adquisición,
foto congelada y resolución, incluso después de confirmar ambas ROI. Ante un fallo
no escribe roi.json ni elimina la marca de invalidación. Repetir V tras reconexión
para obtener otra referencia. No basta que /status haya vuelto a responder: la
época de la referencia debe coincidir. Un error de disco conserva el contexto.

Contador, etiquetas visuales y metadatos de diagnóstico comparten asignar_roi y
Deteccion.centro en coma flotante. El redondeo solo dibuja cajas/círculos; nunca
decide pertenencia. Las regresiones incluyen centros a ambos lados de los bordes.

Para probar B sobre verdad manual de desarrollo sin cambiar config.json:

```powershell
.\.venv\Scripts\python.exe evaluar.py --candidato-b --escenas evaluaciones/escenas.csv --uso desarrollo --salida evaluaciones/candidato_b_desarrollo.json
```

El indicador selecciona explícitamente PyTorch CPU FP32, imgsz960/conf0.10/IoU0.45,
agnostic_nms=false en memoria; conserva pesos y configuraciones del usuario. Solo
acepta desarrollo. Registrar primero N1/N2 reales con --registrar; las métricas
comparan conteos, no son precisión de cajas ni FP/FN. Una vez elegidos parámetros
con desarrollo, fijarlos conscientemente para evaluar las escenas finales sin
--candidato-b ni búsquedas. El programa no modifica automáticamente config.json.

Resultado de esta revisión: 76 pruebas Python correctas (69 previas y 7 nuevas),
incluido un ensayo de B con JPEG/detector y verdad **simulados** para verificar la
herramienta; ese resultado no mide precisión de la maqueta. El usuario confirmó
que las fotos reales aún no están anotadas. La prueba real de B con verdad manual
queda pendiente; no se fabrican etiquetas ni métricas. pip check y diff --check
correctos. No se hicieron nuevas mediciones físicas ni se reinstalaron paquetes.

## Resultado real de la tarea 06

Se analizaron once JPEG originales SVGA y sus hashes, calidad reportada 12 en el
JSONL, pesos originales idénticos, Python 3.11.15, Ultralytics 8.4.218 y Torch
2.15.0+cpu; ocho hilos efectivos y FP32 en todos los casos. Las ROI locales usadas
eran geométricamente válidas para SVGA. No se modificaron ni se verificó su ajuste
visual físico. Se obtuvieron 198 registros medidos más calentamientos: dos opciones
NMS por cada referencia histórica/predict, y local/A–E en la versión actual.

Con parámetros locales equivalentes (imgsz960/conf0.15/IoU0.45), las 22 comparaciones
por cada alternativa frente a cb305f7 coincidieron: sin adicionales/faltantes,
diferencia máxima de confianza y coordenadas 0. Esto incluye 75f1a0e, actual y
predict convencional. El rect=True explícito y predictor personalizado **no
reprodujeron la pérdida en estas fotos**; no prueba equivalencia para toda escena.

| Caso | NMS agnóstico | Predicciones sumadas en 11 fotos | Mediana s | P95 s |
| --- | --- | --- | --- | --- |
| A | false | 49 | 1.964 | 3.054 |
| A | true | 44 | 2.446 | 3.455 |
| B | false | 55 | 1.903 | 2.243 |
| B | true | 50 | 1.816 | 2.764 |
| C | false | 49 | 1.900 | 2.185 |
| C | true | 44 | 1.768 | 1.898 |
| D | false | 8 | 3.139 | 3.785 |
| D | true | 8 | 3.218 | 3.503 |
| E | false | 10 | 3.222 | 3.783 |
| E | true | 10 | 2.858 | 3.047 |

Las cifras son predicciones, no vehículos reales anotados ni conteo acumulativo.
En estas fotos imgsz1280 produjo menos predicciones; más resolución de inferencia
no garantiza mejor detección. NMS agnóstico retiró cinco predicciones en A/B/C,
pero falta revisar cuáles eran duplicadas o vehículos distintos. La forma real
fue 1x3x736x960 para imgsz960 y 1x3x960x1280 para imgsz1280, sin relleno cuadrado.
Los informes conservan N1/N2/fuera por fotografía; no hay verdad manual suficiente
para MAE/exactitud ni anotaciones de cajas para FP/FN, y esas métricas son null.
No se seleccionó configuración por cantidad de cajas ni se afirmó corregida la pérdida.

Se ejecutó además exploración real sobre un JPEG con todas las clases/conf0.03,
generando originales y las tres vistas PNG. Los tiempos son recorridos locales,
con trabajo de editor y tareas de diagnóstico concurrentes, sin control térmico;
no prueban aceleración ni latencia sostenida en vivo. Calentamientos excluidos.
69 pruebas Python correctas y pip check correcto; pendiente evaluación manual de
escenas que reproduzcan la pérdida observada, condiciones de captura/encuadre y
edad de resultados en vivo. Los artefactos quedan locales en diagnosticos/.
