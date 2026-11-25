#include "wifi_manager.h"

#include <string.h>
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

#define BIT_CON_IP BIT0
#define BIT_RECONECTAR BIT1

static const char *TAG = "wifi_manager";
static EventGroupHandle_t eventos_wifi;

static void manejar_evento(void *argumento, esp_event_base_t base, int32_t id, void *datos)
{
    (void)argumento;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        xEventGroupSetBits(eventos_wifi, BIT_RECONECTAR);
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *evento = datos;
        xEventGroupClearBits(eventos_wifi, BIT_CON_IP);
        xEventGroupSetBits(eventos_wifi, BIT_RECONECTAR);
        ESP_LOGW(TAG, "Wi-Fi desconectado (motivo=%u); se programará reconexión.", evento->reason);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *evento = datos;
        if (evento->ip_info.ip.addr != 0) {
            xEventGroupClearBits(eventos_wifi, BIT_RECONECTAR);
            xEventGroupSetBits(eventos_wifi, BIT_CON_IP);
            ESP_LOGI(TAG, "IPv4: " IPSTR " — abrir http://" IPSTR "/",
                     IP2STR(&evento->ip_info.ip), IP2STR(&evento->ip_info.ip));
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_LOST_IP) {
        xEventGroupClearBits(eventos_wifi, BIT_CON_IP);
        ESP_LOGW(TAG, "Dirección IP perdida; reiniciando asociación Wi-Fi.");
        const esp_err_t resultado = esp_wifi_disconnect();
        if (resultado != ESP_OK) {
            ESP_LOGW(TAG, "Desconexión tras perder IP: %s", esp_err_to_name(resultado));
        }
        xEventGroupSetBits(eventos_wifi, BIT_RECONECTAR);
    }
}

static void tarea_reconexion(void *argumento)
{
    (void)argumento;
    uint32_t demora_ms = 1000;
    while (true) {
        const EventBits_t eventos = xEventGroupWaitBits(eventos_wifi, BIT_RECONECTAR,
                                                       pdTRUE, pdFALSE, pdMS_TO_TICKS(1000));
        if ((eventos & BIT_CON_IP) != 0) {
            demora_ms = 1000;
            continue;
        }
        if ((eventos & BIT_RECONECTAR) == 0) {
            continue;
        }
        // La espera permite cancelar el intento si llega una IP durante la pausa.
        if (wifi_esperar_ip(demora_ms)) {
            demora_ms = 1000;
            continue;
        }
        const esp_err_t resultado = esp_wifi_connect();
        if (resultado != ESP_OK) {
            ESP_LOGE(TAG, "No se pudo iniciar conexión: %s", esp_err_to_name(resultado));
            xEventGroupSetBits(eventos_wifi, BIT_RECONECTAR);
        }
        demora_ms = demora_ms < 15000 ? demora_ms * 2 : 30000;
    }
}

bool wifi_esperar_ip(uint32_t espera_ms)
{
    return eventos_wifi != NULL &&
           (xEventGroupWaitBits(eventos_wifi, BIT_CON_IP, pdFALSE, pdFALSE,
                               pdMS_TO_TICKS(espera_ms)) & BIT_CON_IP) != 0;
}

