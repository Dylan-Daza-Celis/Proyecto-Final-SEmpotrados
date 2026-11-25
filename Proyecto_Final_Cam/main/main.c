#include <stdbool.h>
#include "camera_driver.h"
#include "wifi_manager.h"
#include "http_server.h"
#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "practica_1_2_1_3";

void app_main(void)
{
    ESP_LOGI(TAG, "Prácticas 1.2/1.3; ESP-IDF %s; target esp32", esp_get_idf_version());
    camera_registrar_memoria();

    const esp_err_t resultado = camera_inicializar();
    if (resultado != ESP_OK) {
        ESP_LOGE(TAG, "Inicialización detenida: %s (0x%x). No se realizarán capturas.",
                 esp_err_to_name(resultado), (unsigned int)resultado);
        return;
    }

    const esp_err_t resultado_wifi = wifi_inicializar();
    if (resultado_wifi != ESP_OK) {
        ESP_LOGE(TAG, "No se pudo iniciar Wi-Fi: %s. Revise menuconfig y reinicie.", esp_err_to_name(resultado_wifi));
        return;
    }
    // El HTTP es el único consumidor de imágenes; se conserva la función de
    // diagnóstico 1.1, pero ya no hay un bucle competidor de capturas periódicas.
    while (true) {
        const esp_err_t estado_http = wifi_esperar_ip(1000)
            ? servidor_http_iniciar() : servidor_http_detener();
        if (estado_http != ESP_OK) {
            ESP_LOGE(TAG, "Cambio de estado HTTP falló: %s", esp_err_to_name(estado_http));
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
