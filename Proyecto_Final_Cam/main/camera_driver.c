#include "camera_driver.h"
#include "camera_pinout.h"

#include <inttypes.h>
#include <stdbool.h>
#include "esp_camera.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_psram.h"

static const char *TAG = "camera_driver";
static bool camara_inicializada;
static uint32_t imagenes_capturadas;

void camera_registrar_memoria(void)
{
    const uint32_t capacidades_internas = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
    const uint32_t capacidades_psram = MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT;
    ESP_LOGI(TAG, "RAM interna: libre=%zu, mínimo=%zu, bloque mayor=%zu bytes",
             heap_caps_get_free_size(capacidades_internas),
             heap_caps_get_minimum_free_size(capacidades_internas),
             heap_caps_get_largest_free_block(capacidades_internas));
    ESP_LOGI(TAG, "PSRAM: libre=%zu, mínimo=%zu, bloque mayor=%zu bytes",
             heap_caps_get_free_size(capacidades_psram),
             heap_caps_get_minimum_free_size(capacidades_psram),
             heap_caps_get_largest_free_block(capacidades_psram));
}

esp_err_t camera_inicializar(void)
{
    if (camara_inicializada) {
        ESP_LOGW(TAG, "La cámara ya está inicializada.");
        return ESP_ERR_INVALID_STATE;
    }

    if (!esp_psram_is_initialized() || esp_psram_get_size() == 0) {
        ESP_LOGE(TAG, "PSRAM no disponible. Verifique placa, alimentación y sdkconfig.defaults.");
        return ESP_ERR_NOT_FOUND;
    }
    if (heap_caps_get_free_size(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT) == 0) {
        ESP_LOGE(TAG, "PSRAM detectada pero sin memoria asignable al framebuffer.");
        return ESP_ERR_NO_MEM;
    }
    ESP_LOGI(TAG, "PSRAM detectada: %zu bytes", esp_psram_get_size());

    const camera_config_t configuracion = {
        .pin_pwdn = CAMERA_PIN_PWDN,
        .pin_reset = CAMERA_PIN_RESET,
        .pin_xclk = CAMERA_PIN_XCLK,
        .pin_sccb_sda = CAMERA_PIN_SIOD,
        .pin_sccb_scl = CAMERA_PIN_SIOC,
        .pin_d0 = CAMERA_PIN_D0,
        .pin_d1 = CAMERA_PIN_D1,
        .pin_d2 = CAMERA_PIN_D2,
        .pin_d3 = CAMERA_PIN_D3,
        .pin_d4 = CAMERA_PIN_D4,
        .pin_d5 = CAMERA_PIN_D5,
        .pin_d6 = CAMERA_PIN_D6,
        .pin_d7 = CAMERA_PIN_D7,
        .pin_vsync = CAMERA_PIN_VSYNC,
        .pin_href = CAMERA_PIN_HREF,
        .pin_pclk = CAMERA_PIN_PCLK,
        .xclk_freq_hz = 20000000,
        .ledc_timer = LEDC_TIMER_0,
        .ledc_channel = LEDC_CHANNEL_0,
        .pixel_format = PIXFORMAT_JPEG,
        .frame_size = FRAMESIZE_QVGA,
        .jpeg_quality = 12,
        .fb_count = 1,
        .fb_location = CAMERA_FB_IN_PSRAM,
        .grab_mode = CAMERA_GRAB_WHEN_EMPTY,
        .sccb_i2c_port = 0,
        .jpeg_buffer_size = 0, // Tamaño automático del componente 2.1.9.
    };

    const esp_err_t resultado = esp_camera_init(&configuracion);
    if (resultado != ESP_OK) {
        ESP_LOGE(TAG, "esp_camera_init falló: %s (0x%x)",
                 esp_err_to_name(resultado), (unsigned int)resultado);
        camera_registrar_memoria();
        return resultado;
    }

    const sensor_t *sensor = esp_camera_sensor_get();
    if (sensor == NULL || sensor->id.PID != OV2640_PID) {
        ESP_LOGE(TAG, "Se esperaba OV2640; PID detectado=0x%x",
                 sensor == NULL ? 0 : (unsigned int)sensor->id.PID);
        const esp_err_t resultado_liberacion = esp_camera_deinit();
        if (resultado_liberacion != ESP_OK) {
            ESP_LOGE(TAG, "No se pudo liberar el controlador: %s (0x%x)",
                     esp_err_to_name(resultado_liberacion), (unsigned int)resultado_liberacion);
        }
        return ESP_ERR_NOT_SUPPORTED;
    }

    camara_inicializada = true;
    imagenes_capturadas = 0;
    ESP_LOGI(TAG, "OV2640 inicializada: JPEG QVGA 320x240, calidad=12, XCLK=20 MHz, 1 framebuffer en PSRAM.");
    return ESP_OK;
}

esp_err_t camera_capturar_registrar(void)
{
    if (!camara_inicializada) {
        ESP_LOGE(TAG, "Captura rechazada: cámara sin inicializar.");
        return ESP_ERR_INVALID_STATE;
    }

    camera_fb_t *imagen = esp_camera_fb_get();
    if (imagen == NULL) {
        ESP_LOGE(TAG, "esp_camera_fb_get no entregó una imagen.");
        return ESP_FAIL;
    }

    esp_err_t resultado = ESP_OK;
    if (imagen->buf == NULL || imagen->len == 0 || imagen->format != PIXFORMAT_JPEG ||
        imagen->width != 320 || imagen->height != 240) {
        ESP_LOGW(TAG, "Imagen descartada: %zux%zu, formato=%d, tamaño=%zu bytes",
                 imagen->width, imagen->height, (int)imagen->format, imagen->len);
        resultado = ESP_ERR_INVALID_RESPONSE;
    } else {
        ++imagenes_capturadas;
        ESP_LOGI(TAG, "Imagen #%" PRIu32 ": %zux%zu, formato=JPEG (%d), tamaño=%zu bytes",
                 imagenes_capturadas, imagen->width, imagen->height,
                 (int)imagen->format, imagen->len);
    }

    // Único punto de devolución: cubre tanto imágenes válidas como descartadas.
    // No acceder a imagen ni a imagen->buf después de esta llamada.
    esp_camera_fb_return(imagen);
    return resultado;
}
