#include "camera_driver.h"
#include "camera_pinout.h"

#include <inttypes.h>
#include <stdbool.h>
#include "esp_camera.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_psram.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

static const char *TAG = "camera_driver";
static bool camara_inicializada;
static uint32_t imagenes_capturadas;
static uint32_t capturas_fallidas;
static SemaphoreHandle_t mutex_camara;
static camera_config_t configuracion_actual;
static const char *modelo_sensor = "No disponible";
static uint16_t pid_sensor;

static bool tomar_mutex(void)
{
    return mutex_camara != NULL &&
           xSemaphoreTake(mutex_camara, pdMS_TO_TICKS(1000)) == pdTRUE;
}

static bool imagen_valida(const camera_fb_t *imagen)
{
    const resolution_info_t *tamano = &resolution[configuracion_actual.frame_size];
    return imagen->buf != NULL && imagen->len >= 4 &&
           imagen->format == PIXFORMAT_JPEG && imagen->width == tamano->width &&
           imagen->height == tamano->height &&
           imagen->buf[0] == 0xff && imagen->buf[1] == 0xd8 &&
           imagen->buf[imagen->len - 2] == 0xff && imagen->buf[imagen->len - 1] == 0xd9;
}

// Dos intentos de calentamiento, con retorno de todo buffer adquirido.
// NO-SOI viene de la verificación SOI del componente; no se silencia su registro.
static void estabilizar_sensor(void)
{
    vTaskDelay(pdMS_TO_TICKS(200));
    for (int intento = 0; intento < 2; ++intento) {
        camera_fb_t *imagen = esp_camera_fb_get();
        if (imagen != NULL) {
            ESP_LOGI(TAG, "Estabilización %d/2: framebuffer descartado (%zu bytes).",
                     intento + 1, imagen->len);
            esp_camera_fb_return(imagen);
        } else {
            ESP_LOGW(TAG, "Estabilización %d/2: sin framebuffer.", intento + 1);
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

// Se llama exclusivamente con el mutex tomado, o durante el inicio sin clientes.
static esp_err_t iniciar_controlador(const camera_config_t *configuracion)
{
    esp_err_t resultado = esp_camera_init(configuracion);
    if (resultado != ESP_OK) {
        ESP_LOGE(TAG, "esp_camera_init falló: %s (0x%x)",
                 esp_err_to_name(resultado), (unsigned int)resultado);
        return resultado;
    }
    const sensor_t *sensor = esp_camera_sensor_get();
    if (sensor == NULL || (sensor->id.PID != OV2640_PID && sensor->id.PID != OV3660_PID)) {
        ESP_LOGE(TAG, "Se esperaba OV2640 u OV3660; PID=0x%x",
                 sensor == NULL ? 0 : (unsigned int)sensor->id.PID);
        const esp_err_t error_liberacion = esp_camera_deinit();
        if (error_liberacion != ESP_OK) {
            ESP_LOGE(TAG, "Error al liberar cámara: %s", esp_err_to_name(error_liberacion));
        }
        return ESP_ERR_NOT_SUPPORTED;
    }
    configuracion_actual = *configuracion;
    pid_sensor = sensor->id.PID;
    modelo_sensor = pid_sensor == OV3660_PID ? "OV3660" : "OV2640";
    camara_inicializada = true;
    estabilizar_sensor();
    ESP_LOGI(TAG, "%s inicializada (PID=0x%x): JPEG %dx%d, calidad=%d, XCLK=20 MHz, 1 framebuffer en PSRAM.",
             modelo_sensor, pid_sensor, resolution[configuracion->frame_size].width,
             resolution[configuracion->frame_size].height, configuracion->jpeg_quality);
    return ESP_OK;
}

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
    if (mutex_camara == NULL) {
        mutex_camara = xSemaphoreCreateMutex();
        if (mutex_camara == NULL) {
            return ESP_ERR_NO_MEM;
        }
    }

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

    return iniciar_controlador(&configuracion);
}

esp_err_t camera_adquirir(camera_fb_t **imagen, uint32_t *identificador)
{
    if (imagen == NULL || identificador == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    *imagen = NULL;
    if (!tomar_mutex()) {
        return ESP_ERR_TIMEOUT;
    }
    if (!camara_inicializada) {
        xSemaphoreGive(mutex_camara);
        return ESP_ERR_INVALID_STATE;
    }
    // Con WHEN_EMPTY el buffer puede contener una imagen encolada durante la pausa.
    // Se descarta una para que la siguiente corresponda a una escena más reciente.
    camera_fb_t *anterior = esp_camera_fb_get();
    if (anterior != NULL) {
        esp_camera_fb_return(anterior);
    }
    camera_fb_t *nueva = esp_camera_fb_get();
    if (nueva == NULL || !imagen_valida(nueva)) {
        ++capturas_fallidas;
        ESP_LOGE(TAG, "Captura sin JPEG completo SOI/EOI o dimensiones válidas.");
        if (nueva != NULL) {
            esp_camera_fb_return(nueva);
        }
        xSemaphoreGive(mutex_camara);
        return ESP_ERR_INVALID_RESPONSE;
    }
    *imagen = nueva;
    *identificador = ++imagenes_capturadas;
    ESP_LOGI(TAG, "Imagen #%" PRIu32 ": %zux%zu, formato=JPEG, tamaño=%zu bytes",
             *identificador, nueva->width, nueva->height, nueva->len);
    return ESP_OK;
}

void camera_liberar(camera_fb_t *imagen)
{
    esp_camera_fb_return(imagen);
    xSemaphoreGive(mutex_camara);
}

esp_err_t camera_capturar_registrar(void)
{
    camera_fb_t *imagen = NULL;
    uint32_t identificador;
    const esp_err_t resultado = camera_adquirir(&imagen, &identificador);
    if (resultado == ESP_OK) {
        camera_liberar(imagen);
    }
    return resultado;
}

esp_err_t camera_obtener_estado(camera_estado_t *estado)
{
    if (estado == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    if (!tomar_mutex()) {
        return ESP_ERR_TIMEOUT;
    }
    *estado = (camera_estado_t) {
        .inicializada = camara_inicializada,
        .modelo = modelo_sensor,
        .pid = pid_sensor,
        .ancho = resolution[configuracion_actual.frame_size].width,
        .alto = resolution[configuracion_actual.frame_size].height,
        .calidad = configuracion_actual.jpeg_quality,
        .capturas_correctas = imagenes_capturadas,
        .capturas_fallidas = capturas_fallidas,
    };
    xSemaphoreGive(mutex_camara);
    return ESP_OK;
}

esp_err_t camera_reconfigurar(framesize_t resolucion, int calidad)
{
    if ((resolucion != FRAMESIZE_QVGA && resolucion != FRAMESIZE_VGA &&
         resolucion != FRAMESIZE_SVGA) || calidad < 10 || calidad > 40) {
        return ESP_ERR_INVALID_ARG;
    }
    if (!tomar_mutex()) {
        return ESP_ERR_TIMEOUT;
    }
    // Recuperar también una cámara que quedó detenida si falló la restauración.
    const camera_config_t anterior = configuracion_actual;
    camera_config_t nueva = anterior;
    nueva.frame_size = resolucion;
    nueva.jpeg_quality = calidad;
    esp_err_t resultado = ESP_OK;
    if (camara_inicializada) {
        resultado = esp_camera_deinit();
    }
    if (resultado == ESP_OK) {
        camara_inicializada = false;
        resultado = iniciar_controlador(&nueva);
        if (resultado != ESP_OK) {
            ESP_LOGE(TAG, "Reconfiguración fallida; restaurando configuración anterior.");
            const esp_err_t restauracion = iniciar_controlador(&anterior);
            if (restauracion != ESP_OK) {
                ESP_LOGE(TAG, "Restauración fallida: %s; cámara detenida.", esp_err_to_name(restauracion));
            }
        }
    }
    xSemaphoreGive(mutex_camara);
    camera_registrar_memoria();
    return resultado;
}
