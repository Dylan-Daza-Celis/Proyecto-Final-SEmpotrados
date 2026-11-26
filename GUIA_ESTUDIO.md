# Guía de estudio — semáforo inteligente con ESP-IDF

Esta guía corresponde a `refactor/estructura-didactica-espidf`, basada en
`fe35f06` de `feat/integration-udp-07`. Reorganiza el firmware para estudiarlo;
conserva el protocolo, los pines, el algoritmo y los tiempos de esa referencia.
Los resultados de validación y el mapa de traslados están al final.

## 1. Arquitectura completa

```text
ESP32-CAM / sensor -> JPEG por HTTP -> PC / YOLO11x / dos ROI
                                             |
                               secuencia,N1,N2,valido por UDP
                                             v
                              ESP32-C6 / prioridad / estados
                                             |
                                      seis LED por GPIO
```

Son dos proyectos ESP-IDF independientes y una aplicación Python. La cámara
adquiere imágenes; el PC reconoce y cuenta; C6 decide qué carril abre y durante
cuánto tiempo. El PC no envía órdenes «enciende GPIO10». Envía observaciones.
La validación y las restricciones de las salidas permanecen en C6.

La maqueta mide 45 × 44 cm. Dos entradas convergen en una salida. ROI1 cubre la
espera izquierda y ROI2 la derecha; convergencia y salida quedan excluidas.

## 2. Hardware de los dos sistemas empotrados

La cámara usa ESP32 clásico, target `esp32`, y pinout inicial AI Thinker. El
firmware acepta OV2640 u OV3660; el usuario detectó OV3660, PID `0x3660`.
Los pines privados están ahora dentro de `camera_driver.c`:

| Señal | GPIO |
| --- | --- |
| PWDN / RESET / XCLK | 32 / -1 / 0 |
| SCCB SDA / SCL | 26 / 27 |
| D0 / D1 / D2 / D3 | 5 / 18 / 19 / 21 |
| D4 / D5 / D6 / D7 | 36 / 39 / 34 / 35 |
| VSYNC / HREF / PCLK | 25 / 23 / 22 |

`RESET=-1` indica que no se asigna un GPIO de reset. XCLK se configura a 20 MHz.
Conservar flash de 4 MiB y PSRAM habilitada; no trasladar estas opciones a C6.

C6 usa target `esp32c6`. Sus pines provisionales están en `semaforo_gpio.h`:

| Carril | Rojo | Amarillo | Verde |
| --- | --- | --- | --- |
| 1 | GPIO2 | GPIO3 | GPIO10 |
| 2 | GPIO11 | GPIO18 | GPIO19 |

Cada LED lleva **su propia resistencia de 330 Ω**: GPIO → resistencia → ánodo;
cátodo a GND común. El nivel activo es alto. Confirmar variante, esquema,
polaridad y alimentación antes de habilitar salidas: variantes SiP pueden no
exponer GPIO10/11. El validador del SDK no conoce todo el cableado de la placa.

## 3. Función y módulos de ESP32-CAM

Leer en este orden:

1. [main.c](Proyecto_Final_Cam/main/main.c): coordina el arranque y la presencia de IP.
2. [camera_driver.c](Proyecto_Final_Cam/main/camera_driver.c): PSRAM, sensor, mutex y capturas.
3. [wifi_manager.c](Proyecto_Final_Cam/main/wifi_manager.c): STA, eventos y reconexión.
4. [http_server.c](Proyecto_Final_Cam/main/http_server.c): endpoints y envío HTTP.

Esas tres responsabilidades se conservan separadas. No se copiaron a un único
archivo grande: tienen ciclos de vida diferentes y el servidor necesita acceder
a la cámara mediante una interfaz protegida. La función de diagnóstico de
captura de la práctica 1.1 sigue disponible, pero no existe otro bucle periódico
que compita con el servidor HTTP por el framebuffer.

## 4. Framebuffer, JPEG y PSRAM

Un `camera_fb_t` describe un framebuffer adquirido del controlador oficial:
puntero a bytes, longitud, dimensiones y formato. No es una imagen que se pueda
conservar indefinidamente después de devolver su buffer.

`camera_inicializar()` verifica PSRAM y memoria asignable, crea `mutex_camara`
y configura JPEG QVGA 320 × 240, calidad 12, un framebuffer en PSRAM y
`CAMERA_GRAB_WHEN_EMPTY`. Se preservan las opciones VGA y SVGA por control HTTP.
El tamaño del JPEG es variable; no equivale al tamaño de una matriz BGR cruda.
JPEG permite enviar una representación comprimida; el PC la decodifica a BGR.
La PSRAM aloja el framebuffer y evita depender solo de la RAM interna para él.

