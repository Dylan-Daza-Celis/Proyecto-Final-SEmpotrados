#include "comunicacion.h"
#include "sdkconfig.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/event_groups.h"
#include "lwip/sockets.h"
#include <string.h>
#include <inttypes.h>
#include <errno.h>

/* Constantes locales: pilas en bytes, prioridades FreeRTOS, esperas en ms/us. */
enum {
    PILA_WIFI_BYTES = 3072,
    PILA_RECEPTOR_BYTES = 4096,
    PRIORIDAD_WIFI = 3,
    PRIORIDAD_RECEPTOR = 4,
    REINTENTO_WIFI_MS = 3000,
    REINTENTO_SOCKET_MS = 1000,
    PAUSA_RECEPTOR_MS = 100,
    ESPERA_SOCKET_US = 100000
};
#define BIT_WIFI_CONECTADO BIT0

/* Auxiliares privados: solo se usan en esta unidad de comunicacion. */
static bool wifi_manager_conectado(void);
static void receptor_udp_conexion(bool conectado);

/* 1. Wi-Fi STA, eventos y reconexion. */
static EventGroupHandle_t eventos_wifi;
static bool wifi_iniciado, wifi_intentado;
static void eventos_red(void *parametro, esp_event_base_t base, int32_t identificador_evento,
                        void *datos)
{
    (void)parametro;
    if (base == IP_EVENT && identificador_evento == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *evento_ip = datos;
        receptor_udp_conexion(true);
        xEventGroupSetBits(eventos_wifi, BIT_WIFI_CONECTADO);
        ESP_LOGI("wifi_c6", "IPv4 " IPSTR, IP2STR(&evento_ip->ip_info.evento_ip));
    } else if ((base == WIFI_EVENT && identificador_evento == WIFI_EVENT_STA_DISCONNECTED) ||
               (base == IP_EVENT && identificador_evento == IP_EVENT_STA_LOST_IP)) {
        xEventGroupClearBits(eventos_wifi, BIT_WIFI_CONECTADO);
        receptor_udp_conexion(false);
        ESP_LOGW("wifi_c6", "Sin conectividad; demanda invalidada");
    }
}
static void reconectar(void *parametro)
{
    (void)parametro;
    for (;;) {
        if (!wifi_manager_conectado()) {
            esp_wifi_connect();
        }
        vTaskDelay(pdMS_TO_TICKS(REINTENTO_WIFI_MS));
    }
}
static bool wifi_manager_conectado(void)
{
    return eventos_wifi && (xEventGroupGetBits(eventos_wifi) & BIT_WIFI_CONECTADO);
}
bool wifi_manager_iniciar(void)
{
    if (wifi_iniciado) {
        return true;
    }
    if (wifi_intentado) {
        return false;
    }
    wifi_intentado = true;
    if (!strlen(CONFIG_SEMAFORO_WIFI_SSID) || strlen(CONFIG_SEMAFORO_WIFI_SSID) > 32 ||
        strlen(CONFIG_SEMAFORO_WIFI_PASSWORD) > 63) {
        return false;
    }
    /* No borrar NVS para ocultar errores ni cambiar la instalación del usuario. */
    if (nvs_flash_init() != ESP_OK || esp_netif_init() != ESP_OK) {
        return false;
    }
    esp_err_t error = esp_event_loop_create_default();
    if (error != ESP_OK && error != ESP_ERR_INVALID_STATE) {
        return false;
    }
    eventos_wifi = xEventGroupCreate();
    if (!eventos_wifi || !esp_netif_create_default_wifi_sta()) {
        return false;
    }
    wifi_init_config_t inicial = WIFI_INIT_CONFIG_DEFAULT();
    if (esp_wifi_init(&inicial) != ESP_OK) {
        return false;
    }
    if (esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, eventos_red, NULL) != ESP_OK ||
        esp_event_handler_register(IP_EVENT, ESP_EVENT_ANY_ID, eventos_red, NULL) != ESP_OK) {
        return false;
    }
    wifi_config_t configuracion_wifi = {0};
    memcpy(configuracion_wifi.sta.ssid, CONFIG_SEMAFORO_WIFI_SSID,
           strlen(CONFIG_SEMAFORO_WIFI_SSID));
    memcpy(configuracion_wifi.sta.password, CONFIG_SEMAFORO_WIFI_PASSWORD,
           strlen(CONFIG_SEMAFORO_WIFI_PASSWORD));
    if (esp_wifi_set_storage(WIFI_STORAGE_RAM) != ESP_OK ||
        esp_wifi_set_mode(WIFI_MODE_STA) != ESP_OK ||
        esp_wifi_set_config(WIFI_IF_STA, &configuracion_wifi) != ESP_OK ||
        esp_wifi_start() != ESP_OK) {
        return false;
    }
    if (xTaskCreate(reconectar, "wifi_reconexion", PILA_WIFI_BYTES, NULL, PRIORIDAD_WIFI, NULL) !=
        pdPASS) {
        return false;
    }
    wifi_iniciado = true;
    return true;
}

