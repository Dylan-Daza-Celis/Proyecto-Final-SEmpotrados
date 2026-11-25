# Tarea 05 A: medición antes de seleccionar motor

Se conserva YOLO11x, pesos originales, SVGA, imgsz y umbrales locales. El motor
inicial continúa siendo pytorch; no se cambia al más rápido automáticamente.
No se usa entrenamiento, INT8, FP16 ni BF16. Las exportaciones y reportes son locales.

## Configuración compatible

Los campos nuevos del detector son backend (pytorch/onnx/openvino), modelo_exportado
(ruta local), hilos_cpu, hilos_interop y hilos_opencv. Cero conserva el valor de
referencia; valores positivos seleccionan hilos antes del cálculo. Los valores
existentes de config.json prevalecen y no se reescribe el archivo. Cambiar backend
exige reiniciar. La pantalla y los resultados identifican el motor; los errores
no provocan sustitución automática. No se amplían los límites de vigencia.

calentamiento_inferencias es un entero 0..10, inicialmente 3. El hilo neuronal
calienta una sola vez usando BGR sintético 800x600, sin publicar conteos ni añadir
muestras al filtro. La ventana muestra CARGANDO/CALENTANDO MODELO. Al terminar,
descarta el buzón anterior y exige una solicitud de captura iniciada después del
calentamiento. La ventana y HTTP permanecen en sus hilos independientes.

S permite guardar la fotografía intencionalmente pausada como JPEG original con
referencia_historica=true y valida_para_control=false en los metadatos. No rehabilita
la foto ni los conteos. Sin pausa sigue exigiendo vigencia. Se conserva el rechazo
de duplicados. La caducidad de muestras no reinicia la frecuencia de rendimiento;
desconexión/cambio de contexto sí inicia un nuevo tramo de medición.

## Entorno opcional separado en Windows

Desde Vision_Artificial, sin activar ni modificar el venv de ESP-IDF:

```powershell
.\.venv\Scripts\python.exe -m venv .venv-opt
$rutaReferencia = (Resolve-Path .\.venv\Lib\site-packages).Path
Set-Content -LiteralPath .\.venv-opt\Lib\site-packages\referencia.pth -Value $rutaReferencia -Encoding ascii
.\.venv-opt\Scripts\python.exe -m pip install -r requirements-opt.txt
.\.venv-opt\Scripts\python.exe -m pip check
$env:YOLO_AUTOINSTALL = 'false'
$env:YOLO_CONFIG_DIR = Join-Path (Get-Location) '.ultralytics'
```

reference.pth es local: permite reutilizar PyTorch/Ultralytics del venv funcional.
No mover/borrar ese venv mientras se use .venv-opt. Instalar optimizadores solo
tras decidirlo explícitamente. Aquí se autorizó ese entorno por el usuario;
el exportador no instala dependencias. No reinstalar el entorno funcional.

## Benchmark sostenido

```powershell
.\.venv\Scripts\python.exe benchmark_inferencia.py --matriz --fotos capturas --condiciones "Equipo conectado a corriente; indicar ventilación, energía y aplicaciones activas" --salida benchmarks/pytorch.json
```

Todas las fotos seleccionadas deben ser SVGA; si hay otras resoluciones, indicar
la selección explícita con --archivos foto1.jpg foto2.jpg. No modifica ni copia
fotos. Cada configuración corre en un proceso nuevo: actual, 2, 4, 6 y 12 hilos.
Se registra carga, primera inferencia y tres calentamientos, excluidos de las
20 medidas posteriores. --medidas permite ampliar, nunca menos de 20.

El informe registra CPU, núcleos, RAM/RSS/pico working set cuando psutil los
proporciona, versiones, parámetros, hashes, forma real BCHW, detecciones completas,
tiempos de preproceso/red/posproceso, media/mediana/P95 y frecuencia. Los tiempos
de etapas Ultralytics están en ms; sus resúmenes se convierten a segundos. Fotos
precargadas: no incluye HTTP ni latencia de interfaz. Frecuencia incluye el coste
de registrar/hash por iteración. RSS es memoria del proceso, no solo del modelo.

La versión instalada restablece hilos de CPU durante setup_model. El predictor
adaptado vuelve a aplicar la selección antes del primer forward y registra el
tensor en preprocess; un hook sobre el modelo original no serviría porque se copia.
Revisar recursos_despues y forma_entrada antes de aceptar una medición.

La herramienta no dispone de lectura térmica fiable en Windows. Registrar energía,
ventilación y cargas concurrentes; repetir en condiciones equivalentes y otro orden
para investigar calentamiento o throttling. Para medir impacto en vivo, ejecutar
el visualizador con cada configuración y registrar diagnósticos A: HTTP del último
intento, latencia completa solicitud→resultado, edad al utilizar, omitidos y Hz.
Estas medidas en vivo requieren cámara disponible y no se sustituyen por el benchmark.

## ONNX FP32 y entrada rectangular

```powershell
.\.venv-opt\Scripts\python.exe exportar_modelo.py --pesos yolo11x.pt --directorio exportados/onnx-fp32 --formato onnx
.\.venv-opt\Scripts\python.exe benchmark_inferencia.py --backend onnx --modelo exportados/onnx-fp32/yolo11x.onnx --matriz --fotos capturas --condiciones "Describir condiciones reales" --salida benchmarks/onnx.json
```

El directorio de exportación debe ser nuevo. Se copia el PT y se exporta batch 1,
dinámico, FP32, opset 17, sin NMS embebida ni simplificación automática. El verificador
ONNX revisa el grafo, entrada float y ausencia de pesos float16/bfloat16. La exportación
dinámica está soportada y probada en Ultralytics 8.4.218. Aunque se exporta con ejemplo
960x960, el runtime recibe **1x3x736x960** para SVGA/imgsz960, igual que PyTorch.

