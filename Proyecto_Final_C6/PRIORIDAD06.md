# Tarea 06 B: prioridad adaptativa con demanda simulada

Se mantiene el mismo pinout **provisional** y una única tarea propietaria GPIO.
No se habilitan salidas sin SEMAFORO_PINOUT_CONFIRMADO. No hay Wi-Fi, UDP ni
conteos de YOLO: el algoritmo usa solo escenarios simulados o ausencia explícita.

## Matemática y validación

prioridad_vehicular.c/.h no dependen de GPIO ni FreeRTOS. Parámetros iniciales:
verde mínimo 5000 ms, máximo 13000 ms, amarillo 2000 ms, rojo total 1000 ms,
umbral 2, incremento por nivel 2000 ms y objetivo nominal sin verde 20000 ms.

D=N1−N2. Si |D|<2, ambos verdes son 5000 ms. En otro caso:

`incremento = min(verde_max - verde_min, incremento_por_nivel * (|D| - umbral + 1))`.

Para umbral 2 coincide con 2000×(|D|−1). El carril favorecido suma el incremento
al mínimo y el otro conserva su mínimo, aunque tenga cero vehículos. El límite
se deriva de máximo−mínimo, no de una constante 8000. Se validan conteos 0..1000,
parámetros y aritmética intermedia de 64 bits antes de convertir a duraciones.

| D | Verde 1 | Verde 2 |
| --- | --- | --- |
| −5 o menor | 5 s | 13 s |
| −4 | 5 s | 11 s |
| −3 | 5 s | 9 s |
| −2 | 5 s | 7 s |
| −1, 0, 1 | 5 s | 5 s |
| 2 | 7 s | 5 s |
| 3 | 9 s | 5 s |
| 4 | 11 s | 5 s |
| 5 o mayor | 13 s | 5 s |

La espera se define desde el **fin del verde propio** hasta el comienzo del
siguiente verde propio. Siempre se alternan carriles, sin turnos repetidos ni
saltos. Límite nominal: amarillo propio + rojo + verde contrario máximo + amarillo
contrario + rojo = **2+1+13+2+1=19 s**. La validación exige
`verde_max + 2*amarillo + 2*rojo_total <= objetivo_sin_verde` usando 64 bits.
Por ejemplo, máximo 15 s produciría 21 s y se rechaza con objetivo 20 s.

El margen de 1 s no garantiza tiempo real. Retrasos de planificación, logs,
fallos, reset y permanencia en seguro pueden exceder 20 s. Nunca se recortan
amarillo o rojo para recuperar retrasos. Cada fase empieza tras aplicar GPIO.

## Vigencia y selección al entrar

gestor_demanda.c/.h conserva el último mensaje y la última secuencia consumida.
Una secuencia nueva explícitamente inválida, con rangos erróneos, fecha futura o
edad excesiva **invalida la demanda anterior**. Una duplicada/fuera de orden se
ignora y no rehabilita datos. Una invalidación nueva también consume secuencia.
No se admite reiniciar secuencia en el mismo arranque; futuras sesiones de red
necesitarán un contrato explícito, fuera de esta tarea.

Al entrar en VERDE_CARRIL_1/2 se revisa de nuevo la edad local (inicialmente 5 s),
se toma la demanda válida más reciente y se congela la duración elegida. Los
mensajes posteriores no reinician el temporizador, no alargan/acortan ese verde
y no modifican amarillo/rojo. La siguiente fase usa la información vigente entonces.

Sin demanda vigente, la demostración adaptativa usa el verde mínimo convencional
y registra «sin medición N1/N2»; no inventa una escena medida 0/0. Una demanda
válida 0/0 es distinta: sí es dato simulado, con validez y secuencia. El modo
convencional mantiene sus tiempos configurados aunque reciba demanda.

controlador_solicitar_seguro conserva salida verde→amarillo completo→rojo total
completo→ESTADO_SEGURO. El futuro modo conectado deberá usarla ante pérdida de
datos, pero esta tarea no implementa comunicación ni simula un receptor UDP.

## FreeRTOS, escenarios y monitor