/* 2. Estado sincronizado, cola y tarea receptora UDP. */
static portMUX_TYPE mutex_recepcion = portMUX_INITIALIZER_UNLOCKED;
static gestor_recepcion_t gestor_recepcion = {.estado = {.generacion = 1},
                                              .fase = RECEPCION_FASE_SEGURA,
                                              .timeout_ms = DEMANDA_VIGENCIA_INICIAL_MS};
static QueueHandle_t cola_demanda;
static bool udp_iniciado, restringir_ip;
static struct in_addr ip_permitida;
static uint64_t ahora_ms(void)
{
    return (uint64_t)esp_timer_get_time() / 1000;
}
void receptor_udp_invalidar(void)
{
    portENTER_CRITICAL(&mutex_recepcion);
    recepcion_invalidar(&gestor_recepcion);
    portEXIT_CRITICAL(&mutex_recepcion);
}
static void receptor_udp_conexion(bool conectado)
{
    portENTER_CRITICAL(&mutex_recepcion);
    recepcion_conexion(&gestor_recepcion, conectado);
    portEXIT_CRITICAL(&mutex_recepcion);
}
estado_recepcion_t receptor_udp_estado(void)
{
    estado_recepcion_t copia;
    uint64_t ahora = ahora_ms();
    portENTER_CRITICAL(&mutex_recepcion);
    recepcion_caducar(&gestor_recepcion, ahora);
    copia = gestor_recepcion.estado;
    portEXIT_CRITICAL(&mutex_recepcion);
    demanda_vehicular_t ultima;
    if (cola_demanda && xQueuePeek(cola_demanda, &ultima, 0) == pdPASS &&
        ultima.secuencia == copia.resultado && ultima.recibida_ms == copia.recibida_ms &&
        ultima.n1 == copia.demanda.n1 && ultima.n2 == copia.demanda.n2) {
        copia.demanda = ultima;
    }
    return copia;
}
void receptor_udp_estado_controlador(uint8_t estado, uint64_t generacion)
{
    portENTER_CRITICAL(&mutex_recepcion);
    recepcion_atender(&gestor_recepcion, estado, generacion);
    portEXIT_CRITICAL(&mutex_recepcion);
}
static void tarea_recepcion(void *parametro)
{
    (void)parametro;
    int conexion = -1;
    for (;;) {
        if (!wifi_manager_conectado()) {
            if (conexion >= 0) {
                close(conexion);
                conexion = -1;
                receptor_udp_invalidar();
            }
            vTaskDelay(pdMS_TO_TICKS(PAUSA_RECEPTOR_MS));
            continue;
        }
        if (conexion < 0) {
            conexion = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
            struct sockaddr_in local = {.sin_family = AF_INET,
                                        .sin_port = htons(CONFIG_SEMAFORO_UDP_PUERTO),
                                        .sin_addr = {.s_addr = htonl(INADDR_ANY)}};
            if (conexion < 0 || bind(conexion, (struct sockaddr *)&local, sizeof local) < 0) {
                if (conexion >= 0) {
                    close(conexion);
                }
                conexion = -1;
                receptor_udp_invalidar();
                ESP_LOGE("udp_c6", "No se pudo abrir puerto UDP");
                vTaskDelay(pdMS_TO_TICKS(REINTENTO_SOCKET_MS));
                continue;
            }
            struct timeval espera = {.tv_sec = 0, .tv_usec = ESPERA_SOCKET_US};
            if (setsockopt(conexion, SOL_SOCKET, SO_RCVTIMEO, &espera, sizeof espera) < 0) {
                close(conexion);
                conexion = -1;
                receptor_udp_invalidar();
                vTaskDelay(pdMS_TO_TICKS(REINTENTO_SOCKET_MS));
                continue;
            }
            ESP_LOGI("udp_c6", "Receptor UDP puerto %d; sin solicitudes ni confirmaciones",
                     CONFIG_SEMAFORO_UDP_PUERTO);
        }
        char datos[CONTEOS_UDP_MAX_BYTES + 1];
        struct sockaddr_in remoto;
        socklen_t longitud = sizeof remoto;
        int longitud_recibida =
            recvfrom(conexion, datos, sizeof datos, 0, (struct sockaddr *)&remoto, &longitud);
        if (longitud_recibida < 0) {
            if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) {
                close(conexion);
                conexion = -1;
                receptor_udp_invalidar();
                vTaskDelay(pdMS_TO_TICKS(PAUSA_RECEPTOR_MS));
            }
            continue;
        }
        if (restringir_ip && remoto.sin_addr.s_addr != ip_permitida.s_addr) {
            continue;
        }
        mensaje_conteos_t mensaje;
        if (!conteos_decodificar(datos, (size_t)longitud_recibida, &mensaje)) {
            ESP_LOGD("udp_c6", "Datagrama malformado rechazado");
            continue;
        }
        uint64_t ahora = ahora_ms();
        demanda_vehicular_t demanda;
        portENTER_CRITICAL(&mutex_recepcion);
        bool aceptado = recepcion_recibir(&gestor_recepcion, mensaje, ahora);
        demanda = gestor_recepcion.estado.demanda;
        portEXIT_CRITICAL(&mutex_recepcion);
        if (aceptado && mensaje.valido) {
            xQueueOverwrite(cola_demanda, &demanda);
        }
        if (aceptado) {
            ESP_LOGI("udp_c6", "seq=%" PRIu64 " N1=%u N2=%u valido=%u", mensaje.secuencia,
                     mensaje.n1, mensaje.n2, (unsigned)mensaje.valido);
        }
    }
}
bool receptor_udp_iniciar(void *cola_ultimo_valor)
{
    if (udp_iniciado) {
        return true;
    }
    if (!cola_ultimo_valor ||
        CONFIG_SEMAFORO_UDP_TIMEOUT_LOCAL_MS > CONFIG_SEMAFORO_MAX_EDAD_DEMANDA_MS) {
        return false;
    }
    restringir_ip = strlen(CONFIG_SEMAFORO_UDP_IP_EMISOR) > 0;
    if (restringir_ip && inet_pton(AF_INET, CONFIG_SEMAFORO_UDP_IP_EMISOR, &ip_permitida) != 1) {
        return false;
    }
    if (!recepcion_iniciar(&gestor_recepcion, CONFIG_SEMAFORO_UDP_TIMEOUT_LOCAL_MS)) {
        return false;
    }
    cola_demanda = (QueueHandle_t)cola_ultimo_valor;
    if (xTaskCreate(tarea_recepcion, "receptor_udp", PILA_RECEPTOR_BYTES, NULL, PRIORIDAD_RECEPTOR,
                    NULL) != pdPASS) {
        return false;
    }
    udp_iniciado = true;
    return true;
}
