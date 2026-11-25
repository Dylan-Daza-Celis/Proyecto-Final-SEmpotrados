# Instrucciones permanentes — Sistemas Empotrados

## Propósito y arquitectura

Proyecto universitario: semáforo inteligente para una intersección en Y de 45 × 44 cm.
Dos carriles de entrada convergen en una salida compartida. Cada carril lleva LEDs
rojo, amarillo y verde, cada uno con resistencia individual de 330 Ω.

- ESP32-CAM: captura con OV2640 u OV3660 y transmisión HTTP por Wi-Fi en 1.2/1.3.
  El planteamiento inicial indicaba OV2640; la prueba UART del usuario detectó
  OV3660 (PID 0x3660). Mantener soporte para ambos y registrar el modelo real.
- Computadora conectada durante la operación: detección de vehículos de juguete,
  asignación a ROI y conteos. Posteriormente envía los conteos por UDP.
- ESP32-C6: valida mensajes, decide prioridad, ejecuta la máquina de estados y
  controla los seis LEDs. La computadora nunca controla directamente los LEDs.
- ROI 1: espera izquierda; ROI 2: espera derecha. Excluir convergencia y salida.
- Todos los vehículos pesan igual. La clasificación por colores es una ampliación.

## Reglas de desarrollo

- Firmware exclusivamente ESP-IDF nativo y C. No Arduino IDE, Arduino Framework,
  PlatformIO ni adaptación directa de ejemplos Arduino.
- Entorno del usuario: VS Code con extensión oficial ESP-IDF de Espressif.
  Está configurado v6.0.2: verificar siempre la versión efectiva antes de compilar.
- No cambiar instalación/configuración ESP-IDF del usuario sin autorización.
  Las rutas absolutas locales existentes no son requisitos portables del proyecto.
- Usar componentes oficiales, Component Manager y versiones reproducibles;
  conservar `dependencies.lock` generado por el gestor. Evitar dependencias extra.
- Código y documentación en español, funciones/variables descriptivas, módulos
  sencillos explicados para estudiantes. Usar FreeRTOS cuando corresponda.
- No publicar secretos, credenciales, tokens, configuraciones locales sensibles,
  `build/` ni `managed_components/`.
- No desactivar brownout para esconder fallos de alimentación.
- Distinguir revisión de código, compilación y prueba física; nunca inventar resultados.
- Programación y prueba física a cargo del usuario desde VS Code.

## Estructura y alcance incremental

- Reutilizar `Proyecto_Final_Cam/` (target `esp32`) y `Proyecto_Final_C6/`
  (target `esp32c6`). No crear proyectos duplicados.
- Práctica 1.1: solo inicialización de cámara y captura JPEG periódica. No modificar
  firmware C6 ni agregar Wi-Fi, HTTP, visión, UDP o controlador de semáforos aquí.
- Tarea actual 02 (1.2/1.3): Wi-Fi STA de 2.4 GHz y servidor HTTP oficial con
  GET /, GET /capture, GET /status y POST /control. Reutilizar cámara; un mutex
  protege adquisición/envío/reconfiguración. No mantener el bucle periódico 1.1
  compitiendo con HTTP. Conservar su función de diagnóstico.
- El usuario confirmó 19 capturas consecutivas y memoria estable en 1.1 con OV3660;
  hubo dos NO-SOI iniciales. No afirmar aún verificación visual de fotografías.
- Flash física 4 MiB: CONFIG_ESPTOOLPY_FLASHSIZE_4MB. Conservar PSRAM funcional.
  Usar la tabla oficial PARTITION_TABLE_SINGLE_APP_LARGE (factory 1500 KiB)
  para dar margen al firmware con Wi-Fi/HTTP; conservar offsets de NVS/factory.
- Credenciales solo mediante Kconfig en sdkconfig ignorado; jamás en defaults,
  logs o contenido versionado. No publicar binarios con credenciales incorporadas.
- Resoluciones autorizadas QVGA/VGA/SVGA y calidad 10..40. Validar el contrato de
  control y reinicializar buffers bajo mutex; restaurar configuración si falla.
  Cada framebuffer se devuelve una vez, incluso en errores de envío.
- Interfaz HTML/CSS/JS embebida, sin Internet ni frameworks; vista continua con
  solicitudes secuenciales, pausa de 1 s y liberación de object URLs reemplazadas.
  Verificar SOI/EOI y decodificación en navegador. Estabilización limitada y visible.
- La C6, redes neuronales y comunicación UDP de la aplicación siguen fuera de alcance.
- Cámara inicial: pinout AI Thinker (confirmar placa física), JPEG QVGA 320 × 240,
  XCLK 20 MHz, calidad 12, un framebuffer en PSRAM, `CAMERA_GRAB_WHEN_EMPTY`,
  `LEDC_TIMER_0`, `LEDC_CHANNEL_0`, espera de 5000 ms con `vTaskDelay()`.
- Verificar PSRAM antes de inicializar cámara. Si falla inicialización, informar
  código y detener captura. Si falla captura, registrar y reintentar tras espera.
  Devolver todo framebuffer obtenido, incluso si se descarta. Registrar contador,
  dimensiones, formato, tamaño y memoria mediante ESP_LOGI/W/E.
- Separar pinout en encabezado y controlador en `.h/.c`; registrar fuentes en CMake.
  Mantener README raíz y guía reproducible de la cámara con solución de problemas.
- Etapas siguientes: 1.2 Wi-Fi, 1.3 HTTP JPEG, 1.4 Python/OpenCV; 2.1 dataset,
  2.2 detector, 2.3 ROI/conteo; 3.1 GPIO C6, 3.2 estados, 3.3 prioridad simulada,
  3.4 tareas/colas/temporizadores; 4.1 UDP, 4.2 integración, 4.3 modo seguro;
  5.1 experimentos, 5.2 documentación/demostración.

## Reglas futuras del semáforo (no implementar en 1.1)

`D = N1 - N2`; D ≥ 2 favorece carril 1, D ≤ -2 favorece carril 2,
|D| < 2 implica alternancia convencional. Parámetros configurables: verde mínimo
5 s, máximo 15 s, amarillo 2 s, rojo total 1 s, espera máxima objetivo 20 s.
Verificar coherencia temporal y evitar inanición antes de integrar. Nunca ambos
verdes simultáneamente. Pérdida de datos válidos: transición controlada a ambos rojos.

## Validación y Git

- Inspeccionar estructura, CMake, código, target y herramientas antes de editar.
  Consultar documentación oficial y cabeceras/Kconfig de versiones seleccionadas.
- En cámara ejecutar `idf.py --version`, `idf.py set-target esp32`, `idf.py build`.
  Resolver errores propios. Si no es posible, investigar entorno oficial compatible
  sin alterar innecesariamente el sistema e informar compilación pendiente.
- Documentar `idf.py -p COMx -b 115200 flash` e `idf.py -p COMx monitor`;
  sustituir COMx por el puerto real.
- Trabajar en rama independiente, por ejemplo `feat/camera-capture-1-1`, nunca
  directamente en `master`. No eliminar archivos existentes sin justificar.
- Preparar PR hacia `master`. Entregar archivos creados/modificados, implementación,
  decisiones, compilación real, pasos de prueba, pendientes y aceptación alcanzada.

Fuentes: https://github.com/espressif/esp32-camera,
https://components.espressif.com/components/espressif/esp32-camera,
https://docs.espressif.com/projects/esp-idf/.
