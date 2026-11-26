# Sistemas Empotrados — instrucciones permanentes

## Proyecto y alcance actual

Maqueta universitaria de 45 × 44 cm, interseccion en Y: dos entradas y una salida.
ROI1 espera izquierda y ROI2 espera derecha; excluir convergencia y salida.
Cada vehiculo tiene el mismo peso. Cada LED lleva resistencia individual de 330 ohmios.

- ESP32-CAM: captura JPEG por HTTP, targetesp32. OV2640/OV3660 soportados;
  el usuario detecto OV3660 PID0x3660. Conservar PSRAM, flash4MiB, brownout y
  particion oficial SINGLE_APP_LARGE. Tarea08 autoriza reorganizar CAM sin alterar
  captura, HTTP ni configuraciones. El pinout privado vive en camera_driver.c.
- PC: un trabajador de adquisicion HTTP, uno de YOLO y un emisor UDP opcional.
- C6: Wi-Fi STA, receptor UDP, prioridad y una tarea propietaria de los seis GPIO.
  Ni PC ni receptor UDP controlan directamente LEDs.
- Tarea08: rama refactor/estructura-didactica-espidf desde fe35f06, PR contra
  feat/integration-udp-07. No modificar master ni fusionar PR anteriores.
  Separar commits de reorganizacion, limpieza y documentacion. Mantener facil
  retorno a la referencia. No incluir archivos .c mediante #include.

Estructura C6: main.c; controlador.c/h; demanda.c/h; comunicacion.c/h;
semaforo_gpio.c/h y semaforo_gpio_idf.c. Pines en semaforo_gpio.h. Conservar
logica pura y operaciones GPIO inyectables para tests. No redisenar protocolos,
prioridad, tiempos ni pines. Estilo .clang-format, nombres descriptivos, una
instruccion por linea y secciones visibles en main. Guia real en GUIA_ESTUDIO.md.

## Firmware y hardware

ESP-IDF nativo v6.0.2, C y FreeRTOS. Sin Arduino ni PlatformIO. Verificar version
real antes de compilar. No cambiar instalacion, politicas ni ajustes locales del
usuario. Rutas locales de herramientas no son requisitos portables.

GPIO provisionales: carril1 rojo2/amarillo3/verde10; carril2 rojo11/amarillo18/verde19.
Confirmar placa, variante y esquema antes de habilitar salidas; SiP puede no
exponer10/11. No usar arranque, USB, consola ni flash. Conservar driver central,
precarga segura, validacion de pines, exclusividad de verdes y bloqueo permanente
ante fallos GPIO. No desactivar watchdog/brownout. Prueba fisica a cargo del usuario.

Tres modos Kconfig independientes: convencional, adaptativo simulado y conectado.
Simulador deshabilitado en conectado. Mantener cola FreeRTOS de longituduno y
separacion entre red, control, simulacion y eventos Wi-Fi. Secciones criticas
breves para copias/contadores; nunca sockets, GPIO, logging ni esperas dentro.

Prioridad sin cambios: D=N1-N2, umbral2, incremento2000ms, verde5000..13000ms,
amarillo2000ms y rojo total1000ms. Alternancia obligatoria incluso con cero.
Elegir y congelar verde al entrar; no reiniciar tiempos por conteos nuevos.
Objetivo nominal sin verde20s (maximo nominal19s en operacion continua), sin
prometer cota fisica durante seguro, retrasos, reset o averias.

## Comunicacion vigente: tarea07.2

Solo PC -> C6, UDP ASCII `secuencia,N1,N2,valido`, puerto5005 configurable.
No conservar dos protocolos operativos. Retirar SE07, HMAC, claves, nonces,
asociaciones, solicitudes, RTT y reconocimientos por red. Sin bibliotecas nuevas.
Cuatro campos canonicos sin espacios/saltos: secuencia1..UINT64_MAX, conteos0..1000,
valido0/1, maximo48bytes. Una foto nueva vigente produce un solo envio valido;
invalidacion explicita con valido0 no representa cero vehiculos medidos.

Timeout LOCAL inicial5s desde observacion nueva valida, configurable. Duplicados
y malformados no lo renuevan. Invalidacion critica retenida con generacion local
hasta ser atendida por el propietario. Conectado inicia ambos rojos, completa
amarillo/rojo ante fallo y queda seguro. Recuperacion solo con observacion nueva
recibida desde seguro, seguida de rojo inicial completo. No cancelar despejes.
Reiniciar referencia de secuencia de Python solo tras caducar demanda previa y
alcanzar seguro atendido. IP del emisor opcionalmente restringida en C6.
LAN privada controlada: UDP no garantiza entrega, autenticacion ni edad de
origen/transporte. sendto correcto solo confirma envio local.

## Vision artificial

YOLO11x original local yolo11x.pt, CPU/PyTorch FP32, foto800x600, imgsz960,
confianza0.15, IoU0.45, clases2/3/5/7, agnostic_nms=false, calentamiento3,
hilos de referencia. Mantener mediana desactivada inicialmente y su implementacion.
No descargar, entrenar, cuantizar, exportar ni reinstalar dependencias funcionales.
Venv Python propio separado de IDF. Conservar diagnostico/evaluacion existentes.

Deteccion y conteo son distintos: reconocer y dibujar cajas/confianzas/total
aunque falten ROI; conteos por carril y demanda valida requieren ambas ROI
confirmadas/guardadas. Sin otro modelo ni inferencias duplicadas. Un trabajo
pendiente reemplazable, una inferencia por secuencia y cajas sobre su propia foto.
No convertir falta de calibracion o errores en0/0 valido.

Mantener ROI normalizadas, referencia de resolucion, rechazo de degeneraciones,
cruces y contacto/solapamiento. Marca roi.json.invalidada persistente: conservar
coordenadas y reconfirmar ambas para guardar. V y cambio de resolucion invalidan.
Antes de editar, foto reciente de epoca actual; Enter/G revalidan referencia y
conexion. /status no rejuvenece JPEG. Edad PC desde inicio HTTP, incluidos reintentos.
Guardar originales sin anotaciones; diagnosticos separados. No inventar verdad
manual, exactitud90%, latencia sostenida ni resultados fisicos.

## Archivos, validacion y entrega

No sobrescribir config.json, roi.json, claves heredadas, sdkconfig, fotos ni pesos.
Configuracion nueva opcional: udp.emisor.local.json (activo/IPdestino/puerto).
No versionar configuraciones locales, secretos, binarios, build, venv, fotos,
pesos ni managed_components. Conservar dependencies.lock del gestor oficial.

Ejecutar pruebas Python vigentes, C de estados/GPIO/prioridad/UDP y loopback.
Retirar solo pruebas exclusivas del protocolo eliminado, explicando su reemplazo.
Compilar CAM/esp32 y los tres modos C6/esp32c6 con configuraciones aisladas;
ejecutar pip check y git diff --check. Reportar evidencia y pendientes fisicos.
Comandos de usuario: idf.py --version/menuconfig/build y
idf.py -p COMx -b115200 flash; idf.py -p COMx monitor (puerto real).
Conservar las 90 pruebas Python, cuatro grupos C y cinco tests web. Adaptar solo
includes/enlace a los traslados; no eliminar aserciones para hacer pasar la reforma.
Guias: GUIA_ESTUDIO.md, Proyecto_Final_C6/README.md y PROTOCOLO_UDP07.md,
Vision_Artificial/README.md. Registrar linea base y comparacion antes/despues.
