# UDP sencillo PC -> ESP32-C6 ? tarea07.2

Tarea08 conserva este protocolo y reorganiza su implementacion en
comunicacion.c/h y demanda.c/h. [Recorrido academico](../GUIA_ESTUDIO.md).

La CAM conserva su servidor HTTP. El PC realiza YOLO11x y conteo por ROI; C6
recibe conteos y ejecuta prioridad, maquina de estados y GPIO con FreeRTOS.

## Mensaje y comportamiento

Un datagrama ASCII, sin salto final ni espacios:

```text
secuencia,N1,N2,valido
42,5,1,1
43,0,0,0
```

Cuatro enteros canonicos sin signos ni ceros iniciales innecesarios. Secuencia
1..18446744073709551615, N1/N2 entre0 y1000, valido exclusivamente0 o1.
Maximo48bytes; rechazar campos extra, truncados, NUL, espacios y rangos invalidos.
`43,0,0,0` invalida: sus ceros son marcadores sin significado de medicion.
`44,0,0,1` si representa cero vehiculos medidos.

El PC incrementa secuencia en cada envio preparado durante su ejecucion. Cada
foto nueva vigente se envia una vez. Errores, pausa, ROI pendientes, desconexion
o caducidad producen invalidez explicita; una misma foto no se reenvia como
observacion nueva. El servicio usa socket estandar en su propio hilo, sin otra
inferencia. Al cerrar intenta enviar una ultima invalidacion.

C6 solo recibe: no solicita ni confirma datagramas. El receptor valida campos,
secuencia y opcion de IP emisora. Cola FreeRTOS de longituduno para demanda;
generacion local separada para invalidacion critica. Duplicados y mensajes
fuera de orden no renuevan la vida de la demanda.

Timeout LOCAL inicial5000ms desde recepcion de una observacion nueva valida.
Se revisa tambien en cada vuelta del propietario. Perdida Wi-Fi/IP invalida de
inmediato en software y bloquea nuevos conteos hasta recuperar IP. En verde se
inicia amarillo completo, luego rojo total y seguro; durante despejes no se
acortan tiempos ni se cancela la salida segura por recibir un valor valido.

El conectado inicia ambos rojos. Para recuperar necesita una nueva observacion
recibida cuando ya estaba seguro y habia atendido la invalidacion; despues
mantiene rojo inicial completo. Una foto recibida durante el despeje no basta.
La alternancia se conserva respecto al ultimo verde aplicado. Un fallo GPIO
bloquea al propietario/driver y los paquetes no lo rehabilitan.

Si Python reinicia secuencia, C6 permite una referencia menor solo despues de
caducar la demanda anterior y alcanzar seguro atendido. Hasta entonces rechaza
esos mensajes. La siguiente foto nueva puede recuperar; no hay negociacion.

## Configuracion en VS Code

Mantener una LAN privada sin aislamiento entre clientes. CAM/C6 requieren2.4GHz.
No modificar firmware CAM; desde su web seleccionar SVGA800x600.

En C6 abrir **ESP-IDF: Open ESP-IDF Terminal**, dentro de Proyecto_Final_C6:

```powershell
idf.py --version
$env:IDF_TARGET = 'esp32c6'
idf.py menuconfig
idf.py build
idf.py -p COMx -b 115200 flash
idf.py -p COMx monitor
```

Verificar v6.0.2 y sustituir COMx por puerto real. Usar Python/terminal de ESP-IDF,
separado del venv de vision. Si Windows asocia idf.py a Node, invocar
`python "$env:IDF_PATH/tools/idf.py"` desde el terminal IDF. Si aun no hay target
C6, seleccionar `idf.py set-target esp32c6` y volver a configurar; conservar la
configuracion local existente cuando ya es correcta.

En menu Semaforos elegir adaptativo conectado; configurar SSID/password locales,
puerto5005, timeout local5000ms y opcional IPv4 permitida del PC. Confirmar placa,
pines y cableado antes de habilitar salidas. El timeout no puede superar la
vigencia maxima de demanda configurada; si no es coherente, mantiene rojos.
Las credenciales siguen en sdkconfig ignorado. El monitor informa la IPv4 de C6;
esa sera el destino del PC. No asumir IP ni usar127.0.0.1 para una placa fisica.

En la raiz del repositorio crear la nueva configuracion solo si no existe:

```powershell
if (-not (Test-Path .\Vision_Artificial\udp.emisor.local.json)) {
    Copy-Item .\Vision_Artificial\udp.emisor.example.json .\Vision_Artificial\udp.emisor.local.json
}
```

Editar ese archivo: activo=true, ip_destino=IPv4 real de C6 y puerto5005.
No modificar config.json. Los archivos UDP/clave antiguos, si existen localmente,
se conservan ignorados y ya no se usan. No hay pasos de autenticacion.

```powershell
& .\Vision_Artificial\.venv\Scripts\python.exe .\Vision_Artificial\main.py --udp-config .\Vision_Artificial\udp.emisor.local.json
```

Sin --udp-config, o con activo=false, UDP queda desactivado. El panel muestra
camara, YOLO11x, calibracion, conteos validos, tiempo de inferencia, destino,
ultimo mensaje enviado, cantidad de envios y errores locales. sendto correcto
no demuestra recepcion en C6. No requiere abrir un puerto entrante en Windows
para este flujo; si una politica local bloquea salidaUDP, revisarla localmente.