La cola xQueueOverwrite sigue con longitud uno y solo la tarea propietaria
modifica GPIO. El simulador recorre valores en orden: 0/0, 3/3, 4/1, 1/5,
diferencias crecientes 2/0 y 3/0, saturación 5/0, congestión 10/0 sostenida,
cambio 0/10, invalidación explícita y 4/1 seguida de una pausa de diez segundos.
Las demás pausas son de dos segundos. Valores/secuencias son reproducibles;
la alineación exacta con el estado puede variar por planificación. La prueba C
inyecta además cambios en instantes exactos durante un verde.

El monitor registra principalmente mensajes nuevos, transiciones y errores:
modo, estado, N1/N2/D válidos o ausencia, edad, secuencia, carril favorecido,
verde seleccionado y motivo, duración real de la fase e intervalo observado
sin verde de cada carril cuando vuelve a abrir. Advierte si excede el objetivo.
El primer turno no tiene intervalo previo. Las marcas del intervalo son de
software (antes de apagar y después de encender), no medición eléctrica.

## Configurar y compilar en Windows

Desde Proyecto_Final_C6, con terminal oficial ESP-IDF v6.0.2:

```powershell
$env:IDF_TARGET = 'esp32c6'
idf.py --version
idf.py menuconfig
idf.py build
idf.py -p COMx -b 115200 flash monitor
```

En «Semaforos - demostracion autonoma» seleccionar convencional o adaptativo.
Para escenarios habilitar SEMAFORO_SIMULAR_DEMANDA; puede deshabilitarse para
observar el retorno por ausencia de datos. La elección del modo no confirma el
pinout automáticamente. Antes de flash: confirmar placa/esquema y GPIO (en
particular 10/11), capacidad flash, seis resistencias individuales 330 Ω y GND
común. COMx debe ser el puerto real de la C6. No se programó hardware en esta tarea.

Los parámetros son Kconfig y se comprueban otra vez en la lógica. Máximo menor
que mínimo o un intervalo nominal incompatible provoca estado seguro, no ajuste
silencioso. El sdkconfig normal y settings.json locales se conservan; las pruebas
de compilación usan copias bajo .herramientas/ con dos directorios separados.

## Pruebas

```powershell
.\tests\ejecutar_host.ps1 -Compilador "RUTA_REAL\tcc.exe"
```

Si no se permite ejecutar scripts, usar los comandos C99 equivalentes indicados
en README, añadiendo main/prioridad_vehicular.c y main/gestor_demanda.c al enlace.
El segundo ejecutable usa tests/pruebas_prioridad.c con esas dos fuentes y
main/controlador_semaforos.c. Las pruebas compilan las mismas fuentes del firmware.

Se conservan las pruebas anteriores y se añaden simetría, umbral, saturación,
extremos, configuraciones incompatibles, vigencia al usar, invalidación nueva,
duplicados/fuera de orden, congelación y retorno sin datos. La simulación nominal
de 600 s con congestión constante en carril 1 conserva más de veinte aperturas
por carril y obtiene máximos sin verde de 11 s / 19 s. Son instantes del reloj
simulado, no seiscientos segundos de prueba física. Los retrasos y el estado
seguro se ensayan aparte sin atribuirles la cota nominal.

La revisión GPIO del PR #6 ya está en la base: mantiene el rojo contrario,
apaga incompatibles primero y comprueba todas las escrituras intermedias y
fallos. No garantiza hardware durante reset, alimentación ausente o avería.
Faltan medidas físicas de tiempos, secuencia, fallos y confirmación del cableado.

Validación real de tarea 06: ambos ejecutables anfitriones C terminaron con éxito.
ESP-IDF informó v6.0.2 y compiló target esp32c6 en dos configuraciones separadas,
con salidas/simulador habilitados solo en las copias de prueba: convencional
0x21d70 bytes y adaptativo 0x21ee0 bytes, ambos con 87 % libre en app de 1 MiB.
Se conservaron sdkconfig normal y settings.json del usuario. git diff --check
correcto. No se programó la placa ni se midieron intervalos físicos.
