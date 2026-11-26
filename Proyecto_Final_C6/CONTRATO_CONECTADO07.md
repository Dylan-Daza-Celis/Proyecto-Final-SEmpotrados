# Contrato previo: resultados con origen, sesion y vencimiento

**Actualizacion tarea 07:** esta propuesta historica ya tiene implementacion en
la rama de integracion. El formato normativo, configuracion y pruebas estan en
[PROTOCOLO_UDP07.md](PROTOCOLO_UDP07.md). Las referencias siguientes a trabajo
futuro describen el estado del PR #7 antes de implementar red.

Propuesta revisable para tarea 07. **No es un protocolo implementado ni probado
en red**: no añade UDP/Wi-Fi, un receptor simulado ni un tercer modo al firmware.
La prioridad, alternancia, verdes 5..13 s, amarillo 2 s y rojo total 1 s continúan
sin cambios. Las demostraciones convencional y adaptativa siguen independientes
y la ausencia de demanda en demostración conserva su tratamiento actual.

## Identidad y significado del mensaje

El futuro contrato debe separar identidad de envío e identidad de observación:

| Campo propuesto | Regla |
| --- | --- |
| version | Versión de contrato y tipos/rangos comprobados antes de usar conteos |
| emisor_id | Identidad estable del proceso/instalación asociado a esa C6 |
| sesion_emisor | Identificador nuevo por arranque del cliente; no reutilizar la sesión anterior |
| sesion_receptor | Identificador nuevo por arranque C6 y por nueva asociación aceptada |
| epoca_adquisicion | Cambia ante errores/reconexiones de cámara; no reutilizar resultados de época anterior |
| resultado_id | Identidad inmutable de la captura analizada, ligada a sesión/época/secuencia de adquisición |
| secuencia_evento | Aumenta por resultado nuevo o invalidación nueva; un reenvío conserva identidad |
| tipo | resultado, invalidacion o mantenimiento; mantenimiento no habilita control |
| valido, motivo | Distinguir cero válido de JPEG inválido, ROI inválidas, inferencia fallida, pausa y caducidad |
| n1, n2 | Enteros 0..1000 solo con resultado válido; null en invalidaciones/ausencia |
| edad_origen_ms | Edad desde inicio monotónico de la solicitud /capture hasta preparar esta respuesta |
| nonce_solicitud | Correlación con una solicitud pendiente de la C6 para acotar también el transporte |

No existe timestamp fiable de exposición del sensor: el origen sigue siendo el
inicio de /capture, incluidos reintentos, decodificación, espera e inferencia.
La edad no se calcula solo desde fin de inferencia o recepción de un paquete.
Tampoco se comparan directamente relojes monotónicos absolutos de PC y C6: sus
orígenes son distintos. La calidad de una foto previamente almacenada en el sensor
y la precisión de sus relojes siguen siendo limitaciones que se deben declarar.

## Edad al utilizar: incluir el transporte

Un envío que declare «edad 4 s» y permanezca 10 s en tránsito no debe llegar como
recién adquirido. Solo sumar edad declarada y tiempo **desde recepción local**
omite ese retraso. Antes de implementar el modo conectado se debe resolverlo.

Se propone solicitud/respuesta correlacionada, sin sincronizar relojes absolutos:

1. La C6 registra t0 con su reloj monotónico y emite un nonce de uso único.
   Se conserva solo una solicitud pendiente y su plazo; no hay cola ilimitada.
2. Después de recibir ese nonce, el cliente obtiene el resultado más reciente y
   **recalcula** edad_origen_ms con su reloj, redondeando hacia arriba. No copia
   una edad serializada antes de la solicitud, ni cambia el origen de la captura.
3. La C6 comprueba sesión, nonce, resultado nuevo y secuencia. En recepción tr,
   calcula conservadoramente `edad_cota_rx = edad_origen_ms + (tr - t0) + margen_ms`.
   El recorrido t0→tr incluye espera del emisor y transporte; parte de esa espera
   puede contarse dos veces, lo que descarta más datos pero no los rejuvenece.
4. Si la cota supera el presupuesto F acordado, no habilita conteos. Si es válida,
   fija una sola vez `vence_local = t0 + F - edad_origen_ms - margen_ms`.
5. En cada uso y en cada iteración del propietario conectado comprueba el mismo
   vencimiento. La cota de edad al usar es `edad_origen_ms + (ahora - t0) + margen_ms`.

Esta cota supone que la edad se midió después de recibir la solicitud y usa una
base de tiempo con error acotado. El margen de reloj/redondeo debe definirse y
validarse; no se considera demostrado todavía. El RTT observado sí incluye el
retardo variable de la respuesta. Si no puede comprobarse la correlación o esas
condiciones, el resultado no es válido para control. Otra solución exigiría
sincronización con error acotado, no timestamps de pared asumidos equivalentes.

F será el mínimo entre el límite de origen acordado por emisor y receptor; no se
amplía automáticamente por inferencias lentas. No confundirlo con el TTL local
de 5 s del simulador actual. Validar enteros, restas antes de sumar y desbordamientos
en 64 bits; un paquete demasiado antiguo no puede producir un plazo futuro por
underflow. Los ejemplos de abajo son aritméticos, no mediciones de transporte.

## Duplicados, reenvíos, épocas y reinicios

