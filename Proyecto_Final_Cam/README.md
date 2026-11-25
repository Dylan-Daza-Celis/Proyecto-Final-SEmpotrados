# Tarea 02 — Wi-Fi y fotografías por HTTP

Prácticas **1.2 y 1.3** sobre el controlador de cámara de 1.1. La ESP32-CAM sirve
una interfaz local para capturar, ver y descargar JPEG. La C6, la red neuronal,
OpenCV y el intercambio UDP de conteos siguen pendientes.

## Evidencia anterior y hardware

El usuario confirmó en 1.1 **19 capturas consecutivas con memoria estable**,
con dos avisos NO-SOI iniciales. No se había inspeccionado visualmente una foto.

| Dato | Hardware / configuración |
| --- | --- |
| ESP-IDF / target / UART | v6.0.2 / esp32 / COM12 |
| Chip / CPU | ESP32-D0WD revisión v3.1 / 160 MHz |
| Sensor físico | **OV3660, PID 0x3660**; el producto anunciaba OV2640 |
| Compatibilidad conservada | OV2640 y OV3660 por detección del componente oficial |
| Flash | 4 MiB físicos; esta tarea configura **4 MiB** (antes 2 MiB) |
| PSRAM | 8 MiB físicos, 4 MiB mapeados al heap; prueba previa correcta |
| Base | ESP32-CAM-MB USB-UART CH340G |

Se conserva JPEG QVGA 320 × 240 inicial, calidad 12, XCLK 20 MHz, un framebuffer en
PSRAM, CAMERA_GRAB_WHEN_EMPTY, LEDC_TIMER_0 y LEDC_CHANNEL_0. Flash y PSRAM siguen
a 40 MHz; brownout permanece habilitado.

### Pinout AI Thinker

Definido en `main/camera_pinout.h`. La detección previa funciona con estas
conexiones; la comprobación visual también verificará el bus de datos.

| Señal | GPIO | Señal | GPIO |
| --- | --- | --- | --- |
| PWDN | 32 | RESET | -1 (software) |
| XCLK | 0 | SIOD / SDA | 26 |
| SIOC / SCL | 27 | D0 | 5 |
| D1 | 18 | D2 | 19 |
| D3 | 21 | D4 | 36 |
| D5 | 39 | D6 | 34 |
| D7 | 35 | VSYNC | 25 |
| HREF | 23 | PCLK | 22 |

## Configurar y probar desde Visual Studio Code

1. Abrir **Proyecto_Final_Cam** y ejecutar **ESP-IDF: Open ESP-IDF Terminal**.
2. Confirmar la instalación efectiva y el target. Ejecutar `set-target` **antes de
   introducir credenciales**, porque regenera sdkconfig y limpia build:

   ```powershell
   idf.py --version
   idf.py set-target esp32
   idf.py menuconfig
   ```

3. En **Semáforo inteligente - conexión local**, introducir SSID y contraseña.
   Usar red de **2.4 GHz**. SSID: 1..32 bytes. Contraseña WPA2: 8..63 bytes.
   Una contraseña vacía selecciona red abierta. No se admiten WPA Enterprise,
   portales cautivos ni claves hexadecimales de 64 caracteres en esta versión.
4. Verificar **Serial flasher config → Flash size → 4 MB**.
   Verificar **Partition Table → Partition Table → Single factory app (large),
   no OTA**. La tabla oficial reserva 1500 KiB para la aplicación, conservando
   offsets de NVS y factory. El enlace con Wi-Fi completo dejaba solo 4 % libre
   en la partición anterior de 1 MiB; esta tabla da margen sin cambiar la cámara.
   En **Component config → ESP PSRAM** conservar soporte, inicialización al
   arrancar, memoria asignable, prueba y 40 MHz. Guardar y salir.
5. Compilar y programar:

   ```powershell
   idf.py build
   idf.py -p COM12 -b 115200 flash monitor
   ```

6. Si se usó puente GPIO0–GND para entrar al cargador, retirarlo y reiniciar para
   ejecutar: GPIO0 genera XCLK. Cerrar monitores anteriores si COM12 está ocupado.
7. Esperar en el monitor `IPv4: ... — abrir http://.../` y el mensaje de inicio
   HTTP. La cámara se estabiliza antes de iniciar la conexión.
8. Abrir **http://IP-DE-LA-CAMARA/** desde una computadora en la misma LAN.
   No usar HTTPS. Si el router aísla clientes o la computadora está en otra red,
   la dirección puede no ser accesible.