El adaptador comparte LetterBox(auto=True,stride=32), BGR→RGB, BCHW float32/255,
NMS y scale_boxes de Ultralytics. Conserva conf/IoU/clases/agnostic_nms y max_det=300.
Rechaza un modelo estático con forma diferente; no añade relleno cuadrado. ONNX usa
solo CPUExecutionProvider. El manifiesto verifica hash PT/modelo y nombres de clase.

OpenVINO es opcional y no está instalado ni verificado sobre esta CPU AMD. La ruta
de código exige CPU, entrada f32, INFERENCE_PRECISION_HINT=f32 y hash del XML/BIN;
no asume que pesos FP32 obliguen toda operación interna. No se recomienda ni se
selecciona sin verificar compatibilidad y precisión efectiva del runtime en el equipo.

## Comparación de precisión

Reutilizar el CSV con verdad manual de evaluar.py y grupos finales independientes:

```powershell
.\.venv\Scripts\python.exe benchmark_inferencia.py --escenas evaluaciones/escenas.csv --uso final --hilos actual --condiciones "Condiciones reales" --salida benchmarks/final_pt.json
.\.venv-opt\Scripts\python.exe benchmark_inferencia.py --backend onnx --modelo exportados/onnx-fp32/yolo11x.onnx --escenas evaluaciones/escenas.csv --uso final --hilos 6 --condiciones "Mismas condiciones" --salida benchmarks/final_onnx.json
.\.venv-opt\Scripts\python.exe comparar_motores.py benchmarks/final_pt.json benchmarks/final_onnx.json --salida benchmarks/comparacion_final.json
```

Se comprueban mismo conjunto SHA-256, pesos, umbrales, clases, NMS, forma y ROI.
Se comparan cajas de la misma clase mediante correspondencia uno a uno IoU≥0.5,
diferencias de confianza y detecciones adicionales/faltantes. Los informes incluyen
N1/N2 por escena, exactitud conjunta y MAE si hay verdad manual y calibración válida.
Revisar individualmente los desacuerdos aunque coincidan las métricas agregadas.
No seleccionar por velocidad sola: exigir exactitud igual o mejor en escenas finales
independientes, revisar MAE y todos los desacuerdos. Sin suficiente verdad manual,
la selección definitiva queda pendiente. Una coincidencia de predicciones no prueba
que los vehículos reales se hayan detectado correctamente.

Fuentes: [Ultralytics export](https://docs.ultralytics.com/modes/export/),
[predict](https://docs.ultralytics.com/modes/predict/),
[hilos ONNX Runtime](https://onnxruntime.ai/docs/performance/tune-performance/threading.html).

## Resultados reales de esta sesión

Windows, Ryzen 5 5600H (6 núcleos/12 hilos), Python 3.11.15, Torch 2.15.0+cpu,
Ultralytics 8.4.218, ONNX 1.23.2 y ONNX Runtime 1.32.0. Once fotos reales SVGA,
seleccionadas explícitamente de las capturas existentes. Por configuración:
tres calentamientos y veinte medidas, procesos independientes. Editor activo,
sin cámara/HTTP/GUI, sin control térmico ni perfil energético verificado. La
primera exploración de PyTorch se descartó porque todos los casos acababan usando
8 hilos; esta tabla procede de la repetición con hilos efectivos verificados.

| Motor | Hilos solicitados/efectivos | Primera (s) | Mediana (s) | P95 (s) | Hz |
| --- | --- | --- | --- | --- | --- |
| PyTorch referencia | actual / 8 | 4.106 | 1.789 | 1.984 | 0.551 |
| PyTorch | 2 / 2 | 5.020 | 2.966 | 3.292 | 0.334 |
| PyTorch | 4 / 4 | 4.342 | 2.118 | 2.153 | 0.472 |
| PyTorch | 6 / 6 | 4.297 | 1.892 | 2.136 | 0.515 |
| PyTorch | 12 / 12 | 4.259 | 1.948 | 2.279 | 0.506 |
| ONNX CPU | actual / runtime por defecto | 2.341 | 2.232 | 2.723 | 0.433 |
| ONNX CPU | 2 / 2 | 3.206 | 3.167 | 3.394 | 0.317 |
| ONNX CPU | 4 / 4 | 2.505 | 2.377 | 3.252 | 0.396 |
| ONNX CPU | 6 / 6 | 2.149 | 2.081 | 2.784 | 0.452 |
| ONNX CPU | 12 / 12 | 2.177 | 2.205 | 2.893 | 0.422 |

La referencia PyTorch tuvo la menor mediana en esta ejecución; no se demostró
aceleración por otro motor/hilos. Se conserva el valor local/reference original.
La forma real fue 1x3x736x960 en ambos motores. Sobre las once fotos, todas las
configuraciones ONNX tuvieron correspondencias de la misma clase con IoU≥0.5,
sin detecciones adicionales/faltantes y diferencia máxima de confianza de
aproximadamente 4.80e-6 frente a la referencia. Esto es concordancia de predicciones,
**no exactitud medida**. La calibración local sigue con referencia 320x240 y no
hay suficientes escenas finales con verdad manual; no se inventaron N1/N2 ni
MAE/exactitud conjunta. Selección definitiva y medición en vivo pendientes.

Los informes detallados, hashes y comparaciones permanecen ignorados en benchmarks/.
Exportación y grafo ONNX FP32 verificados. OpenVINO no se instaló ni probó. Las
65 pruebas unitarias y pip check en ambos entornos pasaron. No se programó hardware.