- Un resultado ya aceptado no se vuelve a aceptar por recibir otro paquete, nonce
  o número de envío. Nunca reemplazar su vencimiento por «ahora + TTL».
- La secuencia de envío puede servir para diagnóstico, pero no demuestra que haya
  una foto nueva. resultado_id debe proceder de adquisición real, no del envío.
- Una invalidación con secuencia_evento nueva elimina la demanda utilizable y
  consume esa secuencia. Un resultado anterior reenviado no la rehabilita, aunque
  el reenvío lleve una secuencia de transporte mayor. Se exige resultado nuevo
  posterior a la barrera de invalidación y a la época aceptada.
- Una duplicada o fuera de orden se descarta sin renovar edad ni conectividad de
  datos. Un mantenimiento puede confirmar transporte, pero no vigencia neuronal.
- Una época de adquisición antigua se rechaza. Una nueva exige invalidar el
  resultado anterior y esperar una captura válida de esa época.
- Un reinicio legítimo del emisor crea otra sesión y puede reiniciar secuencias.
  No basta cambiar el UUID en un paquete: la C6 debe aceptar una nueva asociación
  explícita, pasar de forma controlada a seguro y retirar la sesión anterior.
- El arranque C6 crea otra sesion_receptor/nonce y comienza en ambos rojos. Hasta
  completar asociación y recibir resultado fresco, los paquetes de sesiones
  anteriores no habilitan control. Durante una misma sesión no se admite wrap-around.

El manejador de red futuro validará estos campos antes de entregar una demanda
con vencimiento al propietario. No debe asignar solo recibida_ms=ahora y llamar
al gestor de demostración actual: eso perdería la edad previa y la identidad.
Se necesita un estado de sesión/vencimiento separado del modo de simulación.

## Comportamiento del modo conectado futuro

| Situación | Decisión conectada |
| --- | --- |
| Resultado nuevo, vigente y válido, N1=0/N2=0 | Medición cero válida; aplicar algoritmo/alternancia normal |
| No llegaron datos o caducó el resultado | Pérdida de datos; solicitar salida controlada a seguro |
| Invalidación nueva de cámara/ROI/inferencia | Resultado inválido; retirar demanda y solicitar salida controlada |
| Duplicado, mantenimiento o reenvío viejo | No refrescar; si vence la demanda, solicitar seguro |
| Sesión/época antigua | Descartar; no rehabilitar el último resultado |
| Reinicio/sesión nueva aceptada | Retirar asociación anterior y negociar desde estado seguro |

En el futuro modo conectado, controlador_solicitar_seguro interrumpirá el verde
en la siguiente atención del propietario: amarillo completo y rojo total completo,
sin recuperar tiempo perdido, y ESTADO_SEGURO retenido. Si ya estaba en amarillo
o rojo se termina su despeje. La congelación normal del verde no impide esta
salida por seguridad. Ningún hilo de red/interrupción escribe GPIO.

Recibir datos nuevos durante la transición no debe cancelar el despeje y abrir
otro verde. La recuperación necesitará asociación vigente, resultado nuevo válido
y rearme desde ambos rojos con su intervalo inicial. No cambiar automáticamente
a demostración convencional/adaptativa cuando se pierda la conexión. La cota
nominal sin verde de 19 s no aplica durante pérdida de datos, fallos o seguro.

## Casos de aceptación para implementar después

| Caso propuesto | Resultado esperado |
| --- | --- |
| F=12000, edad=4000, RTT=1000, margen=0 | Cota en recepción 5000; quedan 7000 ms, no 12000 |
| Mismo resultado reenviado 3 s después | Mismo vencimiento, ninguna renovación |
| Mismo resultado con nuevo número de envío | Rechazo como observación repetida |
| Edad=11000, RTT=2000, F=12000 | Resultado antiguo; no crear demanda cero |
| Invalidación nueva seguida de reenvío de resultado anterior | Permanece inválido hasta resultado nuevo |
| Emisor reinicia secuencia dentro de sesión anterior | Rechazo por fuera de orden |
| Emisor reinicia con asociación nueva aceptada | Seguro, sesión anterior retirada, esperar resultado nuevo |
| C6 reinicia y llega paquete de su sesión anterior | Rechazo; permanece en rojos iniciales/seguro |
| Dato válido 0/0 frente a ausencia | Solo el primero es conteo medido y utilizable |

Estos son requisitos y ejemplos calculados, **no pruebas ejecutadas de un receptor**.
Pendientes: formato final/serialización, asociación, validadores y pruebas de
secuencias/edad, integración con propietario, red real y mediciones físicas.
La revisión presente conserva y vuelve a ejecutar las pruebas C de demostración;
no modifica ni afirma probar un modo conectado que aún no existe.
Resultado real de esta revisión: los dos ejecutables C existentes terminaron
correctamente y git diff --check pasó. Fuentes de estados, prioridad, GPIO y
simulador idénticas a d8ff15e; no se recompiló firmware ni se hicieron pruebas
físicas porque los cambios de este bloque son únicamente de documentación.

Fuentes para las bases de tiempo: [Python monotonic](https://docs.python.org/3.11/library/time.html#time.monotonic),
[ESP Timer v6.0.2](https://docs.espressif.com/projects/esp-idf/en/v6.0.2/esp32c6/api-reference/system/esp_timer.html).
La cota y el contrato son una propuesta de este proyecto, no una garantía del SDK.