9. Pulsar **Capturar imagen**, mover físicamente un juguete y capturar otra vez.
   Confirmar que cambian la escena y el identificador.
10. Comparar QVGA, VGA y SVGA con **Aplicar ajustes** y una nueva captura.
    Probar calidad 12, 20 y 30; descargar el JPEG y abrirlo en el visor de la PC.
    Observar encuadre, nitidez, orientación y artefactos: el tamaño por sí solo
    no acredita calidad visual.

Para compilaciones posteriores no hace falta repetir set-target. Los defaults
solo se aplican al generar sdkconfig; si se conserva una configuración previa,
verificar el tamaño Flash de 4 MB en menuconfig. No se requieren rutas absolutas
locales en CMake ni reinstalar ESP-IDF.

### Credenciales locales

Los valores Kconfig se guardan en **sdkconfig**, ignorado por Git junto con
sdkconfig.old y build/. No copiar valores a sdkconfig.defaults ni a README.
`wifi_manager` no imprime SSID ni contraseña, y usa WIFI_STORAGE_RAM para no
persistirlas mediante el driver Wi-Fi. Los binarios y cabeceras generados sí
incorporan los valores compilados: conservarlos localmente. No se han configurado
credenciales reales del usuario durante el desarrollo.

## Interfaz y endpoints

La interfaz HTML/CSS/JavaScript se incluye mediante **EMBED_TXTFILES**. Funciona
sin Internet ni frameworks externos. Muestra conexión, modelo, configuración,
capturas correctas/fallidas y memoria. La descarga usa la última imagen mostrada,
sin solicitar otra foto.

| Método / ruta | Respuesta |
| --- | --- |
| GET / | Interfaz HTML embebida |
| GET /capture | JPEG; Content-Type image/jpeg; X-Capture-Id y nombre captura-ID.jpg |
| GET /status | JSON con estado, sensor/PID, dimensiones, calidad, contadores, memoria y tiempo encendido |
| POST /control | Aplica configuración autorizada y devuelve el mismo JSON de estado |

Todas las respuestas incluyen Cache-Control no-store/no-cache, Pragma y Expires.
La interfaz también solicita con cache no-store y distingue cada imagen por su ID.
La vista continua solicita otra captura **un segundo después de terminar** la
operación anterior; la tasa puede ser menor de 1 imagen/s. Se puede detener sin
abortar el envío que está terminando. No se implementa streaming MJPEG.

### Contrato de POST /control

Content-Type exacto: `application/x-www-form-urlencoded`.
Cuerpo de menos de 80 bytes, **dos campos en este orden**, sin campos adicionales:

```text
resolution=VGA&quality=12
```

- resolution: QVGA (320 × 240), VGA (640 × 480) o SVGA (800 × 600).
- quality: entero de 10 a 40, sin signos, decimales ni ceros iniciales.
- Menor número significa más calidad y normalmente más bytes.
- Campos desconocidos/duplicados, NUL incrustado y valores fuera de rango se
  rechazan con 400. Tipo de contenido incorrecto: 415.
- Un cuerpo no admitido cierra la sesión tras responder, sin drenar longitudes
  arbitrarias. Recepción incompleta/timeout: 408 o cierre de conexión.
- Fallo de cámara o mutex ocupado: 503. No se aceptan nombres arbitrarios de
  funciones o registros del sensor.

Ejemplos opcionales desde PowerShell, sustituyendo IP-DE-LA-CAMARA:

```powershell
curl.exe -i http://IP-DE-LA-CAMARA/status
curl.exe -D cabeceras.txt -o foto.jpg http://IP-DE-LA-CAMARA/capture
curl.exe -i -X POST http://IP-DE-LA-CAMARA/control -H "Content-Type: application/x-www-form-urlencoded" --data "resolution=SVGA&quality=12"
curl.exe -i -X POST http://IP-DE-LA-CAMARA/control -H "Content-Type: application/x-www-form-urlencoded" --data "resolution=UXGA&quality=99"
```

El último ejemplo debe responder 400 y conservar la configuración previa. El
contador indica JPEG adquiridos y validados, incluso si después falla su entrega;
no representa descargas completadas ni cuenta descartes de estabilización/frescura.

## Organización, sincronización y memoria

- **main.c:** inicializa cámara/Wi-Fi y supervisa el único servidor. Inicia HTTP
  solo con IPv4 válida y lo detiene al detectar pérdida de IP/conexión.