`iniciar_controlador()` llama `esp_camera_init()`, verifica PID, guarda la
configuración y ejecuta `estabilizar_sensor()`: dos capturas descartadas,
devolviendo cada buffer obtenido. No se ocultan fallos de alimentación.

`camera_adquirir()` toma el mutex, descarta un buffer previo si existe y solicita
el siguiente. Comprueba SOI/EOI, JPEG y dimensiones. Si falla devuelve el buffer
obtenido y libera el mutex. En éxito deja ambos bajo responsabilidad del caller.
`capturar_imagen()` envía HTTP y llama `camera_liberar()` incluso si falla el
envío. Esta última devuelve el framebuffer y libera el mutex.

La reconfiguración también toma ese mutex. Detiene/inicializa el controlador y
trata de restaurar la configuración anterior si falla. Un solo buffer y un solo
mutex evitan adquisición, transmisión y reconfiguración simultáneas.

## 5. YOLO11x y conteo por ROI

El código Python en `Vision_Artificial/` no se modifica en esta tarea. Conserva
YOLO11x preentrenado original, CPU/PyTorch FP32, SVGA 800 × 600, `imgsz=960`,
confianza 0.15, IoU 0.45, clases COCO 2/3/5/7, NMS agnóstico desactivado,
tres calentamientos e hilos de referencia. No se entrenó ni cuantizó el modelo.

El trabajador carga un solo modelo y procesa una vez cada secuencia aceptada.
Hay un trabajo pendiente reemplazable, sin cola de imágenes ilimitada. Las cajas
se muestran sobre la fotografía que se analizó, no sobre otra imagen reciente.

Reconocer y clasificar por carril son pasos diferentes. Con ROI pendientes,
YOLO sigue publicando cajas, confianza y total diagnóstico; N1/N2 operativos
quedan ausentes. Con ambas ROI confirmadas y guardadas se asigna cada centro
flotante de caja a carril1, carril2 o fuera. No hay tracking ni acumulación.

Pausa, errores, imágenes antiguas o calibración inválida no representan cero
vehículos. V y cambios de resolución conservan la invalidación persistente;
Enter/G comprueban referencia y época. Se preservan coordenadas anteriores.

## 6. HTTP y UDP

CAM conserva cuatro endpoints:

| Endpoint | Responsabilidad |
| --- | --- |
| `GET /` | Página HTML/CSS/JS embebida, sin Internet |
| `GET /capture` | Un JPEG con `X-Capture-Id` |
| `GET /status` | Estado del sensor, resolución, contadores y memoria |
| `POST /control` | Validar resolución QVGA/VGA/SVGA y calidad 10..40 |

El PC adquiere fotografías HTTP individuales; no usa `VideoCapture` como si
`/capture` fuera vídeo continuo. `/status` no rejuvenece una fotografía.

UDP tiene un único flujo PC → C6, puerto inicial 5005:

```text
42,5,1,1
43,0,0,0
```

Son secuencia, N1, N2 y validez. El segundo ejemplo invalida; sus ceros no son una
medición. Se aceptan cuatro enteros ASCII canónicos, secuencia positiva de 64 bits,
conteos 0..1000, validez 0/1 y como máximo 48 bytes. No hay salto final ni espacios.
No existen solicitudes C6, sesiones, autenticación ni confirmaciones por red.

## 7. Configuración GPIO y adaptador oficial

`semaforo_gpio.h` contiene pines, colores, tipos y operaciones inyectables.
`semaforo_gpio.c` valida y aplica luces. `semaforo_gpio_idf.c` adapta dos APIs:

- `gpio_config()`: configura conjuntamente la máscara de salidas, sin pull-up,
  pull-down ni interrupciones GPIO.
- `gpio_set_level()`: modifica el nivel de un pin.

Antes de habilitar salidas se precargan registros: verdes/amarillos bajos y
rojos altos. Los cambios posteriores quitan incompatibles, aseguran el rojo
contrario y abren el carril seleccionado. Solo se escriben niveles que cambian.
El driver rechaza dos carriles no rojos simultáneos y estados inválidos.

Las escrituras de seis pines no son atómicas. Las pruebas inspeccionan cada
escritura intermedia mediante operaciones simuladas. Si una escritura falla,
`semaforo_gpio_seguro()` intenta todos los apagados y ambos rojos, bloquea el
driver y el propietario detiene su tarea. Recibir otro UDP no quita ese bloqueo.

## 8. Tareas FreeRTOS reales

