#include "wifi_manager.h"
#include "receptor_udp.h"
#include "sdkconfig.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include <string.h>
static EventGroupHandle_t eventos;
static bool iniciado,intentado;
static void eventos_red(void *arg,esp_event_base_t base,int32_t id,void *datos)
{
    (void)arg;
    if(base==IP_EVENT && id==IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *ip=datos;
        receptor_udp_conexion(true);xEventGroupSetBits(eventos,1);ESP_LOGI("wifi_c6","IPv4 "IPSTR,IP2STR(&ip->ip_info.ip));
    } else if((base==WIFI_EVENT && id==WIFI_EVENT_STA_DISCONNECTED) || (base==IP_EVENT && id==IP_EVENT_STA_LOST_IP)) {
        xEventGroupClearBits(eventos,1);receptor_udp_conexion(false);
        ESP_LOGW("wifi_c6","Sin conectividad; demanda invalidada");

    }
}
static void reconectar(void *arg)
{
    (void)arg;
    for(;;) {
        if(!wifi_manager_conectado())esp_wifi_connect();
        vTaskDelay(pdMS_TO_TICKS(3000));
    }
}
bool wifi_manager_conectado(void) { return eventos && (xEventGroupGetBits(eventos)&1); }
bool wifi_manager_iniciar(void)
{
    if(iniciado)return true;
    if(intentado)return false;
    intentado=true;
    if(!strlen(CONFIG_SEMAFORO_WIFI_SSID) || strlen(CONFIG_SEMAFORO_WIFI_SSID)>32 || strlen(CONFIG_SEMAFORO_WIFI_PASSWORD)>63)return false;
    /* No borrar NVS para ocultar errores ni cambiar la instalación del usuario. */
    if(nvs_flash_init()!=ESP_OK || esp_netif_init()!=ESP_OK)return false;
    esp_err_t error=esp_event_loop_create_default();if(error!=ESP_OK && error!=ESP_ERR_INVALID_STATE)return false;
    eventos=xEventGroupCreate();if(!eventos || !esp_netif_create_default_wifi_sta())return false;
    wifi_init_config_t inicial=WIFI_INIT_CONFIG_DEFAULT();
    if(esp_wifi_init(&inicial)!=ESP_OK)return false;
    if(esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,eventos_red,NULL)!=ESP_OK ||
       esp_event_handler_register(IP_EVENT,ESP_EVENT_ANY_ID,eventos_red,NULL)!=ESP_OK)return false;
    wifi_config_t config={0};
    memcpy(config.sta.ssid,CONFIG_SEMAFORO_WIFI_SSID,strlen(CONFIG_SEMAFORO_WIFI_SSID));
    memcpy(config.sta.password,CONFIG_SEMAFORO_WIFI_PASSWORD,strlen(CONFIG_SEMAFORO_WIFI_PASSWORD));
    if(esp_wifi_set_storage(WIFI_STORAGE_RAM)!=ESP_OK || esp_wifi_set_mode(WIFI_MODE_STA)!=ESP_OK ||
       esp_wifi_set_config(WIFI_IF_STA,&config)!=ESP_OK || esp_wifi_start()!=ESP_OK)return false;
    if(xTaskCreate(reconectar,"wifi_reconexion",3072,NULL,3,NULL)!=pdPASS)return false;
    iniciado=true;return true;
}
