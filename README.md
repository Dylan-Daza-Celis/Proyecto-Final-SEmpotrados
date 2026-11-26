# Semaforo inteligente ? Sistemas Empotrados

Maqueta de45 ?44cm con dos entradas que convergen en una salida. Cada carril
usa LEDs rojo, amarillo y verde con resistencias individuales de330?.

```text
ESP32-CAM -- HTTP/JPEG --> PC (YOLO11x + ROI) -- UDP ASCII --> ESP32-C6
                                                               |
                                                    prioridad + estados + GPIO
```

**Tarea07.2:** comunicacion unidireccional sencilla. El PC envia
`secuencia,N1,N2,valido`; C6 recibe, valida y decide. Puerto inicial5005,
timeout local5s. El protocolo anterior queda en el historial Git (ebe261a).
La rama sigue siendo feat/integration-udp-07 y el trabajo se revisa en el PR8,
sin fusionar PR anteriores ni modificar master o el firmware de CAM.

## Hardware, FreeRTOS y control

[Guia C6 y cableado](Proyecto_Final_C6/README.md): una tarea propietaria GPIO,
receptor UDP separado, eventos Wi-Fi y cola de ultimo valor. No hay control
remoto directo de LEDs. Confirmar placa y esquema antes de habilitar GPIO;
los GPIO10/11 provisionales pueden no estar expuestos en variantes SiP.

Tres modos: convencional, adaptativo simulado y adaptativo conectado. El
conectado inicia ambos rojos. Resultado invalido, timeout o perdida Wi-Fi inicia
amarillo completo, rojo total y seguro. La invalidacion se retiene aunque llegue
otro conteo. Se recupera desde seguro con una observacion nueva y rojo inicial.

Prioridad: D=N1-N2, umbral2, verde5..13s e incremento2s por nivel; amarillo2s y
rojo total1s. Alternancia obligatoria, duracion congelada al entrar. Nunca ambos
verdes. Objetivo nominal sin verde20s, maximo nominal19s durante operacion
continua. No se garantiza ese limite durante fallos, seguro o retrasos.

## Vision y configuracion

[Guia Python](Vision_Artificial/README.md): YOLO11x original, PyTorch FP32 CPU,
SVGA800x600, imgsz960, confianza0.15, IoU0.45, clases2/3/5/7, NMSfalse,
tres calentamientos y hilos de referencia. Sin entrenamiento ni nuevo modelo.

YOLO reconoce y muestra cajas/confianzas/total aunque no haya ROI calibradas.
Los conteos por carril y el envio de demanda valida requieren ambas ROI
confirmadas y guardadas. Conserva invalidacion persistente y referencias de
recalibracion. Configuraciones, fotografias, ROI y pesos locales se conservan.

[Configurar UDP PC -> C6](Proyecto_Final_C6/PROTOCOLO_UDP07.md): IP de C6 y puerto
en udp.emisor.local.json; SSID y opcion de IP emisora en menuconfig C6. Solo LAN
privada controlada. UDP no garantiza entrega, autenticacion ni antiguedad de un
paquete en transito. El timeout mide tiempo local desde recepcion. sendto no
confirma que C6 recibiera el mensaje.

## Validacion

90 pruebas Python y cuatro grupos C correctos, ademas de UDP loopback.
Tres modos compilados con ESP-IDF nativo v6.0.2/esp32c6 y configuraciones aisladas;
programacion y prueba fisica desde VS Code a cargo del usuario. Verificar version
efectiva antes de compilar. No Arduino ni PlatformIO; no cambiar instalacion.

La exactitud vehicular y los tiempos fisicos de LAN/LED siguen pendientes. No
hay anotaciones manuales locales para afirmar90% de escenas correctas. Los
resultados historicos de diagnostico y evaluacion se conservan en sus guias.

Camara: [configuracion y pruebas previas](Proyecto_Final_Cam/README.md).
Licencia neuronal: [Ultralytics AGPL/Enterprise](Vision_Artificial/LICENCIAS_IA.md).
Instrucciones de desarrollo: [AGENTS.md](AGENTS.md).