| Proyecto/modo | Función de tarea | Pila ESP-IDF | Prioridad | Trabajo |
| --- | --- | --- | --- | --- |
| C6, todos | `tarea_controlador` | 5120 bytes | 5 | Único propietario GPIO |
| C6, simulación habilitada | `tarea_simulacion` | 3072 bytes | 3 | Escenarios hacia la cola |
| C6, conectado | `tarea_recepcion` | 4096 bytes | 4 | Socket y demanda UDP |
| C6, conectado | `reconectar` | 3072 bytes | 3 | Reintento STA espaciado |
| CAM | `tarea_reconexion` | 4096 bytes | 4 | Reconectar por eventos |

ESP-IDF también crea tareas propias, por ejemplo Wi-Fi, el event loop y HTTP.
`httpd_start()` usa configuración HTTP de pila 8192 bytes. Las tablas anteriores
describen creaciones explícitas del proyecto, no todo el sistema operativo.

El estilo se parece a la práctica: includes, constantes, tareas, colas y
`app_main`. Se conserva un propietario de los seis LED. Tres tareas por LED
permitirían órdenes incompatibles y harían más difícil preservar los despejes.

## 9. Parámetros de xTaskCreate

En C6, `app_main()` llama:

```c
xTaskCreate(tarea_controlador, "controlador_semaforos",
            PILA_CONTROL_BYTES, NULL, PRIORIDAD_CONTROL, NULL);
```

Los seis argumentos son función de entrada, nombre de diagnóstico, tamaño de
pila, puntero al parámetro, prioridad y salida opcional del identificador.
En ESP-IDF el tamaño se expresa en **bytes**, a diferencia de FreeRTOS vanilla.
La función de tarea recibe `void *`, no devuelve un resultado y debe permanecer
en su bucle o terminar con `vTaskDelete(NULL)`.

El simulador recibe la cola como parámetro. El resto usa NULL porque no necesita
un argumento. El último NULL significa que no se guarda un `TaskHandle_t`:
ninguna tarea del proyecto necesita suspender a otra. Se comprueba `pdPASS` al
crear tareas; fallar después de habilitar GPIO obliga a intentar rojos seguros.

## 10. Cola, mutex, eventos y sincronización

Son mecanismos diferentes:

- La cola C6 tiene longitud uno y almacena una copia de `demanda_vehicular_t`.
  `xQueueOverwrite()` conserva la observación más reciente. En demostración se
  usa `xQueueReceive(..., 0)`; en conectado se consulta `xQueuePeek(..., 0)` y se
  conserva un snapshot coherente durante la publicación.
- Una generación de invalidación separada impide que otro conteo sobrescriba un
  fallo crítico. El propietario comunica localmente la generación atendida solo
  después de aplicar estado seguro. No es un ACK por UDP.
- `portENTER_CRITICAL()` protege copias y contadores de recepción. El parsing,
  socket, cola, logs y GPIO se ejecutan fuera de esa sección breve.
- Los event groups representan conectividad Wi-Fi. Los callbacks del SDK
  actualizan esos bits y, en C6, invalidan demanda al perder Wi-Fi/IP.
- El mutex de CAM conserva exclusividad de cámara/buffer hasta finalizar el
  envío HTTP o la reconfiguración.

No se agregaron notificaciones directas entre tareas para imitar la práctica V.
La cola y los eventos existentes representan mejor estos datos y se preservan.

## 11. Temporización: esp_timer y vTaskDelay

`esp_timer_get_time()` devuelve microsegundos desde el arranque. Los helpers
`ahora_ms()` dividen entre 1000 y usan un reloj monótono local. No se comparan
relojes absolutos de PC y C6.

El controlador guarda `inicio_ms`. Al actualizar compara el tiempo transcurrido
con la duración de la fase; avanza como máximo una fase por llamada. Después de
escribir GPIO fija el inicio de la fase aplicada. Un despertar tardío prolonga
la fase y no «recupera tiempo» recortando amarillo o rojo total.

El propietario pide `vTaskDelay(pdMS_TO_TICKS(20))`. Esto cede CPU y permite
seguir observando fallos sin bloquear cinco o trece segundos dentro de un verde.
20 ms es el retardo solicitado, no una cota física garantizada: hay ticks,
ejecución, preempciones y logging. CAM espera IP hasta 1000 ms y añade un retardo
de 1000 ms por ciclo; no se debe describir ese ciclo como un periodo exacto de 1 s.

## 12. Máquina de estados

```text
ROJO_TOTAL_INICIAL
 -> VERDE_CARRIL_1 -> AMARILLO_CARRIL_1 -> ROJO_TOTAL_1_A_2
 -> VERDE_CARRIL_2 -> AMARILLO_CARRIL_2 -> ROJO_TOTAL_2_A_1
 -> VERDE_CARRIL_1 -> ...
```

