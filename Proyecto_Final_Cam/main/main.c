#include <stdbool.h>
#include "camera_driver.h"
#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define PERIODO_CAPTURA_MS 5000

static const char *TAG = "practica_1_1";

void app_main(void)
{
    ESP_LOGI(TAG, "Práctica 1.1; ESP-IDF %s; target esp32", esp_get_idf_version());
    camera_registrar_memoria();

    const esp_err_t resultado = camera_inicializar();
    if (resultado != ESP_OK) {
        ESP_LOGE(TAG, "Inicialización detenida: %s (0x%x). No se realizarán capturas.",
                 esp_err_to_name(resultado), (unsigned int)resultado);
        return;
    }

    // app_main ya se ejecuta en una tarea FreeRTOS; no hace falta otra tarea.
    while (true) {
        if (camera_capturar_registrar() != ESP_OK) {
            ESP_LOGW(TAG, "Se reintentará la captura después de %d ms.", PERIODO_CAPTURA_MS);
        }
        camera_registrar_memoria();
        // Cede la CPU también cuando falla una captura; evita un bucle ocupado.
        vTaskDelay(pdMS_TO_TICKS(PERIODO_CAPTURA_MS));
    }
}
