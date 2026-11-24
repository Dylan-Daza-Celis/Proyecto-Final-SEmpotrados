#pragma once

#include "esp_err.h"

// API de uso secuencial desde app_main; no utilizar desde tareas concurrentes.
// Verifica PSRAM y sensor OV2640/OV3660; solo ESP_OK habilita la captura.
esp_err_t camera_inicializar(void);

// Captura y registra una imagen; devuelve siempre el framebuffer adquirido.
// El contador solo aumenta cuando los metadatos corresponden a JPEG QVGA.
esp_err_t camera_capturar_registrar(void);

// Informa memoria interna y PSRAM libres, mínimo histórico y bloque mayor.
void camera_registrar_memoria(void);
