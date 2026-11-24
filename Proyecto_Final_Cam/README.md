# Práctica 1.1 — Cámara OV2640/OV3660 y captura JPEG

Inicializa una OV2640 u OV3660 y adquiere una imagen QVGA por intento. Imprime contador,
resolución, formato, tamaño y memoria; devuelve el framebuffer al controlador y
espera 5000 ms antes del siguiente intento. No guarda JPEG ni los envía por UART.
El monitor muestra metadatos, no una imagen visualizable.

## Requisitos y dependencias

- ESP32-CAM clásica con OV2640 u OV3660, PSRAM y pinout AI Thinker. El usuario
  confirmó por UART una OV3660 (PID 0x3660); la captura aún debe comprobarse.
- Base ESP32-CAM-MB CH340G, cable USB de datos y alimentación estable adecuada a
  la base. El UART del ESP32 usa lógica de 3.3 V.
- VS Code con extensión oficial ESP-IDF; instalación efectiva **ESP-IDF v6.0.2**,
  Python del entorno IDF, CMake, Ninja y compilador Xtensa instalados.
- Acceso al registro oficial de componentes durante la primera configuración.

`main/idf_component.yml` fija `espressif/esp32-camera ==2.1.9` y admite IDF
`>=6.0.2,<6.1.0`. La versión del controlador se verificó en el
[registro oficial](https://components.espressif.com/components/espressif/esp32-camera/versions/2.1.9/readme).
Su [manifiesto](https://github.com/espressif/esp32-camera/blob/v2.1.9/idf_component.yml)
requiere IDF ≥5.1 y arrastra `esp_jpeg`; su
[CMake](https://github.com/espressif/esp32-camera/blob/v2.1.9/CMakeLists.txt)
incluye dependencias específicas para IDF ≥6.0. Se comprobó la estructura
`camera_config_t` en la
[cabecera de esa versión](https://github.com/espressif/esp32-camera/blob/v2.1.9/driver/include/esp_camera.h).
La declaración de compatibilidad se complementa con el resultado real de compilación
indicado al final de esta guía.

Component Manager descarga `managed_components/` y genera `dependencies.lock`.
Versionar el bloqueo generado, nunca inventarlo ni editar sus hashes. Los
componentes descargados y `build/` están ignorados. El código de aplicación es C;
el componente oficial incluye internamente fuentes C++ de conversión.

## Pinout inicial

Definido únicamente en `main/camera_pinout.h`. Verificar modelo y conexiones antes
de alimentar. No confundir el ejemplo WROVER del componente con AI Thinker.

| Señal de cámara | GPIO ESP32 |
| --- | --- |
| PWDN | 32 |
| RESET | -1 (reinicio por software) |
| XCLK | 0 |
| SIOD / SDA SCCB | 26 |
| SIOC / SCL SCCB | 27 |
| D0 | 5 |
| D1 | 18 |
| D2 | 19 |
| D3 | 21 |
| D4 | 36 |
| D5 | 39 |
| D6 | 34 |
| D7 | 35 |
| VSYNC | 25 |
| HREF | 23 |
| PCLK | 22 |

## Configuración y PSRAM

| Parámetro | Valor |
| --- | --- |
| Target | `esp32` |
| Sensores aceptados | OV2640 (PID 0x26) u OV3660 (PID 0x3660); se registra el modelo real |
| Resolución / formato | QVGA 320 × 240 / `PIXFORMAT_JPEG` |
| XCLK / calidad JPEG | 20 MHz / 12 (menor número implica mayor calidad) |
| Buffers / ubicación | 1 / `CAMERA_FB_IN_PSRAM` |
| Adquisición | `CAMERA_GRAB_WHEN_EMPTY` |
| LEDC | `LEDC_TIMER_0` / `LEDC_CHANNEL_0` |
| Tamaño buffer JPEG | Automático (`jpeg_buffer_size=0`) |
| Espera entre intentos | 5000 ms usando `vTaskDelay()` |

La espera empieza al terminar cada intento; el intervalo entre registros también
incluye captura y diagnóstico, y puede aumentar si el controlador agota su espera.
`WHEN_EMPTY` puede entregar una imagen ya encolada; esta práctica no garantiza una
imagen tomada exactamente en el instante del registro ni una cadencia de tiempo real.

`sdkconfig.defaults` usa opciones comprobadas en Kconfig de IDF 6.0.2 para ESP32:
`CONFIG_SPIRAM`, autodetección, inicialización al arrancar, prueba de memoria e
integración con `malloc`. Se elige flash/PSRAM a 40 MHz como punto conservador de
partida para QVGA; XCLK permanece a 20 MHz. No se activa PSRAM DMA de S2/S3.
Ver [soporte oficial de RAM externa](https://docs.espressif.com/projects/esp-idf/en/v6.0.2/esp32/api-guides/external-ram.html).

`CONFIG_SPIRAM_IGNORE_NOTFOUND=y` permite que la aplicación informe ausencia de
PSRAM sin reinicios por esa causa. **No permite capturar sin PSRAM**:
`camera_inicializar()` verifica inicialización, tamaño y memoria asignable antes
de llamar al controlador. No hay sustitución silenciosa por DRAM. El detector
de brownout permanece habilitado.

Los defaults solo se aplican al generar `sdkconfig`; una configuración existente
puede prevalecer. En tal caso revisar `idf.py menuconfig` → Component config →
ESP PSRAM y ejecutar de nuevo `idf.py set-target esp32` para regenerar configuración
si corresponde; este último comando limpia `build` y conserva `sdkconfig.old`.
No ejecutar sobre una compilación que se necesite conservar.

## Compilar desde Visual Studio Code

1. Abrir **la carpeta `Proyecto_Final_Cam`** en VS Code.
2. Seleccionar la instalación ESP-IDF v6.0.2 ya disponible. No reinstalar ni cambiar
   la configuración global para este proyecto.
3. Ejecutar **ESP-IDF: Open ESP-IDF Terminal** desde la paleta de comandos.
4. En esa terminal, estando en la carpeta que contiene el CMake raíz de cámara:

```powershell
idf.py --version
idf.py set-target esp32
idf.py build
```

La primera línea debe mostrar `ESP-IDF v6.0.2`. El target también queda validado
por el CMake raíz; no seleccionar `esp32c6` en este proyecto. El gestor resolverá
automáticamente la dependencia; no hace falta `add-dependency` otra vez.
El éxito se identifica por `Project build complete` y el archivo
`build/Proyecto_Final_Cam.bin`.

En otros sistemas usar la terminal activada por `export.sh`/`export.ps1` de la
instalación correspondiente. No copiar rutas absolutas de Windows a CMake.
Los archivos OpenOCD heredados son para depuración; la prueba actual usa UART.

## Programar por UART y observar

1. Instalar el controlador CH340G solo si el dispositivo no aparece. Consultar el
   puerto en Administrador de dispositivos → Puertos (COM y LPT), y cerrar otras
   terminales que lo estén usando.
2. Insertar la cámara en la base con la orientación correcta y verificar la cinta
   de la cámara con la placa sin alimentación.
3. Sustituir `COMx` por el puerto real en los comandos siguientes:

```powershell
idf.py -p COMx -b 115200 flash
idf.py -p COMx monitor
```

Si la base controla automáticamente BOOT/RESET, el flasheo reiniciará la placa.
Si se queda en `Connecting...`, entrar manualmente al cargador: mantener GPIO0
a GND durante RESET/encendido según los botones/puentes de la base. Finalizada la
programación, **retirar el puente GPIO0–GND** y reiniciar para ejecutar: GPIO0
debe quedar libre porque genera XCLK. No retirar ni conectar la cinta con alimentación.
El monitor usa la velocidad de consola predeterminada de 115200; salir con `Ctrl+]`.

## Resultado esperado y prueba manual

Ejemplo **ilustrativo**, no transcripción de hardware probado; tamaños y memoria varían:

```text
I (...) practica_1_1: Práctica 1.1; ESP-IDF v6.0.2; target esp32
I (...) camera_driver: PSRAM detectada: ... bytes
I (...) camera_driver: OV3660 inicializada (PID=0x3660): JPEG QVGA 320x240, calidad=12, XCLK=20 MHz, 1 framebuffer en PSRAM.
I (...) camera_driver: Imagen #1: 320x240, formato=JPEG (...), tamaño=... bytes
I (...) camera_driver: RAM interna: libre=..., mínimo=..., bloque mayor=... bytes
I (...) camera_driver: PSRAM: libre=..., mínimo=..., bloque mayor=... bytes
```

Mantener el monitor al menos un minuto. Confirmar contador creciente, 320x240,
JPEG, longitud mayor que cero y nuevas líneas aproximadamente cada cinco segundos.
Mover juguetes ante la cámara puede variar el tamaño JPEG; esta práctica no permite
evaluar visualmente enfoque ni contenido. Observar memoria después de cada retorno:
no debería existir una caída sostenida por cada captura. El mínimo histórico puede
disminuir al arrancar sin que eso pruebe una fuga.

Si falla una captura, debe aparecer error y aviso de reintento con espera de 5000 ms;
no aumenta el contador. Ante PSRAM ausente, sensor no admitido o fallo de inicio, se
debe informar la causa/código y no aparecer ninguna línea `Imagen #`.
No desconectar el sensor en caliente para provocar fallos.

## Funciones y decisiones

- `app_main()` registra versión/memoria, comprueba inicialización y ejecuta el bucle
  en su propia tarea FreeRTOS. No necesita otra tarea, cola ni temporizador en 1.1.
- `camera_inicializar()` verifica PSRAM, prepara `camera_config_t`, comprueba
  `esp_camera_init()` y valida que el sensor sea OV2640 u OV3660. Registra su modelo
  real; ante otro sensor libera el controlador e informa el error. No continúa
  capturando tras un fallo.
- `camera_capturar_registrar()` exige inicialización, obtiene un framebuffer,
  comprueba metadatos y registra una captura correcta. Usa un único punto de
  `esp_camera_fb_return()` para todos los buffers adquiridos, incluso descartados.
  No conserva punteros después del retorno. La comprobación de metadatos no
  sustituye una futura decodificación/inspección visual del JPEG.
- `camera_registrar_memoria()` muestra bytes libres, mínimo histórico y mayor
  bloque contiguo para memoria interna y externa.

## Problemas frecuentes

| Síntoma | Revisión |
| --- | --- |
| `idf.py` no reconocido | Abrir terminal ESP-IDF, comprobar instalación seleccionada y `idf.py --version`; no usar Python ajeno al entorno |
| Error al resolver el componente | Revisar conexión/proxy y versión del manifiesto; no reemplazar el bloqueo con hashes manuales |
| Target incorrecto | Ejecutar `idf.py set-target esp32` dentro de cámara |
| PSRAM ausente o error de prueba de memoria | Confirmar variante física y opciones generadas, alimentación y montaje; no asumir que toda ESP32-CAM lleva PSRAM funcional |
| `Camera probe failed` / sensor no detectado | Revisar cinta, cierre del conector, orientación, modelo y pinout con placa apagada |
| `Se esperaba OV2640; PID detectado=0x3660` | Versión inicial que solo aceptaba OV2640. La placa reporta OV3660; recompilar y programar la versión corregida que acepta ambos modelos |
| `ov3640: Mismatch PID=0x3660` seguido de `Detected OV3660 camera` | Es el intento de identificación de otro modelo dentro del componente; la detección posterior de OV3660 es la relevante |
| `Virtual address not enough ... 4MB is mapped` con prueba de PSRAM correcta | Se detectan 8 MiB físicos pero solo se mapean 4 MiB al heap. En el registro aportado hay memoria suficiente para el framebuffer QVGA; no causó la detención |
| Flash detectada de 4096k y cabecera de 2048k | El firmware utiliza un límite de 2 MiB sobre flash física de 4 MiB. La partición actual cabe; no causó la detención. Para usar toda la flash seleccionar 4 MB en `idf.py menuconfig` → Serial flasher config → Flash size y recompilar/programar |
| Aviso GDB `COMx`, seguido de uso del nombre extendido de COM12 | El monitor adapta el nombre del puerto para Windows; si llegan los registros, no es un fallo de conexión |
| `ESP_ERR_NO_MEM` | Consultar memoria/bloque mayor, defaults PSRAM y framebuffer único; no aumentar resolución |
| Timeout/imagen descartada | Revisar alimentación, cinta, pinout y XCLK; el bucle reintenta sin perder el buffer adquirido |
| Brownout o reinicios | Corregir fuente, cable y conexiones; mantener detector habilitado |
| `Connecting...` o placa en modo descarga | Revisar COM, cable de datos, BOOT/RESET y puente GPIO0; liberarlo para ejecución |
| Puerto ocupado / acceso denegado | Cerrar monitor anterior y otras aplicaciones serie; comprobar puerto real |
| Rutas/herramientas heredadas inválidas | Seleccionar instalación local desde la extensión; el firmware y CMake no dependen de esas rutas |

## Validación registrada

Verificación inicial del **24 de noviembre de 2026** (versión `9d079b5`, anterior
a la corrección de aceptación de OV3660):

| Comprobación | Resultado real |
| --- | --- |
| Versión efectiva (etiqueta Git y `idf.py --version`) | ESP-IDF v6.0.2 |
| Herramientas | Python 3.11.15, CMake 4.0.3, Ninja 1.12.1, GCC Xtensa 15.2.0 |
| `idf.py set-target esp32` | Finalizó con código 0 |
| Component Manager | Cámara 2.1.9, esp_jpeg 1.3.2; `dependencies.lock` generado |
| Opciones generadas | Target esp32, PSRAM inicializada al arranque, 40 MHz, brownout habilitado |
| `idf.py build` | Código 0; `Project build complete` |
| Binario de aplicación | `build/Proyecto_Final_Cam.bin`: 306688 bytes (0x4ae00); 71 % libre en partición de 1 MiB |
| Revisión de cambios | `git diff --check` sin errores; C6 sin modificaciones |
| Programación UART | El usuario aportó escritura verificada por hash y arranque por COM12 |
| Prueba de memoria y detección | PSRAM pasó la prueba; el componente detectó e inicializó OV3660 |
| Captura física | Detenida por validación exclusiva de OV2640; pendiente con la corrección |

La primera descarga falló por la restricción de red del entorno aislado; se repitió
con acceso autorizado al registro y el gestor resolvió las dependencias. Para usar
la instalación existente se prepararon variables **solo en los procesos de
validación**; no se modificaron perfiles ni configuración global de ESP-IDF.
Durante la configuración aparecieron avisos de Kconfig de componentes del SDK y
un aviso de símbolos ROM para GDB por una variable inicialmente ausente. Se indicó
la ruta ROM instalada en el proceso de compilación; la construcción final terminó
correctamente. No hubo errores de compilación en las fuentes de esta práctica.

### Corrección a partir del registro del usuario

El log aportado confirma ESP32-D0WD-V3, flash física de 4 MiB y PSRAM de 8 MiB
con 4 MiB mapeados. El componente informó `Detected OV3660 camera` y `cam config ok`.
Después, la aplicación rechazó PID 0x3660 al exigir OV2640; ese rechazo produjo
`ESP_ERR_NOT_SUPPORTED (0x106)` y el retorno de `app_main()`.

Se mantienen las comprobaciones y se admiten explícitamente **OV2640 y OV3660**,
ambas soportadas por esp32-camera 2.1.9. El mensaje de inicialización muestra el
modelo detectado en lugar de anunciar siempre OV2640. La configuración de captura
no cambia. Los demás modelos siguen rechazándose.

La corrección se recompiló con **ESP-IDF v6.0.2**, target `esp32`: `idf.py build`
terminó con código 0 y `Project build complete`. El binario corregido ocupa
**306752 bytes (0x4ae40)** y conserva 71 % libre en la partición. Se verificó que
`CONFIG_OV2640_SUPPORT` y `CONFIG_OV3660_SUPPORT` están habilitados. El bloqueo de
dependencias, los defaults y el firmware C6 permanecen sin cambios. La captura en
hardware con este binario sigue pendiente de la prueba del usuario.

Para probar la corrección, salir del monitor con `Ctrl+]` y ejecutar desde la
terminal ESP-IDF de `Proyecto_Final_Cam`:

```powershell
idf.py build
idf.py -p COM12 -b 115200 flash
idf.py -p COM12 monitor
```

Debe aparecer `OV3660 inicializada (PID=0x3660)` y después `Imagen #1`, `Imagen #2`,
etc. Esta salida es **esperada**, aún no comprobada en hardware con la corrección.
No hace falta repetir `set-target` para este cambio de código.

## Criterios de aceptación

| Criterio | Evidencia / límite |
| --- | --- |
| Estructura existente, ESP-IDF nativo y target esp32 | Proyectos conservados; CMake y compilación verificados |
| Dependencia oficial reproducible | Manifiesto fijo y bloqueo generado incluidos |
| OV2640/OV3660, JPEG QVGA y configuración solicitada | Sensor OV3660 identificado por el usuario; captura con corrección pendiente |
| Registro de capturas y manejo de errores | El registro confirma parada ante sensor rechazado; capturas tras corregir pendientes |
| Devolución de framebuffers | Un único retorno común para cada adquisición no nula, incluso descartadas |
| Documentación reproducible | Pinout, PSRAM, compilación, UART, monitor y diagnóstico en esta guía |
| Alcance 1.1 | Sin funciones de etapas posteriores ni cambios en C6 |
| Separación entre compilación y funcionamiento físico | Usuario confirmó programación/arranque de versión inicial; capturas con corrección pendientes |