Perfil neuronal conservado: pesos originales yolo11x.pt, CPU/PyTorch FP32,
foto800x600, imgsz960, confianza0.15, IoU0.45, clases2/3/5/7, NMSfalse,
tres calentamientos e hilos de referencia. Sin modelos adicionales ni nuevas
instalaciones. Con ROI pendientes siguen las cajas/confianzas y total de YOLO;
N1/N2 y demanda valida quedan bloqueados. Confirmar ambas ROI con Enter y guardar
con G. V, cambios de resolucion y la marca persistente de invalidacion conservan
sus protecciones. S guarda originales y A diagnosticos separados.

## Limites

UDP sencillo no garantiza entrega, autenticacion, orden ni antiguedad extremo
a extremo. Timeout mide tiempo LOCAL desde recepcion: un paquete pudo permanecer
en transito antes. PC verifica vigencia desde inicio HTTP antes de enviar, pero
C6 no puede medir esa edad con cuatro campos. Una invalidacion perdida se
resuelve por caducidad local si no llegan nuevas observaciones; no hay reenvio
confirmado ni garantia de observar todos los fallos breves remotos.

Tras reiniciar referencia tampoco se distingue de forma infalible un reinicio
real de un paquete antiguo retrasado. Restringir IP reduce emisores accidentales,
no autentica. Usar exclusivamente LAN privada controlada, sin puertos expuestos.

Una invalidacion puede llegar entre el chequeo de vigencia y la escritura GPIO.
Se comprueba antes/despues del driver; si hubo verde, se inicia amarillo completo.
Fuera de esa ventana se observa en la siguiente vuelta solicitada de20ms mas
trabajo, ticks y retrasos de planificacion/logging. No es una cota fisica garantizada
ni eliminacion de pulsos. Estado seguro tampoco garantiza LEDs durante reset,
falta de alimentacion o averia. Confirmar funcionamiento fisico con instrumentos.

## Pruebas y sustitucion del protocolo anterior

El historial de SE07 se conserva en ebe261a. Se retiran cliente_udp, sesion_udp,
protocolo_udp, udp_criptografia, servidor_udp, configurar_udp, puente binario y
vectores HMAC; tambien el contrato propuesto anterior. CMake ya no requiere
mbedtls para el protocolo. No se mantienen dos protocolos operativos.

De93 pruebas Python de tarea07, se conservan76 anteriores y3 de edicion ROI;
se retiran14 exclusivas del protocolo binario/asociacion/HMAC/RTT. Sus requisitos
vigentes se cubren por pruebas ASCII, timeout, reinicio y seguridad nuevas.
Las pruebas de prioridad, estados, geometria, persistencia y evaluacion siguen.
Un test de referencia ROI utiliza ahora un instante fijo para evitar depender
de la velocidad de codificacion JPEG del equipo; conserva la misma proteccion.

```powershell
& .\Vision_Artificial\.venv\Scripts\python.exe -m unittest discover -s Vision_Artificial/tests -v
& .\Vision_Artificial\.venv\Scripts\python.exe -m pip check
git diff --check
```

Para C, desde C6:

```powershell
.\tests\ejecutar_host.ps1 -Compilador "RUTA_REAL\tcc.exe" -EnMemoria
```

Compila/ejecuta cuatro grupos con TinyCC existente. Sin EnMemoria puede usarse
GCC o TinyCC para generar ejecutables. Si la politica de PowerShell impide el
script, ejecutar los comandos C equivalentes desde el terminal sin cambiarla.
Las operaciones GPIO inyectadas prueban cada estado intermedio y fallos; los
intercalados son deterministas, no un ensayo del planificador en placa.

Compilacion aislada de tres modos desde C6: usar sdkconfig de validacion
separados con CONFIG_IDF_TARGET="esp32c6", la opcion de modo correspondiente
y confirmacion de pinout solo para compilar el codigo, sin flashear esas pruebas:

```powershell
idf.py -B .herramientas/build07-conv -D SDKCONFIG=.herramientas/sdkconfig072.conv build
idf.py -B .herramientas/build07-adapt -D SDKCONFIG=.herramientas/sdkconfig072.adapt build
idf.py -B .herramientas/build07-udp -D SDKCONFIG=.herramientas/sdkconfig072.udp build
```

Validacion real de tarea07.2: **90 pruebas Python correctas** (79 conservadas y11
nuevas), cuatro grupos C correctos con TinyCC existente y loopback UDP real con
resultados simulados. pip check y git diff --check correctos. Se compilaron
convencional, adaptativo simulado y conectado con ESP-IDF v6.0.2/esp32c6,
sdkconfig/directorios de validacion aislados y secretos vacios. Binarios de prueba:
convencional0x28ef0, adaptativo0x29470, conectado0x3f1a0 bytes; no se publican.
Inferencia funcional REAL con pesos locales, tres calentamientos y una imagen
sintetica SVGA sin ROI: cero detecciones y conteos operativos None. Esto valida
la ruta diagnostica, sin medir exactitud, rendimiento sostenido ni latencia radio.
config.json se verifico conservado byte a byte y confianza efectiva0.15.

Pendiente fisico: verificar cableado y pinout; recibir conteos reales, cortar
Wi-Fi/Python, observar despejes, esperar caducidad, reiniciar Python y recuperar.
No se declara precision vehicular ni latencia radio/LED medida.