`estado_semaforo_t` es un enum de estados. `controlador_actualizar()` determina
duración y siguiente estado. `controlador_luces()` traduce estado a dos colores,
sin tocar el driver. `ROJO_TOTAL_INICIAL` puede elegir primero el carril contrario
al último abierto después de una recuperación.

Convencional usa verdes configurados inicialmente en 5 s. Adaptativo simulado y
conectado usan la fórmula de prioridad; ambos conservan amarillo 2 s y rojo 1 s.
El simulador se deshabilita en conectado. En demostración, falta de demanda lleva
al mínimo; en conectado lleva al estado seguro, sin cambiar de modo automáticamente.

## 13. Algoritmo matemático de prioridad

En `prioridad_calcular()`, todos los vehículos pesan igual:

```text
D = N1 - N2
Si |D| < 2: ambos verdes seleccionables = 5000 ms
Si |D| >= 2:
  incremento = min((|D| - 2 + 1) * 2000, 13000 - 5000)
  verde favorecido = 5000 + incremento
  verde del otro carril = 5000
```

`D>0` favorece carril1 y `D<0` carril2. La alternancia nunca se elimina: se
extiende una duración, no se atiende repetidamente el mismo carril.
La aritmética intermedia usa 64 bits y satura con los límites configurados.

| N1 / N2 | D | Verde1 / verde2 |
| --- | --- | --- |
| 0 / 0 o 3 / 3 | 0 | 5 s / 5 s |
| 2 / 0 | 2 | 7 s / 5 s |
| 5 / 1 | 4 | 11 s / 5 s |
| 1 / 4 | -3 | 5 s / 9 s |
| 10 / 0 | 10 | 13 s / 5 s |

La duración se congela al entrar en verde. Nuevos conteos no reinician el
temporizador ni alteran los despejes. El intervalo nominal sin verde se mide
desde fin propio hasta inicio propio siguiente: `2+1+13+2+1=19 s`. Se valida
contra objetivo 20 s; no se garantiza durante seguro, fallos o retrasos.

## 14. Estado seguro y recuperación

En conectado, el inicio lógico es `ESTADO_SEGURO` con ambos rojos ya aplicados.
Se requiere una observación nueva válida recibida cuando el propietario ya
estaba seguro y había atendido la generación correspondiente. Después se vuelve
a rojo inicial completo antes de abrir.

Un `valido=0`, timeout local o pérdida Wi-Fi/IP retiene invalidación. Si había
verde se entra en amarillo completo; si ya estaba amarillo o rojo se termina
el despeje. Recibir un dato válido durante ese proceso no lo cancela ni sirve
por sí solo para recuperar: debe llegar otra observación desde seguro.

`aplicacion_conectada()` comprueba vigencia y generación antes y después de
GPIO mediante callbacks. Si el fallo se observa antes de abrir, conserva rojos.
Si llega durante el driver y hubo verde, inicia amarillo completo. Sigue
existiendo una ventana entre instrucciones; el software no garantiza ausencia
de pulso ni seguridad eléctrica durante reset, falta de alimentación o avería.

## 15. app_main y recorrido exacto hacia los GPIO

### ESP32-C6

```text
app_main
  -> xTaskCreate(tarea_controlador)
     -> comprobar CONFIG_SEMAFORO_PINOUT_CONFIRMADO
     -> semaforo_operaciones_idf() devuelve las operaciones oficiales
     -> semaforo_gpio_iniciar()
        -> semaforo_pines_validos() -> GPIO_IS_VALID_OUTPUT_GPIO
        -> operaciones.escribir() -> escribir() -> gpio_set_level [precarga]
        -> operaciones.habilitar() -> habilitar() -> gpio_config [habilita salidas]
        -> semaforo_gpio_aplicar(ambos rojos)
     -> controlador_iniciar()
     -> controlador_configurar_adaptativo() si corresponde
     -> validar coherencia temporal
     -> xQueueCreate(1, sizeof(demanda_vehicular_t))
     -> conectado: receptor_udp_iniciar() y wifi_manager_iniciar()
        -> tareas tarea_recepcion y reconectar
     -> simulación habilitada: xTaskCreate(tarea_simulacion)
     -> bucle de control y vTaskDelay
```

Sin confirmación de pines se elimina la tarea antes de habilitar salidas: en ese
caso no se promete que los LED estén rojos. La inicialización queda dentro del
propietario para que una única tarea sea responsable del driver desde el arranque.

Una transición conectada sigue este recorrido:

