# Integracion 07: HTTP, conteos y UDP autenticado

La rama `feat/integration-udp-07` parte de C6 `3ff0759`
(`feat/c6-adaptive-traffic-priority`, PR #7) e incorpora vision `352afcb`
(`feat/yolo11x-inference-optimization`, PR #5). Conserva GPIO del PR #6,
prioridad, diagnostico, evaluacion y los modos autonomos. No fusiona esos PR
en GitHub ni modifica `master` o `Proyecto_Final_Cam`.

La CAM mantiene HTTP/80; PC sirve UDP/5005 configurable; C6 solicita datos como
STA en la misma LAN. Solo la tarea propietaria de C6 modifica los GPIO. Ni el PC
ni la tarea de red encienden LEDs. HMAC proporciona **autenticidad e integridad,
no cifrado**. No redirigir el puerto desde Internet. Quien conoce la clave puede
suplantar el emisor: proteger archivos locales, firmware y acceso a la LAN.

## Formato SE07, version 1

Todos los datagramas miden **152 bytes**: cuerpo [0,120) y HMAC-SHA256 [120,152).
El MAC autentica exactamente los primeros 120 bytes, incluidos cabecera,
identidades y reservas. Clave de 32 bytes. Enteros sin signo en orden de red.
No se transmite una estructura C. Python usa
`!4sBBBB16s16s16sQQQQQQIHHB3xI`; C escribe cada campo explicitamente.

| Offset | Bytes | Campo |
| --- | --- | --- |
| 0 | 4 | ASCII `SE07` |
| 4 | 1 | version = 1 |
| 5 | 1 | tipo 1..7 |
| 6 | 1 | valido = 1 exclusivamente en RESULTADO; 0 en los otros |
| 7 | 1 | motivo 0..7 |
| 8 | 16 | identidad estable del emisor E |
| 24 | 16 | sesion del proceso Python S; ceros en HELLO |
| 40 | 16 | sesion del receptor R |
| 56 | 8 | epoca de adquisicion |
| 64 | 8 | resultado: secuencia inmutable de captura analizada |
| 72 | 8 | evento del servidor; en solicitudes, generacion de fallos locales C6 |
| 80 | 8 | nonce de solicitud/respuesta |
| 88 | 8 | reconocimiento de invalidacion; solo efectivo si estado = 7 |
| 96 | 8 | barrera; en ASOCIACION/CONFIRMAR contiene el desafio |
| 104 | 4 | edad_origen_ms |
| 108 | 2 | N1: 0..1000 |
| 110 | 2 | N2: 0..1000 |
| 112 | 1 | estado C6 0..7 |
| 113 | 3 | reserva: exactamente ceros |
| 116 | 4 | ultimo RTT informado por C6, ms |
| 120 | 32 | HMAC-SHA256 del cuerpo |

Tipos: HELLO=1, ASOCIACION=2, CONFIRMAR=3, CONSULTA=4, RESULTADO=5,
INVALIDACION=6, ESPERA=7. Motivos: 0 sin motivo; 1 sin datos; 2 camara;
3 inferencia; 4 pausa; 5 contexto/ROI; 6 edad; 7 comunicacion.
Estados: 0 rojo inicial; 1 verde1; 2 amarillo1; 3 rojo1->2; 4 verde2;
5 amarillo2; 6 rojo2->1; 7 seguro. Los estados informados reflejan software,
no una medicion electrica de los LEDs.

RESULTADO exige resultado/evento no nulos y motivo=0. N1/N2 solo tienen sentido
con ese tipo y `valido=1`; los demas tipos reservan ambos campos a cero.
Un RESULTADO 0/0 es una medicion valida, diferente de INVALIDACION o ESPERA.
Los campos no utilizados de una solicitud se envian a cero; estado y RTT pueden
informarse en todas las solicitudes. Identidades son bytes opacos de 16 bytes,
representados en hexadecimal solo en configuracion local.

Tamanos distintos, MAC erroneo, version, tipo, reservas o rangos invalidos se
rechazan antes de aplicar campos. Se recibe como maximo 513 bytes para detectar
exceso del limite 512; solo se acepta el tamano exacto 152. El parser C autentica
antes de escribir su salida. La autenticacion no sustituye validacion de nonce,
sesiones, orden, edad y barrera.

### Asociacion y reinicios

1. C6 inicia ambos rojos, genera R y manda HELLO autenticado con E, S=0, nonce.
2. PC responde ASOCIACION con ese R/nonce, su S aleatoria por arranque y un
   desafio aleatorio valido durante 3 s. Esto todavia no cambia la asociacion activa.
3. C6 envia CONFIRMAR con S/R y desafio, usando un nonce nuevo. PC confirma con
   INVALIDACION retenida. Solo entonces queda asociado y retira el R anterior.
4. C6 conserva la generacion de seguridad hasta que el propietario haya aplicado
   ambos rojos en ESTADO_SEGURO. CONSULTA informa ese estado y el reconocimiento.
5. PC acepta el ACK exacto y fija un instante monotonic local. Solo permite una
   captura cuyo inicio HTTP sea **estrictamente posterior** a ese instante.
6. C6 recibe un resultado nuevo y hace un rojo inicial completo antes de verde.

Una respuesta solo puede consumir el unico nonce pendiente, con E/S/R correctos
y RTT <=750 ms. Nonces crecientes de 64 bits, nuevos tambien en retransmisiones;
al agotar el contador se bloquea la entrega y se requiere reiniciar, sin wrap.
El PC recuerda hasta 64 sesiones retiradas durante su proceso: al llegar al
limite requiere reiniciar el servicio. Una sesion nueva necesita el desafio,
no basta cambiar un identificador en un RESULTADO. En un reinicio de Python,
C6 deja caducar comunicacion, cambia R y repite la asociacion desde seguro.
Un reinicio C6 cambia R y ejecuta el mismo procedimiento. No se acepta el
reinicio de numeracion de resultados sin nueva asociacion y barrera.

La identidad de observacion es (S, epoca, resultado); nonce identifica la
transmision. El PC responde ESPERA al volver a consultar la misma observacion.
Si se pierde un RESULTADO, no lo rejuvenece ni vuelve a declararlo nuevo:
espera otra captura. El resultado/evento aceptado en C6 debe avanzar; un paquete
atrasado o de otro nonce/sesion no actualiza comunicacion autenticada ni demanda.

## Vigencia y barreras

La edad parte del inicio monotonic de `/capture`, incluyendo reintentos HTTP,
espera, decodificacion e inferencia, y se redondea hacia arriba al preparar la
respuesta. `/status` no rejuvenece la foto. No hay timestamp fiable de exposicion
del sensor, por lo que no se acota el tiempo de una foto ya almacenada en el sensor.

Con `t0` de solicitud y `tr` de aceptacion en C6:

```text
edad_cota_rx = edad_origen_ms + (tr - t0) + margen_ms
vence_origen = t0 + F - edad_origen_ms - margen_ms
vence_local = tr + vigencia_local_ms
vence_resultado = min(vence_origen, vence_local)
```

F=12000 ms, local=5000 ms, margen=50 ms, intervalo=1000 ms,
respuesta=750 ms y comunicacion autenticada=3000 ms, todos configurables.
Se comprueban restas/sumas/overflow antes de construir plazos. Igualar el
vencimiento ya significa caducado. ESPERA puede confirmar transporte, pero no
cambia `vence_resultado`. El propietario comprueba ademas el vencimiento de
comunicacion en cada vuelta (~20 ms solicitados), sin esperar al socket.
La vida efectiva es el minimo de resultado y comunicacion.

Los 50 ms son una hipotesis inicial conservadora, no un error medido: contemplan
redondeo de milisegundos, granularidad de monotonic en Windows y deriva relativa
acotada a menos de 1000 ppm durante 12 s. Esa cota requiere verificarse en los
equipos; si no se cumple, revisar margen y presupuestos explicitamente. RTT
cubre la espera variable de transporte; no se comparan relojes absolutos entre
equipos. La doble contabilizacion de parte de la espera puede descartar datos
adicionales. No se amplian limites automaticamente.

El PC retiene cada invalidacion en memoria de sesion hasta ACK de seguro;
un fallo seguido de un resultado valido entre dos consultas no borra la barrera.
Epoca HTTP, generacion neuronal, contador de errores, ROI y pausa forman el
contexto sincronizado. Los contadores conservan errores breves aunque el
servicio no llegue a observar el estado de error antes de su recuperacion.
Ademas, cruzar el vencimiento del snapshot anterior entre dos observaciones
retiene una invalidacion, aunque la siguiente fotografia ya sea valida. Esta
regla conservadora puede exigir otro rearme cerca del limite temporal. C6
aplica la misma precaucion si el plazo anterior termina durante la recepcion.

En C6 la demanda ordinaria usa la cola FreeRTOS de un valor, con overwrite;
un snapshot bajo seccion critica conserva coherencia durante la publicacion.
La generacion de invalidacion y su reconocimiento se guardan por separado y no
pueden sobrescribirse por otro conteo. Un fallo local incrementa tambien una
generacion enviada a PC, que exige otra barrera y captura posterior al ACK.
La perdida de Wi-Fi/IP borra validez en el manejador de eventos inmediatamente.

Durante verde, una invalidacion inicia amarillo completo; durante amarillo o
rojo total completa el despeje. Luego permanece en ESTADO_SEGURO, ambos rojos.
Datos posteriores no cancelan esa transicion. Recuperar requiere asociacion,
generacion reconocida y captura posterior a ACK; mantiene rojo inicial completo
y alterna respecto al ultimo carril abierto. La duracion se selecciona una vez
al entrar al verde, 5..13 s; amarillo 2 s y rojo total 1 s no se recortan.
No se cambia al modo convencional ante fallo. El objetivo nominal 20 s sin
verde aplica a operacion continua: una permanencia en seguro puede superarlo.
Un error GPIO bloquea al propietario y no se rearma mediante paquetes.

## Configuracion desde VS Code

Conectar los tres equipos a una LAN que permita comunicacion entre clientes
(desactivar aislamiento de clientes si procede). CAM y C6 necesitan 2.4 GHz.
Configurar SVGA 800x600 en la web de CAM; no se cambia su firmware ni resolucion
en silencio. Confirmar fotografia y ambas ROI antes de operar.

En terminal PowerShell de la raiz, con el venv Python existente:

```powershell
& .\Vision_Artificial\.venv\Scripts\python.exe .\Vision_Artificial\configurar_udp.py
```

Solo crea archivos NUEVOS `Vision_Artificial/udp.local.json` y `clave_udp.hex`.
Si ya existen, los conserva y sale con error. Guardar la clave local con acceso
limitado al usuario; no compartir capturas de pantalla, backups publicos ni logs
de esos archivos. No imprime la clave. Copiar localmente su contenido a Kconfig
de C6 sin pegarlo en comandos registrados. Copiar `emisor_id` de udp.local.json
al campo de identidad. El JSON contiene ruta a clave, identidad, direccion de
escucha `0.0.0.0`, puerto5005 y max_edad_ms12000; no contiene la clave.

Consultar `ipconfig` y elegir IPv4 LAN real de PC. Configurar C6 con esa direccion;
no usar 127.0.0.1 en hardware. Si cambia DHCP, actualizar IP local o reservarla
en el router. Para limitar escucha del PC, cambiar `direccion` en udp.local.json.
No sobrescribir `config.json`: su confianza efectiva ya fue verificada en .15.
Mantener YOLO11x .pt/CPU/PyTorch FP32, imgsz960, .15/.45, clases2/3/5/7, NMSfalse,
hilos de referencia (0 conserva defecto), calentamiento3 y filtro desactivado.
El modo UDP rechaza un perfil neuronal diferente; las herramientas de
comparacion/diagnostico siguen disponibles por separado.

Abrir `Proyecto_Final_C6` en VS Code, ejecutar **ESP-IDF: Open ESP-IDF Terminal**:

```powershell
idf.py --version
$env:IDF_TARGET = 'esp32c6'
idf.py menuconfig
idf.py build
idf.py -p COMx -b 115200 flash
idf.py -p COMx monitor
```

Debe indicar v6.0.2. `COMx` se sustituye por el puerto real. Si el proyecto aun
no tiene target C6, ejecutar `idf.py set-target esp32c6` y volver a configurar;
no ejecutar set-target innecesariamente sobre una configuracion local existente.
Si Windows ejecuta idf.py con Node, invocar `python "$env:IDF_PATH/tools/idf.py"`
desde esa misma terminal ESP-IDF. No usar el Python del venv de vision para IDF.

En **Semaforos**: modo adaptativo conectado; confirmar pinout SOLO despues de
verificar placa/cableado; SSID/password locales; IPv4 de PC; puerto, emisor y
clave. Simulador queda deshabilitado en conectado. Los secretos viven en
sdkconfig ignorado y en el binario generado: tampoco publicar binarios.
Timeout respuesta < intervalo; comunicacion > intervalo; margen < presupuesto;
vigencia UDP <= vigencia maxima de demanda. Una configuracion incoherente
mantiene ambos rojos y requiere corregirla/reiniciar. No borrar NVS para ocultar
errores. Wi-Fi reintenta de forma espaciada (3 s), sin espera activa.

Firewall Windows, SOLO en una LAN privada y PowerShell elevado, despues de
revisar la ruta exacta del ejecutable. Ejemplo que el usuario ejecuta localmente:

```powershell
$pythonVision = (Resolve-Path '.\Vision_Artificial\.venv\Scripts\python.exe').Path
New-NetFirewallRule -DisplayName 'SE07 UDP privado' -Direction Inbound -Action Allow -Profile Private -Protocol UDP -LocalPort 5005 -RemoteAddress LocalSubnet -Program $pythonVision
```

Adaptar puerto si se cambio. No se ejecuto esta regla durante el desarrollo.
Para retirarla: `Remove-NetFirewallRule -DisplayName 'SE07 UDP privado'`.
No abrirla en perfil publico ni reenviar puertos del router.

Arrancar la CAM, comprobar su HTTP; iniciar PC y despues C6:

```powershell
& .\Vision_Artificial\.venv\Scripts\python.exe .\Vision_Artificial\main.py --config .\Vision_Artificial\config.json --udp-config .\Vision_Artificial\udp.local.json
```

Controles S/A/D/C/O/1/2/R/Enter/G/V/Espacio/Q se conservan. UDP activo y C6
asociada son indicadores distintos. RTT/estado C6 son los ultimos reportados;
no sustituyen observacion fisica. Pausar, editar o desactivar IA invalida control.
Para una edicion ordinaria nueva se exige foto reciente de la epoca actual;
Enter/G revalidan la referencia congelada, conexion y epoca. G no guarda una
calibracion obsoleta como valida.

## Pruebas reproducibles

Validacion ejecutada el 2026-11-25: **93 pruebas Python correctas**, incluidas las
76 anteriores y dos del puente C, sin skips. Pasan los ejecutables C anteriores
de controlador/GPIO y prioridad, y cuatro grupos nuevos de sesiones, plazos,
barreras y seguridad en las seis fases del ciclo. Loopback real con datos
simulados correcto. `pip check`: sin requisitos incompatibles. Compilaciones
ESP-IDF v6.0.2/esp32c6 correctas en convencional, adaptativo simulado y conectado,
con configuraciones de validacion aisladas. No se flasheo ningun dispositivo.

Inferencia funcional real con pesos locales originales y una imagen sintetica
negra SVGA, despues de tres calentamientos: cero detecciones, tensor de entrada
`(1,3,736,960)` FP32 (LetterBox rectangular), PyTorch CPU; hilos efectivos
intra=8/inter=6. Python3.11.15, Ultralytics8.4.218, PyTorch2.15.0+cpu.
El hash de config.json antes/despues coincide y la confianza efectiva es0.15.
Esto comprueba ejecucion, no precision ni rendimiento sostenido. No se evaluaron
vehiculos anotados ni latencia completa HTTP/radio en esta tarea.

Desde raiz, sin dispositivos ni credenciales:

```powershell
& .\Vision_Artificial\.venv\Scripts\python.exe -m unittest discover -s Vision_Artificial\tests -v
& .\Vision_Artificial\.venv\Scripts\python.exe -m pip check
git diff --check
```

Vectores compartidos: [vectores_udp07.json](tests/vectores_udp07.json), con clave
PUBLICA de prueba `00..1f`, **nunca utilizarla en dispositivos**. Incluyen HELLO,
RESULTADO e INVALIDACION y sus 152 bytes completos. El HELLO tiene HMAC
`bae30a00e6e3ee0497414e9e92512325f046fc06656b1659c03b9a639d4c1424`.
Python compara hmac estandar con ida/vuelta por el codec C compilado anfitrion;
las devoluciones de llamada usan hmac/compare_digest de Python. La API PSA del
firmware se compila contra el SDK, pero requiere prueba en placa para verificar
su ejecucion real. No se implementa criptografia propia.

Con TinyCC local existente, compilar y ejecutar los tres ejecutables anfitriones
(en otros equipos puede usarse un compilador C99, adaptando nombres/rutas):

```powershell
$tcc = '.\Proyecto_Final_C6\.herramientas\tcc\tcc\tcc.exe'
$inc = '-IProyecto_Final_C6/main'
$nucleo = @('Proyecto_Final_C6/main/controlador_semaforos.c', 'Proyecto_Final_C6/main/prioridad_vehicular.c', 'Proyecto_Final_C6/main/gestor_demanda.c')
& $tcc -std=c99 -Wall -Werror $inc Proyecto_Final_C6/tests/pruebas_controlador.c @nucleo Proyecto_Final_C6/main/semaforo_gpio.c -o Proyecto_Final_C6/.herramientas/pruebas.exe
& .\Proyecto_Final_C6\.herramientas\pruebas.exe
& $tcc -std=c99 -Wall -Werror $inc Proyecto_Final_C6/tests/pruebas_prioridad.c @nucleo -o Proyecto_Final_C6/.herramientas/prioridad.exe
& .\Proyecto_Final_C6\.herramientas\prioridad.exe
& $tcc -std=c99 -Wall -Werror $inc Proyecto_Final_C6/tests/pruebas_udp.c @nucleo Proyecto_Final_C6/main/protocolo_udp.c Proyecto_Final_C6/main/sesion_udp.c Proyecto_Final_C6/main/control_conectado.c -o Proyecto_Final_C6/.herramientas/udp07.exe
& .\Proyecto_Final_C6\.herramientas\udp07.exe
```

Si TinyCC no existe, solo los dos tests de puente codec C indican skip; no
declarar interoperabilidad probada en ese entorno hasta ejecutarlos. Las pruebas
UDP Python usan sockets reales sobre 127.0.0.1 con snapshots simulados, sin YOLO
ni firmware. Incluyen ACK, cero valido, ausencia y cierre limpio.

Para reproducir compilaciones sin tocar sdkconfig local, desde C6 crear tres
archivos de defaults en una carpeta ignorada, cada uno con `CONFIG_IDF_TARGET="esp32c6"`
y respectivamente `CONFIG_SEMAFORO_CONVENCIONAL=y`, `CONFIG_SEMAFORO_ADAPTATIVO=y`
o `CONFIG_SEMAFORO_CONECTADO=y`; usar:

```powershell
idf.py -B .herramientas/build07-conv -D SDKCONFIG=.herramientas/sdkconfig07.conv build
idf.py -B .herramientas/build07-adapt -D SDKCONFIG=.herramientas/sdkconfig07.adapt build
idf.py -B .herramientas/build07-udp -D SDKCONFIG=.herramientas/sdkconfig07.udp build
```

Las configuraciones de validacion habilitaron pinout solo para compilar la rama
de codigo completa, sin flashear. Los secretos quedaron vacios. Eso no autoriza
habilitar salidas en una placa sin verificar el esquema.

Prueba fisica pendiente: con conteos conocidos y monitor, abrir cada carril,
pausar PC, interrumpir HTTP/Wi-Fi, cerrar Python, perder paquetes, reiniciar PC/C6
y recuperar. Comprobar amarillo/rojo completos, permanencia segura y captura
posterior al ACK antes del rearme. Repetir durante verde, amarillo y rojo total;
verificar los seis LEDs y tiempos con instrumentos. Los logs indican decisiones
y tiempos software; no prueban tension, cableado, latencia radio o exactitud YOLO.
Estado seguro no garantiza funcionamiento durante reset, falta de alimentacion
o averia. No hay verdad manual local: precision y objetivo 90% siguen pendientes.

Fuentes oficiales: [Wi-Fi STA ESP-IDF](https://docs.espressif.com/projects/esp-idf/en/v6.0.2/esp32c6/api-reference/network/esp_wifi.html),
[Mbed TLS/PSA en ESP-IDF](https://docs.espressif.com/projects/esp-idf/en/v6.0.2/esp32c6/api-reference/protocols/mbedtls.html),
cabeceras `psa/crypto.h`, `esp_wifi.h`, `esp_event.h` y `esp_netif.h` del SDK instalado.
