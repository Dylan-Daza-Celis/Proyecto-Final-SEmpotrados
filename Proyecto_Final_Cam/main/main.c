/* 1. Includes: tres responsabilidades independientes del firmware. */
#include <stdbool.h>
#include "camera_driver.h"
#include "wifi_manager.h"
#include "http_server.h"
#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

/* 2. Identificacion de logs. Los estados privados viven en cada modulo. */
static const char *TAG = "practica_1_2_1_3";

/* 3. app_main: inicializar camara, iniciar STA y administrar HTTP. */
void app_main(void)
{
    ESP_LOGI(TAG, "Prácticas 1.2/1.3; ESP-IDF %s; target esp32", esp_get_idf_version());
    camera_registrar_memoria();

    // Verifica PSRAM, crea mutex, configura pines/sensor y estabiliza framebuffers.
    const esp_err_t resultado = camera_inicializar();
    if (resultado != ESP_OK) {
        ESP_LOGE(TAG, "Inicialización detenida: %s (0x%x). No se realizarán capturas.",
                 esp_err_to_name(resultado), (unsigned int)resultado);
        return;
    }

    // NVS, interfaz STA, eventos y reconexion quedan a cargo del modulo Wi-Fi.
    const esp_err_t resultado_wifi = wifi_inicializar();
    if (resultado_wifi != ESP_OK) {
        ESP_LOGE(TAG, "No se pudo iniciar Wi-Fi: %s. Revise menuconfig y reinicie.",
                 esp_err_to_name(resultado_wifi));
        return;
    }
    // El HTTP es el único consumidor de imágenes; se conserva la función de
    // diagnóstico 1.1, pero ya no hay un bucle competidor de capturas periódicas.
    // Un ciclo solo inicia o detiene HTTP; capturar corresponde a GET /capture.
    // Esperar IP y vTaskDelay ceden CPU a FreeRTOS; no hay espera activa.
    while (true) {
        const esp_err_t estado_http =
            wifi_esperar_ip(1000) ? servidor_http_iniciar() : servidor_http_detener();
        if (estado_http != ESP_OK) {
            ESP_LOGE(TAG, "Cambio de estado HTTP falló: %s", esp_err_to_name(estado_http));
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
