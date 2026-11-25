# Tarea 03 — Cliente Python y calibración de dos ROI

Práctica **1.4**: recibe fotografías individuales de la ESP32-CAM por HTTP,
decodifica con OpenCV, permite dibujar dos polígonos y guarda JPEG originales
para el futuro dataset. No realiza detección de vehículos, entrenamiento ni UDP.
Los firmware de cámara y C6 permanecen sin cambios.

## Estado de las pruebas

- El usuario confirmó 19 capturas de 1.1 con memoria estable y sensor **OV3660**.
- Wi-Fi/HTTP de 1.2/1.3 tiene compilación verificada; su prueba física y la calidad
  visual siguen pendientes de evidencia del usuario.
- Este cliente se prueba con respuestas HTTP simuladas y fotografías sintéticas
  generadas localmente. Eso no acredita recepción real, encuadre ni calibración
  de la maqueta. **No hay coordenadas definitivas preconfiguradas.**

## Instalación en Windows

Usar **Python 3.11 de 64 bits**, Visual Studio Code y una terminal PowerShell
normal. Descargar Python desde [python.org](https://www.python.org/downloads/)
si hace falta. El paquete OpenCV incluye soporte de ventana; no instalar
opencv-python-headless en este entorno.

Desde la raíz del repositorio:

```powershell
cd Vision_Artificial
py -3.11 --version
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.example.json config.json
```

Si config.json ya existe, conservarlo y editarlo en vez de volver a copiar la
plantilla. Los comandos usan directamente el ejecutable del entorno: **no es
necesario activar scripts ni cambiar la política de ejecución de PowerShell**.
En VS Code seleccionar como intérprete `Vision_Artificial\.venv\Scripts\python.exe`.
No ejecutar pip dentro del venv de ESP-IDF ni instalar estas dependencias allí.

La referencia verificada usa OpenCV-Python 4.12.0.88, NumPy 2.2.6 y Requests
2.32.5, fijados en requirements.txt. unittest pertenece a la biblioteca estándar;
no se necesita pytest. La carpeta vacía heredada `Vision Artificial/` se conserva;
la implementación de esta tarea está únicamente en **Vision_Artificial/**.

## Configurar la cámara

Primero programar el firmware HTTP de la tarea 02 y comprobar la IPv4 en el
monitor serie. Computadora y cámara deben estar en la misma LAN. La guía de
[Proyecto_Final_Cam](../Proyecto_Final_Cam/README.md) explica ese procedimiento.
En este cliente no se introducen credenciales Wi-Fi: las gestiona la cámara.

Editar el **config.json local**:

| Campo | Uso |
| --- | --- |
| url_base | IPv4 o URL base anunciada por la cámara, sin `/capture` al final |
| timeout_conexion_s | Espera de conexión, inicialmente 3 s |
| timeout_lectura_s | Espera por inactividad de lectura, inicialmente 15 s |
| intervalo_captura_s | Objetivo entre inicios de ciclos completos, inicialmente 1 s |
| reintentos | Reintentos HTTP adicionales, inicialmente 2 (máximo 5) |
| pausa_reintento_s | Pausa entre reintentos: base × número de intento |
| directorio_almacenamiento | Carpeta de JPEG originales y metadatos, por defecto capturas |
| ruta_roi | Archivo local de calibración, por defecto roi.json |

Los tiempos deben estar entre 0.05 y 60 segundos. Las rutas relativas se resuelven
contra la carpeta del archivo de configuración, no contra el directorio desde el
que se lanzó Python. La plantilla y el config.json creado inicialmente dejan la
URL vacía para que no haya una dirección real publicada.

Ejecutar desde Vision_Artificial:

```powershell
.\.venv\Scripts\python.exe main.py
```

También se puede sobrescribir la URL sin modificar config.json, reemplazando el
marcador IP-DE-LA-CAMARA por la dirección real:

```powershell
.\.venv\Scripts\python.exe main.py --url http://IP-DE-LA-CAMARA
.\.venv\Scripts\python.exe main.py --config config.json --url http://IP-DE-LA-CAMARA
.\.venv\Scripts\python.exe main.py --help
```

## Contrato HTTP y adquisición

Se consulta **GET /status** y después **GET /capture**, siempre secuencialmente.
No se utiliza VideoCapture: `/capture` es un JPEG individual, no MJPEG.
No se modifica la configuración de la cámara ni se llama a POST /control desde
este programa. Para cambiar resolución/calidad usar la interfaz web de la tarea
02 antes de calibrar y evitar controles de otros clientes durante la sesión.

El cliente exige HTTP 200, application/json o image/jpeg según la ruta, límite
de tamaño (64 KiB para estado y 5 MiB para JPEG), marcadores SOI/EOI y una matriz
BGR válida tras cv2.imdecode(np.frombuffer(...)). Content-Type puede incluir
parámetros como charset. No sigue redirecciones ni usa proxies del entorno.
Conserva X-Capture-Id cuando existe; su ausencia se muestra como no disponible.

Del JSON real se usan camera_ready, sensor, width, height y quality. Los demás
campos reales recibidos se conservan como instantánea en los metadatos. La calidad
se registra como **reportada por /status**, solo si sus dimensiones coinciden:
el firmware no incluye calidad en el encabezado de cada JPEG. Otro cliente que
reconfigure entre /status y /capture puede desactualizar ese dato.

Se mide recepción y decodificación con relojes monotónicos. La frecuencia efectiva
es la inversa del tiempo entre capturas válidas consecutivas; errores y pausas
pueden reducirla. Si HTTP tarda más de un segundo, no se superponen solicitudes
para intentar recuperar el tiempo. Los reintentos de transporte/HTTP esperan
pausas controladas; un JPEG que no decodifica se informa y se intenta de nuevo
en el siguiente ciclo. Todas las respuestas y la Session se cierran correctamente.

Un único hilo maneja HTTP y conserva **solo la última captura**, sin cola de
fotografías. El hilo principal procesa la ventana/teclado cada 30 ms incluso
durante un timeout. Requests limita inactividad por lectura; se verifica además
el tiempo transcurrido entre bloques. Sus timeouts no son una garantía estricta
de duración total en redes que entregan datos muy lentamente.

## Ventana y controles

La fotografía se presenta a tamaño nativo con un panel debajo: estado de conexión,
dimensiones reales, bytes JPEG, ID, recepción/decodificación, Hz y edad de imagen.
NUEVA indica actualización; ULTIMA es la foto conservada entre solicitudes;
PAUSADA es la referencia congelada. Si falla HTTP o no se confirma conexión
durante más de max(5 s, 3 × intervalo), aparece **IMAGEN ANTIGUA** y se impide
guardar. No confundir un ID repetido tras reinicio con una sesión global única.

| Control | Acción |
| --- | --- |
| S | Guardar los bytes originales de la fotografía visible |
| 1 / 2 | Pausar y seleccionar/editar ROI 1 o ROI 2 |
| Clic izquierdo | Añadir vértice dentro de la fotografía |
| Clic derecho | Quitar el último vértice del borrador |
| Enter | Validar y confirmar el polígono activo |
| R | Borrar ROI activa en memoria y limpiar el borrador |
| G | Guardar la calibración de ambas ROI confirmadas |
| Espacio | Pausar/reanudar; reanudar abandona un borrador no confirmado |
| Q / Escape / cerrar ventana | Salir y cerrar conexiones |

Al pausar no se solicitan nuevas fotografías, pero continúan las consultas de
estado para detectar desconexión. Una captura ya en curso puede terminar en el
buzón sin cambiar la referencia pausada. Al salir se cierra la ventana y se espera
a que termine/cancele la lectura HTTP en curso; no se mata el hilo ni se cierra su
sesión desde otro hilo. Una red lenta puede retrasar esa salida.

## Calibrar los dos carriles

1. Fijar cámara elevada en diagonal, iluminación y resolución. Recibir una imagen
   nítida de la maqueta de 45 × 44 cm.
2. Pulsar 1. Dibujar la **zona de espera del primer carril** siguiendo sus bordes.
   Seleccionar al menos tres vértices, sin repetir el primero, y pulsar Enter.
3. Pulsar 2 y repetir para la **zona de espera del segundo carril**.
4. Excluir **convergencia y camino de salida**. Dejar separación entre regiones.
5. Si una región necesita corrección, seleccionarla con 1/2 y usar clic derecho
   para deshacer vértices o R para redibujarla. Enter confirma; G persiste ambas.
6. Reanudar con Espacio y comprobar que los polígonos coinciden con las zonas.

Se admiten polígonos simples, también cóncavos, de 3 a 64 vértices. Se rechazan
puntos fuera de imagen, no finitos o repetidos, tres vértices consecutivos alineados,
área casi nula y autointersecciones. También se rechazan contención, cruces y
**contacto entre los bordes** de las ROI para evitar asignaciones ambiguas.
La región previa se mantiene si falla una confirmación, excepto cuando el usuario
la borró expresamente con R. G requiere ambas regiones válidas y ningún borrador.

roi.json contiene versión, resolución de referencia y coordenadas normalizadas:
`x/(ancho-1), y/(alto-1)`. Así el último píxel corresponde a 1. Al cargar se
revalidan polígonos y se reconstruyen coordenadas para la resolución de la imagen.
No se publican coordenadas inventadas. El archivo se reemplaza de forma atómica
al guardar; una configuración inválida se informa y no se sobrescribe al arrancar.

**Cambiar orientación, perspectiva o campo visual exige recalibrar**, aunque la
resolución sea igual. Un cambio de resolución muestra aviso; normalizar coordenadas
solo conserva proporciones, no corrige recortes ni perspectiva. Verificar el
encuadre real y recalibrar cuando corresponda.

API reutilizable para una futura detección, sin implementarla todavía:

```python
from roi_manager import GestorROI
regiones = GestorROI.cargar("roi.json")
pertenece = regiones.contiene_punto(1, (x, y), (ancho, alto))
```

Usa cv2.pointPolygonTest; incluye el borde, devuelve False fuera de la imagen o
si no existe esa región. El punto debe estar en coordenadas de la imagen actual.

## Guardado y futuro dataset

S guarda el **JPEG recibido sin recodificarlo**, no el lienzo de la ventana.
Los polígonos y textos se dibujan en copias. No se exportan imágenes anotadas
como entrenamiento ni se guardan diagnósticos automáticamente.

Cada nombre combina fecha/hora UTC, ID saneado y UUID. Se abre en modo exclusivo
para no sobrescribir. metadatos.jsonl incluye archivo, sesión, SHA-256, fechas,
resolución, bytes, ID, calidad reportada, estado y tiempos. SHA-256 evita duplicados
exactos, incluso después de reiniciar el programa, mientras se conserve el índice
de metadatos. No identifica imágenes casi iguales. Utilizar una sola instancia
escritora por directorio y no editar el índice mientras se recopilan fotografías.

Si se pierde la conexión se conserva la foto a modo de referencia visual, pero
S queda deshabilitada cuando el fallo es conocido o la confirmación está caducada.
Una referencia pausada puede guardarse mientras /status confirma conexión;
volver a pulsar S para el mismo JPEG no crea otra copia.

La estructura preparada permanece vacía de imágenes y etiquetas:

```text
capturas/                  # JPEG originales + metadatos.jsonl
dataset/
  images/
    train/
    val/
    test/
  labels/
    train/
    val/
    test/
```

No hay reparto train/val/test, etiquetas, red neuronal ni conteo. En el futuro
agrupar por sesión/escena al dividir el dataset: fotogramas casi idénticos de una
misma sesión deben permanecer en el mismo conjunto para evitar contaminación de
la evaluación. Las carpetas generadas, venv, configuración local y pesos futuros
están ignorados por Git; solo se versionan placeholders vacíos.

## Pruebas automatizadas

Desde Vision_Artificial, sin cámara, sin Internet y sin abrir ventanas:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Las pruebas generan JPEG con OpenCV, simulan Responses de Requests y ejercitan
geometría, persistencia, guardado y controles del visualizador sin HighGUI.
También verifican que el buzón conserve la última imagen y que pausar no inicie
nuevas capturas. Resultado real del **24 de noviembre de 2026**: **29 pruebas
correctas**, Python 3.11.15, OpenCV 4.12.0 (distribución 4.12.0.88), NumPy 2.2.6 y
Requests 2.32.5. También se comprobó main.py --help y compatibilidad de dependencias.
El entorno de validación se creó en Vision_Artificial/.venv usando un intérprete
base 3.11, sin instalar paquetes en el venv de ESP-IDF ni cambiar su configuración.

## Diagnóstico y límites

| Síntoma | Revisión |
| --- | --- |
| py -3.11 no disponible | Instalar Python 3.11 x64 o usar la ruta completa de su python.exe para crear .venv |
| Falta cv2/NumPy/Requests | Usar el intérprete de Vision_Artificial/.venv e instalar requirements.txt |
| url_base vacía / configuración inválida | Editar config.json local o indicar --url; revisar tiempos/rutas |
| HTTP 503 | Cámara ocupada o captura inválida; revisar monitor serie y esperar reintento |
| Error de conexión/timeout | IP vigente, misma LAN, firmware HTTP, punto de acceso y aislamiento de clientes |
| Content-Type inesperado | URL base incorrecta, portal cautivo u otro servidor; no añadir /capture a url_base |
| JPEG incompleto/no decodificable | Revisar alimentación, cinta y monitor; los marcadores por sí solos no prueban corrección |
| No aparece ventana | Usar sesión de escritorio y opencv-python, no variante headless; comprobar intérprete VS Code |
| G rechaza guardar | Confirmar ambas ROI con Enter y corregir cruces/contacto/área nula |
| Error al cargar roi.json | Corregir el archivo o renombrarlo localmente a roi.json.bak y recalibrar |
| S rechaza duplicado | El JPEG ya está indexado; cambiar físicamente la escena antes de otra captura |
| Metadatos corruptos | Conservar copia local y revisar la línea indicada; no eliminar el índice para forzar duplicados |

La visualización HighGUI en Windows, recepción de la placa, calibración definitiva
y calidad visual requieren prueba física del usuario. Las pruebas simuladas no
convierten esos puntos en completados. El firmware no se recompila ni modifica
durante esta tarea.

Referencias: [OpenCV imdecode](https://docs.opencv.org/4.12.0/d4/da8/group__imgcodecs.html),
[pointPolygonTest](https://docs.opencv.org/4.12.0/d3/dc0/group__imgproc__shape.html),
[Requests y timeouts](https://requests.readthedocs.io/en/latest/user/quickstart/#timeouts),
y las versiones verificadas en PyPI de
[OpenCV-Python](https://pypi.org/project/opencv-python/4.12.0.88/),
[NumPy](https://pypi.org/project/numpy/2.2.6/) y
[Requests](https://pypi.org/project/requests/2.32.5/).