```text
tarea_controlador -> receptor_udp_estado() -> control_conectado_paso()
 -> controlador_recibir_demanda() / controlador_actualizar()
    -> seleccionar_verde() -> prioridad_calcular() al entrar a verde
 -> aplicacion_conectada()
    -> aplicar() -> controlador_luces() -> operaciones.escribir()
       -> escribir_fase() [callback de main]
       -> semaforo_gpio_aplicar() -> escribir_cambio()
       -> escribir() [adaptador IDF] -> gpio_set_level()
 -> receptor_udp_estado_controlador() [aviso local, no paquete]
 -> vTaskDelay()
```

En demostración se usa `controlador_actualizar()`, `controlador_luces()` y
`semaforo_gpio_aplicar()` directamente. La recepción solo decodifica y publica;
no participa en la cadena final de escrituras GPIO.

### ESP32-CAM

```text
app_main -> camera_registrar_memoria()
 -> camera_inicializar() -> iniciar_controlador() -> esp_camera_init()
 -> wifi_inicializar() -> NVS/netif/eventos/STA -> tarea_reconexion
 -> bucle: wifi_esperar_ip(1000)
    -> con IP: servidor_http_iniciar() -> httpd_start() y registrar cuatro rutas
    -> sin IP: servidor_http_detener() -> httpd_stop()
 -> vTaskDelay(1000 ms) y repetir
```

Iniciar/detener HTTP es idempotente. Una petición de captura recorre
`capturar_imagen()` → `camera_adquirir()` → `esp_camera_fb_get()` →
`httpd_resp_send()` → `camera_liberar()` → `esp_camera_fb_return()`.
La rutina Wi-Fi de CAM conserva su tratamiento previo de NVS incompatible/llena;
esta reorganización no modifica esa política ni las credenciales locales.

## 16. Archivos C, cabeceras y palabras del lenguaje

Un `.c` contiene implementación; su `.h` publica tipos y prototipos para otras
unidades. CMake compila cada `.c` por separado y el enlazador reúne sus símbolos.
No se incluye ningún `.c` mediante `#include`.

- `typedef` da un nombre a un tipo: `demanda_vehicular_t` facilita declarar demanda.
- `struct` agrupa campos relacionados: N1/N2, secuencia, recepción y validez.
- `enum` expresa opciones finitas: estados y colores, evitando comparar números sin nombre.
- `static` en función limita su uso a ese archivo: `seleccionar_verde()`,
  `autorizado()` y `escribir_cambio()` son auxiliares privados.
- `static` en variable global conserva estado de ese módulo: grupos de eventos,
  flags de inicio y gestor sincronizado de recepción en `comunicacion.c`.

La dependencia evita ciclos: `demanda.h` no incluye controlador; `semaforo_gpio.h`
define colores/pines/operaciones sin controlador. `controlador.h` usa ambos tipos
puros. `comunicacion.h` usa demanda y no expone tipos SDK. Así los tests C pueden
compilar controlador/demanda/GPIO sin ESP-IDF ni Wi-Fi.

## 17. CMake, Kconfig y archivos de configuración

| Archivo | Papel real |
| --- | --- |
| `CMakeLists.txt` raíz de cada proyecto | Cargar ESP-IDF y declarar el proyecto |
| `main/CMakeLists.txt` | Fuentes, includes, componentes y HTML embebido en CAM |
| `Kconfig.projbuild` | Opciones visibles en menuconfig: modo, tiempos, GPIO confirmado, Wi-Fi y UDP |
| `sdkconfig` | Selección local generada; puede contener credenciales, no versionar |
| `sdkconfig.defaults` | Valores iniciales reproducibles; no sobrescribe elecciones locales existentes |
| `idf_component.yml` de CAM | Fijar esp32-camera 2.1.9 y SDK >=6.0.2,<6.1.0 |
| `dependencies.lock` de CAM | Versiones/hash resueltos: esp32-camera 2.1.9 y esp_jpeg 1.3.2 |
| `.clang-format` | Convenciones de sangría, llaves y líneas; no configuración del firmware |

La cabecera `sdkconfig.h` se genera para compilar; no se edita manualmente.
`managed_components/` es material del gestor, no un lugar para cambiar código del
proyecto. Los dos targets permanecen distintos. No se eliminó ningún componente
oficial por no aparecer en main: se revisan sus usos en todos los módulos.

## 18. Decisiones y alternativas

Se agrupan funciones relacionadas en controlador, demanda y comunicación, en
lugar de mantener un archivo por subresponsabilidad pequeña. GPIO conserva
adaptador separado porque permite probar fallos sin hardware. CAM conserva sus
tres responsabilidades porque adquisición, red y servidor tienen recursos propios.