- **wifi_manager.c:** esp_netif, esp_event, esp_wifi, NVS y grupo de eventos
  FreeRTOS. Una tarea reconecta con pausas de 1, 2, 4, 8, 16 y hasta 30 s; se
  restablece la demora al obtener IP. La espera ocurre fuera del bucle de eventos.
  Si NVS está llena o tiene formato incompatible, se informa y se reinicializa
  borrando esa partición. Una configuración vacía/inválida detiene el inicio.
- **camera_driver.c:** conserva pinout e inicialización de 1.1. Agrega mutex con
  espera máxima de 1 s, adquisición, estado y reconfiguración. La función
  camera_capturar_registrar sigue disponible para diagnóstico, usando el mismo
  mutex; ya no se ejecuta el bucle periódico de 1.1.
- **http_server.c:** handlers oficiales y envío síncrono del JPEG sin copiarlo
  a otro buffer. El framebuffer sigue válido y el mutex permanece tomado hasta
  retornar httpd_resp_send; se devuelve también ante desconexión o error.
- **web/index.html:** una sola operación de red a la vez, timeout de 30 s,
  decodificación de JPEG por el navegador antes de reemplazar la foto y liberación
  de la object URL anterior. Solo se conserva la última foto.

Con un framebuffer y WHEN_EMPTY puede existir una imagen encolada de la pausa
anterior. Por eso se adquiere/devuelve una antes de obtener la que se enviará.
No se promete una fotografía tomada exactamente al hacer clic. Se comprueban
dimensiones, formato, buffer y marcadores **FF D8 / FF D9**; eso detecta truncados
e incoherencias, pero no sustituye la inspección visual/decodificación completa.

### Cambiar resolución de forma segura

No basta cambiar registros del sensor: el componente calcula el tamaño del
buffer al inicializarse (automático, según resolución). El controlador toma el
mutex, desinicializa y reinicializa la cámara con la nueva resolución/calidad,
conservando el resto de parámetros. No hay framebuffer prestado durante el cambio.
Si falla, intenta restaurar la configuración anterior **una vez**. Si también
falla la restauración, /status informa camera_ready=false; un control válido puede
intentar recuperarla o se puede reiniciar la placa. No hay bucle infinito.

El servidor atiende solicitudes secuencialmente, con 3 sockets y pila de 8192
bytes. Los timeouts de envío/recepción son 5 s por espera de socket; no constituyen
un plazo global de una descarga. Cada esp_camera_fb_get espera hasta unos 4 s en
el componente seleccionado; una captura tiene como máximo dos adquisiciones y
una estabilización tiene dos intentos. Una cámara lenta puede retrasar /status.
La vista continua de una pestaña evita acumular peticiones; varias pestañas
comparten la misma cámara y no aumentan su capacidad.

### NO-SOI y estabilización

En cam_hal.c de esp32-camera 2.1.9, NO-SOI significa que no se encontró la cabecera
JPEG esperada al comienzo del flujo. Los dos avisos iniciales del usuario son
compatibles con un transitorio al arrancar el sensor; esa causa no está demostrada
con una medición de hardware. Se añade una pausa de 200 ms y se descartan **dos**
adquisiciones al iniciar/reconfigurar, registrando el resultado y devolviendo
todos los buffers obtenidos. No se cambia el nivel de log ni se ocultan errores
del componente. Si los avisos persisten, revisar alimentación, cinta, pinout y
escena; no aumentar indefinidamente los descartes.

## Validación y seguimiento

| Prueba | Estado |
| --- | --- |
| 1.1: OV3660, 19 capturas y memoria estable | Confirmado por el usuario |
| Fotografía de 1.1 visualmente correcta | Aún no comprobada |
| ESP-IDF v6.0.2 y target esp32 | Comprobados localmente |
| idf.py set-target esp32 | Finalizó con código 0 |
| Configuración generada | Flash 4 MiB, factory 1500 KiB, PSRAM a 40 MHz, brownout habilitado |
| Compilación sin SSID configurado | Código 0; binario 445600 bytes |
| Enlace completo con configuración Wi-Fi ficticia local | Código 0; Project build complete; 1006592 bytes (0xf5c00), 34 % libre en factory de 1500 KiB |
| JavaScript real de la interfaz | 5 pruebas automatizadas correctas con Node, sin dependencias |
| Wi-Fi real, IPv4, HTTP y descarga en la placa | Pendientes de la prueba física del usuario |
| QVGA/VGA/SVGA, cambios de escena y estabilidad con Wi-Fi | Pendientes de prueba física |
| C6 y dependencias gestionadas | Sin cambios |