esp_err_t wifi_inicializar(void)
{
    if (eventos_wifi != NULL) {
        return ESP_ERR_INVALID_STATE;
    }
    const size_t largo_ssid = strlen(CONFIG_PROYECTO_WIFI_SSID);
    const size_t largo_clave = strlen(CONFIG_PROYECTO_WIFI_PASSWORD);
    if (largo_ssid == 0 || largo_ssid > 32 || largo_clave > 63 ||
        (largo_clave != 0 && largo_clave < 8)) {
        ESP_LOGE(TAG, "Configure SSID (1..32 bytes) y contraseña (8..63 o vacía para red abierta) en menuconfig.");
        return ESP_ERR_INVALID_ARG;
    }

    esp_err_t resultado = nvs_flash_init();
    if (resultado == ESP_ERR_NVS_NO_FREE_PAGES || resultado == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "Partición NVS incompatible o llena: se borrará para reinicializarla.");
        resultado = nvs_flash_erase();
        if (resultado == ESP_OK) {
            resultado = nvs_flash_init();
        }
    }
    if (resultado != ESP_OK) {
        return resultado;
    }
    resultado = esp_netif_init();
    if (resultado != ESP_OK) {
        return resultado;
    }
    resultado = esp_event_loop_create_default();
    if (resultado != ESP_OK) {
        return resultado;
    }
    esp_netif_t *interfaz = esp_netif_create_default_wifi_sta();
    if (interfaz == NULL) {
        esp_event_loop_delete_default();
        return ESP_ERR_NO_MEM;
    }
    eventos_wifi = xEventGroupCreate();
    bool controlador_creado = false;
    bool registro_wifi = false;
    bool registro_ip = false;
    esp_event_handler_instance_t manejador_wifi = NULL;
    esp_event_handler_instance_t manejador_ip = NULL;
    if (eventos_wifi == NULL) {
        resultado = ESP_ERR_NO_MEM;
        goto fallo;
    }
    wifi_init_config_t inicial = WIFI_INIT_CONFIG_DEFAULT();
    resultado = esp_wifi_init(&inicial);
    if (resultado != ESP_OK) { goto fallo; }
    controlador_creado = true;
    resultado = esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                   manejar_evento, NULL, &manejador_wifi);
    if (resultado != ESP_OK) { goto fallo; }
    registro_wifi = true;
    resultado = esp_event_handler_instance_register(IP_EVENT, ESP_EVENT_ANY_ID,
                                                   manejar_evento, NULL, &manejador_ip);
    if (resultado != ESP_OK) { goto fallo; }
    registro_ip = true;
    // Las credenciales se mantienen en RAM; no se persisten mediante esp_wifi.
    resultado = esp_wifi_set_storage(WIFI_STORAGE_RAM);
    if (resultado != ESP_OK) { goto fallo; }
    wifi_config_t configuracion = {0};
    memcpy(configuracion.sta.ssid, CONFIG_PROYECTO_WIFI_SSID, largo_ssid);
    memcpy(configuracion.sta.password, CONFIG_PROYECTO_WIFI_PASSWORD, largo_clave);
    configuracion.sta.threshold.authmode = largo_clave == 0 ? WIFI_AUTH_OPEN : WIFI_AUTH_WPA2_PSK;
    configuracion.sta.pmf_cfg.capable = true;
    resultado = esp_wifi_set_mode(WIFI_MODE_STA);
    if (resultado != ESP_OK) { goto fallo; }
    resultado = esp_wifi_set_config(WIFI_IF_STA, &configuracion);
    if (resultado != ESP_OK) { goto fallo; }
    resultado = esp_wifi_start();
    if (resultado != ESP_OK) { goto fallo; }
    if (xTaskCreate(tarea_reconexion, "wifi_reconexion", 4096, NULL, 4, NULL) != pdPASS) {
        resultado = ESP_ERR_NO_MEM;
        goto fallo;
    }
    ESP_LOGI(TAG, "Estación Wi-Fi iniciada (2.4 GHz); credenciales omitidas del registro.");
    return ESP_OK;

fallo:
    if (registro_ip) {
        esp_event_handler_instance_unregister(IP_EVENT, ESP_EVENT_ANY_ID, manejador_ip);
    }
    if (registro_wifi) {
        esp_event_handler_instance_unregister(WIFI_EVENT, ESP_EVENT_ANY_ID, manejador_wifi);
    }
    if (controlador_creado) {
        esp_wifi_stop();
        esp_wifi_deinit();
    }
    esp_netif_destroy_default_wifi(interfaz);
    esp_event_loop_delete_default();
    if (eventos_wifi != NULL) {
        vEventGroupDelete(eventos_wifi);
        eventos_wifi = NULL;
    }
    ESP_LOGE(TAG, "Inicialización Wi-Fi fallida: %s", esp_err_to_name(resultado));
    return resultado;
}