No se usó un único archivo gigantesco para C6: impediría separar la lógica pura
de las APIs del SDK al ejecutar tests anfitriones. Tampoco tres tareas por LED,
retardos de varios segundos dentro del controlador ni una cola ilimitada.
No se agregó UDP bidireccional ni autenticación: esta tarea solo reorganiza el
flujo ASCII de la referencia y conserva sus límites para una LAN privada.

## 19. Ejecución y ejemplos para la defensa

Desde la terminal oficial de ESP-IDF en cada proyecto:

```powershell
idf.py --version
# CAM: $env:IDF_TARGET = 'esp32'
# C6:  $env:IDF_TARGET = 'esp32c6'
idf.py menuconfig
idf.py build
idf.py -p COMx -b 115200 flash
idf.py -p COMx monitor
```

Verificar versión 6.0.2 y usar el puerto real de cada placa. Si el proyecto aún
no tiene el target adecuado, configurar `idf.py set-target esp32` o `esp32c6`
y revisar menuconfig; no regenerar innecesariamente configuraciones locales.
Si Windows asocia idf.py a Node, usar `python "$env:IDF_PATH/tools/idf.py"` desde
la terminal IDF. El venv Python de visión es independiente del de ESP-IDF.

En C6 elegir convencional, adaptativo simulado o conectado. Confirmar esquema
antes de marcar pinout. Para conectado configurar SSID, puerto y timeout local;
usar en PC la IP que informa C6 y `udp.emisor.local.json` (activo/IPdestino/puerto).
No sobrescribir archivos privados ni mostrar credenciales durante la defensa.

```powershell
& .\Vision_Artificial\.venv\Scripts\python.exe .\Vision_Artificial\main.py --udp-config .\Vision_Artificial\udp.emisor.local.json
```

Ejemplo de análisis lógico: con mensaje nuevo `42,5,1,1`, D=4 y el verde
seleccionado para carril1 será 11 s cuando le toque. Si llega `43,0,0,0` durante
verde, la siguiente actualización solicita amarillo completo y rojo total.
Otra observación recibida durante el despeje no habilita el rearme. Estos son
ejemplos del código, no mediciones de la maqueta.

## 20. Límites y pruebas físicas pendientes

UDP puede perder, duplicar, retrasar o reordenar paquetes; no autentica al emisor.
El timeout de C6 es local desde recepción y no demuestra antigüedad extremo a
extremo. Duplicados no lo renuevan. Reiniciar referencia de Python exige demanda
previa caducada y seguro atendido, pero un paquete antiguo puede ser ambiguo.
`sendto` correcto no confirma recepción en C6.
El origen temporal del PC es el inicio de la solicitud HTTP, no una marca fiable
del instante de exposición del sensor.

La pila/prioridad configurada no demuestra cumplimiento de deadlines. Tampoco
compilar o simular GPIO demuestra niveles eléctricos. Falta verificar placa,
GPIO10/11, resistencias, alimentación, sensor, fotografías, cortes de Wi-Fi,
reinicios y tiempos con instrumentos. No se afirma precisión vehicular del 90 %:
no existen anotaciones manuales locales para esa evaluación. No se entrenó YOLO11x.

## Preguntas probables del profesor

| Pregunta | Respuesta basada en este código |
| --- | --- |
| ¿Quién enciende los LED? | Solo tarea_controlador, a través del driver y sus callbacks; receptor y simulador publican demanda. |
| ¿Por qué inicializar GPIO dentro de esa tarea? | Evita repartir la propiedad de las salidas entre app_main y otra tarea. |
| ¿Cuál es la diferencia entre cola y mutex? | La cola copia observaciones; el mutex CAM reserva un recurso compartido durante captura/envío/reconfiguración. |
| ¿Por qué una cola de longitud uno? | Interesa la ocupación más reciente; procesar una fila larga usaría escenas viejas. |
| ¿Puede una observación borrar un fallo? | No: la generación retenida y seguro_solicitado conservan el despeje aunque la cola cambie. |
| ¿Por qué no poner vTaskDelay(13000) para el verde? | Durante esa espera la tarea no comprobaría invalidación ni caducidad. Se revisa reloj en cada vuelta corta. |
| ¿Llegar tarde acorta amarillo? | No: una sola transición y reinicio temporal tras aplicar GPIO prolongan la fase. |
| ¿Qué hace static? | Hace privados auxiliares/estado del módulo; no crea una tarea ni un mutex. |
| ¿Basta declarar volatile para compartir demanda? | No: el estado se copia y actualiza bajo secciones críticas breves, y la cola copia sus mensajes. |
| ¿Qué mide xTaskCreate en ESP-IDF? | Su argumento de pila está en bytes; prioridad no representa segundos ni orden fijo. |
| ¿Por qué dos SDK targets? | CAM usa ESP32 clásico y C6 ESP32-C6; toolchain, pines y configuración son distintos. |
| ¿Se libera el framebuffer si falla HTTP? | Sí: capturar_imagen llama camera_liberar tras intentar el envío. |
| ¿ROI inválida impide reconocer? | No: mantiene cajas/total diagnóstico; bloquea la clasificación operativa por carril. |
| ¿N1=0,N2=0 significa error? | Solo es medición si valido=1. valido=0 es ausencia de demanda válida. |
| ¿Se evita inanición dando siempre verde al más cargado? | No se repite carril: alternan, con duración limitada a 5..13 s. |
| ¿UDP garantiza que el dato es reciente? | No. El PC comprueba vigencia, pero el receptor de cuatro campos no conoce el tiempo en tránsito. |
| ¿Qué evidencia tiene de funcionamiento? | Tests antes/después y compilaciones; las comprobaciones físicas quedan explícitamente separadas. |

