# Semáforo inteligente — Sistemas Empotrados

Proyecto final universitario sobre una maqueta de **45 × 44 cm** con intersección
en Y. Dos entradas comparten una salida. La cantidad de vehículos de juguete en
cada entrada determinará su prioridad; cada vehículo tiene el mismo peso.

## Arquitectura prevista

```text
ESP32-CAM / cámara -- imágenes por Wi-Fi --> Computadora
                                             |
                                  detector + ROI 1 / ROI 2
                                             |
                                        conteos UDP
                                             v
                                          ESP32-C6
                                             |
                                   estados + prioridad + 6 LEDs
```

La computadora permanecerá conectada. Hará detección neuronal y conteo dentro de
dos ROI: espera izquierda y derecha; convergencia y salida se excluyen. La lógica
de circulación y el control de LEDs permanecerán en la C6.

`D = N1 - N2`: D ≥ 2 prioriza carril 1; D ≤ -2 prioriza carril 2; |D| < 2 produce
alternancia. Los tiempos iniciales serán verde mínimo 5 s, máximo 15 s, amarillo
2 s y rojo total 1 s, con espera máxima objetivo 20 s. Se deberá validar su
coherencia y evitar esperas indefinidas. Nunca se permitirán ambos verdes; la
pérdida de datos válidos llevará de forma controlada a ambos rojos.

## Hardware disponible

- ESP32-CAM y base ESP32-CAM-MB USB-UART CH340G. Se había previsto una OV2640
  de 2 MP; el registro UART aportado por el usuario identificó **OV3660**.
- ESP32-C6 y una ESP32 clásica adicional para pruebas.
- Computadora, soporte elevado fijo para cámara diagonal y vehículos de juguete.
- Dos LEDs de cada color: rojo, amarillo y verde; seis resistencias de 330 Ω.
- Maqueta en Y de 45 × 44 cm.

El registro confirma PSRAM física de 8 MiB, 4 MiB mapeados al heap y prueba de
memoria correcta. El pinout AI Thinker permitió detectar e inicializar el sensor;
la adquisición de imágenes con la corrección para OV3660 sigue pendiente.

## Proyectos y estado

| Carpeta | Target | Responsabilidad | Estado |
| --- | --- | --- | --- |
| `Proyecto_Final_Cam/` | `esp32` | Captura y posterior envío de imágenes | Práctica 1.1 implementada; validación en su README |
| `Proyecto_Final_C6/` | `esp32c6` | Semáforos y decisiones | Plantilla existente, sin cambios en 1.1 |
| `Vision Artificial/` | Computadora | Detector, ROI y conteos | Desarrollo posterior |

Solo se implementa la práctica **1.1**. Su firmware captura JPEG QVGA, informa
metadatos por UART y devuelve el buffer. No almacena ni transmite imágenes.
La captura física sigue pendiente de prueba por el usuario.

Compilación verificada el **24 de noviembre de 2026** con ESP-IDF **v6.0.2** y
target `esp32`: `idf.py set-target esp32` e `idf.py build` finalizaron correctamente.
El usuario programó esa versión por COM12 y aportó el registro de arranque:
el componente inicializó la OV3660, pero la validación de la aplicación detuvo
la captura porque exigía OV2640. Se ajustó para aceptar ambos sensores y registrar
su modelo real. Los resultados de compilación y los límites de la prueba física
están en la guía de cámara.

## Etapas

| Etapa | Trabajo |
| --- | --- |
| 1.1 | Inicializar cámara OV2640/OV3660 y capturar JPEG periódicamente |
| 1.2–1.4 | Wi-Fi, servidor HTTP JPEG y recepción Python/OpenCV |
| 2.1–2.3 | Dataset de juguetes, detector neuronal, ROI y conteo |
| 3.1–3.4 | GPIO C6, estados, prioridades simuladas y organización FreeRTOS |
| 4.1–4.3 | UDP, integración y validación de modo seguro |
| 5.1–5.2 | Experimentos, documentación y demostración |

## Desarrollo

Firmware en C con ESP-IDF nativo, VS Code y extensión oficial Espressif; sin
Arduino ni PlatformIO. El entorno local declara ESP-IDF v6.0.2. Verificar con
`idf.py --version` antes de compilar. Las rutas locales de `.vscode` no son
obligatorias para otras máquinas y no se cambia la instalación del usuario.

Seguir [AGENTS.md](AGENTS.md) y la [guía completa de cámara](Proyecto_Final_Cam/README.md).
Usar ramas y PR hacia `master`; no versionar compilaciones, componentes descargados
ni secretos. Conservar el bloqueo de dependencias generado por Component Manager.
