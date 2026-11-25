#pragma once

#include "esp_err.h"
#include "esp_camera.h"
#include <stdbool.h>
#include <stdint.h>

// Verifica PSRAM y sensor OV2640/OV3660; solo ESP_OK habilita la captura.
esp_err_t camera_inicializar(void);

typedef struct {
    bool inicializada;
    const char *modelo;
    uint16_t pid;
    unsigned int ancho;
    unsigned int alto;
    int calidad;
    uint32_t capturas_correctas;
    uint32_t capturas_fallidas;
} camera_estado_t;

// En éxito entrega el framebuffer Y mantiene el mutex tomado por esta tarea.
// El llamante debe liberar exactamente una vez, incluso si falla el envío HTTP.
// En error no entrega un buffer ni conserva el mutex. Espera de mutex: 1 s.
esp_err_t camera_adquirir(camera_fb_t **imagen, uint32_t *identificador);
void camera_liberar(camera_fb_t *imagen);

// Solo acepta QVGA/VGA/SVGA y calidad 10..40. Reinicia buffers bajo el mutex;
// si falla, intenta restaurar la configuración previa una sola vez.
esp_err_t camera_reconfigurar(framesize_t resolucion, int calidad);
esp_err_t camera_obtener_estado(camera_estado_t *estado);

// Captura y registra una imagen; devuelve siempre el framebuffer adquirido.
// El contador solo aumenta con metadatos y marcadores JPEG válidos.
esp_err_t camera_capturar_registrar(void);

// Informa memoria interna y PSRAM libres, mínimo histórico y bloque mayor.
void camera_registrar_memoria(void);