## Anexo A. Mapa de archivos trasladados y eliminados

| Antes, en main de C6 | Ahora | Justificación |
| --- | --- | --- |
| controlador_semaforos.c/h, prioridad_vehicular.c/h, control_conectado.c/h, aplicacion_conectada.c/h | controlador.c/h | Una unidad de prioridad, estados, seguridad y aplicación comprobable |
| demanda_vehicular.h, gestor_demanda.c/h, demanda_conectada.c/h | demanda.c/h | Datos, validación, parsing, secuencias, vigencia e invalidación juntos |
| wifi_manager.c/h, receptor_udp.c/h | comunicacion.c/h | Recursos y tareas de red, sin dependencia del driver GPIO |
| simulador_demanda.c/h | tarea_simulacion en main.c | Una tarea opcional visible junto al controlador, sin otro módulo pequeño |
| semaforo_pinout.h | semaforo_gpio.h | Los tests y el driver usan el mismo mapa público de pines |
| semaforo_gpio.c/h, semaforo_gpio_idf.c | Mismos archivos | Se conserva la separación de driver lógico y adaptador SDK |
| CAM camera_pinout.h | CAM camera_driver.c | Sus definiciones solo eran privadas de ese controlador |

Los archivos antiguos se eliminaron tras trasladar sus responsabilidades, sin
incluir fuentes `.c` desde otras. Los cuatro tests C mantienen instrucciones y
aserciones: solo cambiaron includes. Sus scripts enlazan los módulos consolidados.
C6 pasa de **12 C + 12 H a 6 C + 4 H**. CAM conserva **4 C**, pasando de 4 H a 3 H.

## Anexo B. Dependencias conservadas

| Proyecto | Componente | Uso que justifica conservarlo |
| --- | --- | --- |
| C6 | esp_driver_gpio | gpio_config/gpio_set_level y validación de salidas |
| C6 | esp_timer | Reloj monótono para fases y recepción |
| C6 | freertos, log | Tareas/colas/eventos/secciones críticas y registros |
| C6 | esp_wifi, esp_netif, esp_event, nvs_flash | STA, interfaz, callbacks e inicialización del subsistema |
| C6 | lwip | socket, bind, recvfrom y timeouts |
| CAM | esp32-camera, esp_jpeg | Controlador oficial y dependencia transitiva fijados por el gestor |
| CAM | esp_psram, heap | Verificación PSRAM y consulta de memoria |
| CAM | esp_driver_ledc, esp_system | Configuración XCLK/LEDC y versión SDK |
| CAM | freertos, log | Mutex, tareas, esperas y diagnóstico |
| CAM | esp_wifi, esp_netif, esp_event, nvs_flash | STA, reconexión y recursos de red |
| CAM | esp_http_server, esp_timer | Servidor/endpoints y límites temporales HTTP/uptime |

No se encontró una dependencia oficial demostrablemente sobrante; no se elimina
ninguna por aparecer en un módulo distinto de main. El HTML embebido, defaults,
Kconfig, manifiesto y lock de CAM se conservan.

## Anexo C. Línea base y regresión

Referencia: `fe35f06f4563b03748d12448a9552af893ecf8f1`. Antes de modificar se
registraron fuentes, dependencias, tres modos y huellas de archivos privados.
Pasaron 90 pruebas Python, cuatro grupos C y cinco tests web. Node necesitó
permiso de lectura de metadatos de ruta fuera del sandbox; no se cambió su instalación.

Resultados reales después de la reorganización:

| Verificación | Antes | Después | Alcance |
| --- | --- | --- | --- |
| Python | 90 correctas | 90 correctas | Cliente, geometría, persistencia, conteo, diagnóstico y UDP loopback |
| C anfitrión | 4 grupos correctos | Los mismos 4 correctos | GPIO, prioridad, estados, demanda, timeout, Wi-Fi simulado, invalidaciones y recuperación |
| Web | 5 correctas | Las mismas 5 correctas | JavaScript real de la página: secuenciación, parada, errores, blobs y control |
| Mapa de pines | Referencia fe35f06 | Mismos valores | Comparación de macros trasladadas en ambos proyectos |
| Archivos privados y manifiesto/lock | Huellas locales guardadas | 10 archivos sin cambios | Incluye sdkconfig y ajustes locales existentes; no se publican sus hashes |

No se eliminó ninguna prueba ni se cambiaron las aserciones C. En HTTP/Wi-Fi
CAM se contrastaron también los tokens: mismas instrucciones, literales y
operadores normalizando solo formato, comentarios, llaves y concatenación C de
cadenas. HTML, Python, manifiesto, lock y defaults no cambian de contenido.

Compilaciones **ejecutadas** con ESP-IDF v6.0.2 y configuraciones aisladas:

| Proyecto/modo | Target | Resultado | Tamaño app |
| --- | --- | --- | --- |
| CAM | esp32 | Correcto | 0x6ccb0 bytes |
| C6 convencional | esp32c6 | Correcto | 0x28ef0 bytes |
| C6 adaptativo simulado | esp32c6 | Correcto | 0x29460 bytes |
| C6 adaptativo conectado | esp32c6 | Correcto | 0x3f1b0 bytes |

Los tamaños no prueban rendimiento ni equivalencia binaria. La refactorización
y el enlazado pueden cambiar el tamaño sin cambiar el comportamiento comprobado.
Durante la comprobación se corrigió un nombre de campo del SDK afectado por un
renombrado; las cuatro compilaciones finales son posteriores a la corrección.
`pip check`, `git diff --check` y la comprobación de formato resultaron correctos.

Comandos de regresión desde la raíz:

```powershell
& .\Vision_Artificial\.venv\Scripts\python.exe -m unittest discover -s Vision_Artificial/tests -v
& .\Vision_Artificial\.venv\Scripts\python.exe -m pip check
node .\Proyecto_Final_Cam\tests\web_ui.test.cjs
.\Proyecto_Final_C6\tests\ejecutar_host.ps1 -Compilador "RUTA_REAL\tcc.exe" -EnMemoria
git diff --check
```

Si la política local impide ejecutar el script, los comandos C equivalentes con
TinyCC, desde `Proyecto_Final_C6`, son:

```powershell
$cc = 'RUTA_REAL\tcc.exe'
$comun = @('-std=c99','-Wall','-Werror','-Imain','main/controlador.c','main/demanda.c')
& $cc @comun main/semaforo_gpio.c -run tests/pruebas_controlador.c
& $cc @comun -run tests/pruebas_prioridad.c
& $cc @comun -run tests/pruebas_udp.c
& $cc @comun main/semaforo_gpio.c -run tests/pruebas_gpio_conectado.c
```

No se cambió la política del usuario. Para GCC puede usarse el mismo conjunto de
fuentes con `-o pruebas.exe` y ejecutar el binario, sin `-run`.
Las builds C6 reutilizaron directorios/configuraciones de validación ignorados;
CAM usó `build08-cam` y `sdkconfig08.cam` bajo `.herramientas` de C6, con target
esp32 y defaults de CAM. No son proyectos duplicados: compilan las fuentes de
los dos proyectos existentes. Sus credenciales están vacías y la confirmación
de pines de las variantes C6 sirve solo para compilar el código habilitado.

La evidencia de regresión cubre lógica y escenarios simulados; no demuestra
radio, sensor, niveles eléctricos ni planificación FreeRTOS en placa. No se
flasheó ni publicaron binarios. Mantener pendientes físicos del apartado 20.

Fuentes oficiales: [FreeRTOS ESP-IDF](https://docs.espressif.com/projects/esp-idf/en/v6.0.2/esp32c6/api-reference/system/freertos_idf.html),
[GPIO C6](https://docs.espressif.com/projects/esp-idf/en/v6.0.2/esp32c6/api-reference/peripherals/gpio.html),
[esp_timer](https://docs.espressif.com/projects/esp-idf/en/v6.0.2/esp32c6/api-reference/system/esp_timer.html),
[esp32-camera](https://github.com/espressif/esp32-camera).
También se verificó el comentario de pila en bytes de `idf_additions.h` del SDK instalado.
