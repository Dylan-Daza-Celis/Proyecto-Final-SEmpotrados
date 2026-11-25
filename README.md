# Semáforo inteligente — Sistemas Empotrados

Proyecto final universitario sobre una maqueta de **45 × 44 cm** con intersección
en Y. Dos entradas comparten una salida. La cantidad de vehículos de juguete en
cada entrada determinará su prioridad; cada vehículo tiene el mismo peso.

## Arquitectura prevista

```text
ESP32-CAM / cámara -- imágenes por Wi-Fi --> Computadora
                                             |
                                  detector + ROI 1 / ROI 2
                                             |
                                        conteos UDP
                                             v
                                          ESP32-C6
                                             |
                                   estados + prioridad + 6 LEDs
```

La computadora permanecerá conectada. Hará detección neuronal y conteo dentro de
dos ROI: espera izquierda y derecha; convergencia y salida se excluyen. La lógica
de circulación y el control de LEDs permanecerán en la C6.

`D = N1 - N2`: D ≥ 2 prioriza carril 1; D ≤ -2 prioriza carril 2; |D| < 2 produce
alternancia. Los tiempos iniciales serán verde mínimo 5 s, máximo 15 s, amarillo
2 s y rojo total 1 s, con espera máxima objetivo 20 s. Se deberá validar su
coherencia y evitar esperas indefinidas. Nunca se permitirán ambos verdes; la
pérdida de datos válidos llevará de forma controlada a ambos rojos.

## Hardware disponible

- ESP32-CAM y base ESP32-CAM-MB USB-UART CH340G. Se había previsto una OV2640
  de 2 MP; el registro UART aportado por el usuario identificó **OV3660**.
- ESP32-C6 y una ESP32 clásica adicional para pruebas.
- Computadora, soporte elevado fijo para cámara diagonal y vehículos de juguete.
- Dos LEDs de cada color: rojo, amarillo y verde; seis resistencias de 330 Ω.
- Maqueta en Y de 45 × 44 cm.

El registro confirma PSRAM física de 8 MiB, 4 MiB mapeados al heap y prueba de
memoria correcta. El pinout AI Thinker permitió detectar e inicializar el sensor;
el usuario confirmó después **19 capturas consecutivas** con memoria estable.
Hubo dos avisos NO-SOI iniciales; la inspección visual de fotografías sigue pendiente.

## Proyectos y estado

| Carpeta | Target | Responsabilidad | Estado |
| --- | --- | --- | --- |
| `Proyecto_Final_Cam/` | `esp32` | Captura y envío HTTP de imágenes | 1.1 probada físicamente; 1.2/1.3 implementadas, validación física pendiente |
| `Proyecto_Final_C6/` | `esp32c6` | Semáforos y decisiones | Plantilla existente, sin cambios |
| `Vision_Artificial/` | Python 3.11 en computadora | Cliente HTTP, YOLO11x y ocupación por ROI | Aplicación de visión probada por el usuario; integración 04 verificada con pruebas y JPEG local, evaluación de exactitud pendiente |

La **tarea 02 (prácticas 1.2/1.3)** añade estación Wi-Fi de 2.4 GHz y una página
local con captura, descarga JPEG, vista continua, estado y controles validados.
Se conserva el controlador de cámara y su configuración inicial; un mutex protege
la captura, el envío y la reinicialización al cambiar resolución. Flash configurada
para 4 MiB y PSRAM conservada. Credenciales únicamente en `menuconfig`/`sdkconfig`
local ignorado. El servidor solo se inicia con IPv4 y se administra sin duplicados.

Para comenzar, abrir `Proyecto_Final_Cam` en VS Code y seguir su
[guía de configuración y prueba](Proyecto_Final_Cam/README.md). Los resultados
reales de compilación y el seguimiento de aceptación están en esa guía. La prueba
Wi-Fi, HTTP, descarga y visualización física de la tarea 02 corresponde al usuario.

La **tarea 03 (práctica 1.4)** añade un cliente Python con OpenCV, NumPy y Requests,
sin modificar el firmware. Un hilo consulta HTTP y conserva solo la última imagen;
la ventana permite editar dos polígonos sobre una fotografía pausada y guardar
JPEG originales con metadatos, sin anotaciones. El venv y las configuraciones son
locales, separados de ESP-IDF. Ver [instalación y controles](Vision_Artificial/README.md).
La carpeta vacía heredada `Vision Artificial/` se conserva sin cambios.

El usuario confirmó el funcionamiento de la aplicación y probó modelos
preentrenados. La **tarea 04** integra definitivamente **YOLO11x en CPU**, con foto
física **800 × 600** e inferencia inicial imgsz=960, confianza=0.15, IoU=0.45 y
clases COCO 2/3/5/7. No reconfigura automáticamente la cámara. Se conserva el
guardado de originales; dataset propio y entrenamiento se posponen.

El conteo es ocupación instantánea (N1, N2, fuera, total y D), sin tracking ni
acumulación. Un trabajador independiente procesa solo la foto pendiente más
reciente y publica cajas/conteos unidos a esa misma imagen. ROI incoherentes,
desconexión, fotos antiguas o errores invalidan el resultado; nunca equivalen a
cero vehículos. Incluye mediana opcional de tres resultados y evaluación local.

Seguimiento: **51 pruebas automatizadas correctas**; inferencia real con pesos
locales sobre una imagen sintética y un JPEG local SVGA. En este último YOLO
produjo cuatro predicciones car en unos 4.35 s; no son conteos reales verificados.
La calibración local de referencia 320 × 240 se conserva y exige reconfirmar ambas
ROI para SVGA. La meta de **90 % de escenas con ambos conteos correctos no está
demostrada**. Ver [guía de ejecución/evaluación](Vision_Artificial/README.md) y
[licencias de IA](Vision_Artificial/LICENCIAS_IA.md).

## Etapas

| Etapa | Trabajo |
| --- | --- |
| 1.1 | Inicialización y captura: usuario confirmó 19 imágenes y memoria estable |
| 1.2–1.3 | Wi-Fi/HTTP e interfaz implementados; prueba física pendiente |
| 1.4 | Cliente/visualizador confirmados por el usuario; controles de vigencia y ROI corregidos en 04 |
| 2.1 | Dataset propio y entrenamiento pospuestos |
| 2.2–2.3 | YOLO11x y conteo por ROI implementados; evaluación física de exactitud pendiente |
| 3.1–3.4 | GPIO C6, estados, prioridades simuladas y organización FreeRTOS |
| 4.1–4.3 | UDP, integración y validación de modo seguro |
| 5.1–5.2 | Experimentos, documentación y demostración |

## Desarrollo

Firmware en C con ESP-IDF nativo, VS Code y extensión oficial Espressif; sin
Arduino ni PlatformIO. El entorno local declara ESP-IDF v6.0.2. Verificar con
`idf.py --version` antes de compilar. Las rutas locales de `.vscode` no son
obligatorias para otras máquinas y no se cambia la instalación del usuario.

Seguir [AGENTS.md](AGENTS.md) y la [guía completa de cámara](Proyecto_Final_Cam/README.md).
Usar ramas y PR; mientras una dependencia siga en un PR abierto, revisar los cambios
nuevos contra esa rama para evitar duplicarlos. La integración final será hacia
`master`, sin fusionar PR automáticamente. No versionar compilaciones, componentes
descargados, venv, capturas, dataset real ni secretos. Conservar el bloqueo de
dependencias generado por Component Manager.