Las pruebas de JavaScript usan respuestas/DOM simulados: verifican solicitudes
secuenciales, detener, manejo de HTTP 503, validación de calidad y liberación de
blobs tras reemplazo/error de decodificación. No son una prueba de navegador ni
de la placa. Ejecutarlas opcionalmente desde la raíz:

```powershell
node --test Proyecto_Final_Cam/tests/web_ui.test.cjs
```

Node no es dependencia del firmware ni requisito para programarlo.

Verificación realizada el **24 de noviembre de 2026** con ESP-IDF v6.0.2.
El gestor reutilizó el bloqueo y los componentes ya descargados al no disponer
de red en el entorno aislado. Los avisos Kconfig heredados del SDK no impidieron
la compilación. La configuración final y el binario indican flash de 4 MiB y
tabla oficial partitions_singleapp_large.csv. Los valores Wi-Fi ficticios de
validación se retiraron de sdkconfig/sdkconfig.old antes de entregar los cambios;
es obligatorio introducir la red real y reconstruir antes de programar.

### Pruebas físicas de aceptación

1. Capturar y abrir un JPEG descargado; mover un juguete y comprobar cambio real.
2. Aplicar QVGA, VGA y SVGA alternadamente; comprobar dimensiones decodificadas.
3. Mantener vista continua al menos 10 minutos. Comparar /status tras calentamiento
   y después de volver a la misma resolución: no debería haber caída sostenida de
   memoria por captura. Los mínimos históricos pueden bajar sin indicar una fuga.
4. Detener vista continua: debe terminar la operación en curso y cesar /capture.
5. Desconectar/reconectar el punto de acceso y verificar nuevos mensajes IPv4,
   reconexión con demora y una sola instancia del servidor. Usar la IP actual.
6. Cerrar el navegador durante una descarga; volver a abrir y capturar.
7. Enviar controles inválidos; verificar 400/415 sin cambios de parámetros.
8. Registrar resultados reales antes de dar por cumplidos los criterios de
   fotografía visible, descarga válida, reconexión y memoria estable de la tarea 02.

## Diagnóstico y limitaciones

| Síntoma | Revisión |
| --- | --- |
| Solicita configurar SSID/contraseña | Abrir menuconfig y guardar datos locales antes de compilar/programar |
| No obtiene IP | Red 2.4 GHz, credenciales, señal y DHCP; el monitor muestra motivo de desconexión, no la clave |
| No abre la página | Misma LAN, IP actual, HTTP puerto 80 y aislamiento de clientes del router |
| Sigue apareciendo flash 2 MB | Configuración sdkconfig previa; seleccionar 4 MB en menuconfig y reconstruir/programar |
| Aviso de 8 MiB PSRAM con 4 MiB mapeados | Limitación del espacio de direcciones de ESP32; memoria utilizable suficiente para estas resoluciones |
| HTTP 503 / captura inválida | Revisar monitor; SOI/EOI, memoria, alimentación y cinta; reintentar o recuperar mediante control válido |
| JPEG de SVGA falla en escenas complejas | El buffer es finito; probar calidad 20–30 o resolución menor, y anotar el resultado |
| Brownout/reinicio | Corregir fuente/cable; mantener detector habilitado |
| COM12 ocupado o Connecting... | Cerrar monitor previo; revisar cable de datos y BOOT/RESET de la base |

HTTP local sin autenticación ni TLS. No se guarda una galería, no hay MJPEG ni
detección de vehículos en esta etapa. Aún no se ha probado el conjunto Wi-Fi +
cámara en hardware: no se afirma ausencia de fugas ni calidad visual sin esa prueba.

## Referencias oficiales

- [HTTP Server de ESP-IDF 6.0.2](https://docs.espressif.com/projects/esp-idf/en/v6.0.2/esp32/api-reference/protocols/esp_http_server.html).
- [Ejemplo Wi-Fi STA de ESP-IDF 6.0.2](https://github.com/espressif/esp-idf/tree/v6.0.2/examples/wifi/getting_started/station).
- [Componente esp32-camera 2.1.9](https://components.espressif.com/components/espressif/esp32-camera/versions/2.1.9/readme).
- [Gestión de JPEG y NO-SOI](https://github.com/espressif/esp32-camera/blob/v2.1.9/driver/cam_hal.c).
- [RAM externa de ESP32](https://docs.espressif.com/projects/esp-idf/en/v6.0.2/esp32/api-guides/external-ram.html).
