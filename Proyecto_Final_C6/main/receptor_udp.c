#include "receptor_udp.h"
#include "wifi_manager.h"
#include "sdkconfig.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "lwip/sockets.h"
#include <string.h>
#include <inttypes.h>
#include <errno.h>
static portMUX_TYPE mutex=portMUX_INITIALIZER_UNLOCKED;
static gestor_recepcion_t gestor={.estado={.generacion=1},.fase=7,.timeout_ms=5000};
static QueueHandle_t cola;
static bool iniciado,restringir_ip;
static struct in_addr ip_permitida;
static uint64_t ahora_ms(void) { return (uint64_t)esp_timer_get_time()/1000; }
void receptor_udp_invalidar(void)
{ portENTER_CRITICAL(&mutex);recepcion_invalidar(&gestor);portEXIT_CRITICAL(&mutex); }
void receptor_udp_conexion(bool conectado)
{ portENTER_CRITICAL(&mutex);recepcion_conexion(&gestor,conectado);portEXIT_CRITICAL(&mutex); }
estado_recepcion_t receptor_udp_estado(void)
{
    estado_recepcion_t copia;uint64_t ahora=ahora_ms();
    portENTER_CRITICAL(&mutex);recepcion_caducar(&gestor,ahora);copia=gestor.estado;portEXIT_CRITICAL(&mutex);
    demanda_vehicular_t ultima;
    if(cola && xQueuePeek(cola,&ultima,0)==pdPASS && ultima.secuencia==copia.resultado &&
        ultima.recibida_ms==copia.recibida_ms && ultima.n1==copia.demanda.n1 && ultima.n2==copia.demanda.n2)
        copia.demanda=ultima;
    return copia;
}
void receptor_udp_estado_controlador(uint8_t estado,uint64_t generacion)
{ portENTER_CRITICAL(&mutex);recepcion_atender(&gestor,estado,generacion);portEXIT_CRITICAL(&mutex); }
static void tarea_recepcion(void *arg)
{
    (void)arg;int conexion=-1;
    for(;;) {
        if(!wifi_manager_conectado()) {
            if(conexion>=0) { close(conexion);conexion=-1;receptor_udp_invalidar(); }
            vTaskDelay(pdMS_TO_TICKS(100));continue;
        }
        if(conexion<0) {
            conexion=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
            struct sockaddr_in local={.sin_family=AF_INET,.sin_port=htons(CONFIG_SEMAFORO_UDP_PUERTO),
                .sin_addr={.s_addr=htonl(INADDR_ANY)}};
            if(conexion<0 || bind(conexion,(struct sockaddr*)&local,sizeof local)<0) {
                if(conexion>=0)close(conexion);
                conexion=-1;receptor_udp_invalidar();
                ESP_LOGE("udp_c6","No se pudo abrir puerto UDP");vTaskDelay(pdMS_TO_TICKS(1000));continue;
            }
            struct timeval espera={.tv_sec=0,.tv_usec=100000};
            if(setsockopt(conexion,SOL_SOCKET,SO_RCVTIMEO,&espera,sizeof espera)<0) {
                close(conexion);conexion=-1;receptor_udp_invalidar();
                vTaskDelay(pdMS_TO_TICKS(1000));continue;
            }
            ESP_LOGI("udp_c6","Receptor UDP puerto %d; sin solicitudes ni confirmaciones",CONFIG_SEMAFORO_UDP_PUERTO);
        }
        char datos[CONTEOS_UDP_MAX_BYTES+1];struct sockaddr_in remoto;socklen_t longitud=sizeof remoto;
        int n=recvfrom(conexion,datos,sizeof datos,0,(struct sockaddr*)&remoto,&longitud);
        if(n<0) {
            if(errno!=EAGAIN && errno!=EWOULDBLOCK && errno!=EINTR) {
                close(conexion);conexion=-1;receptor_udp_invalidar();vTaskDelay(pdMS_TO_TICKS(100));
            }
            continue;
        }
        if(restringir_ip && remoto.sin_addr.s_addr!=ip_permitida.s_addr)continue;
        mensaje_conteos_t m;
        if(!conteos_decodificar(datos,(size_t)n,&m)) { ESP_LOGD("udp_c6","Datagrama malformado rechazado");continue; }
        uint64_t ahora=ahora_ms();demanda_vehicular_t demanda;
        portENTER_CRITICAL(&mutex);
        bool aceptado=recepcion_recibir(&gestor,m,ahora);demanda=gestor.estado.demanda;
        portEXIT_CRITICAL(&mutex);
        if(aceptado && m.valido)xQueueOverwrite(cola,&demanda);
        if(aceptado)ESP_LOGI("udp_c6","seq=%"PRIu64" N1=%u N2=%u valido=%u",m.secuencia,m.n1,m.n2,(unsigned)m.valido);
    }
}
bool receptor_udp_iniciar(void *cola_ultimo_valor)
{
    if(iniciado)return true;
    if(!cola_ultimo_valor || CONFIG_SEMAFORO_UDP_TIMEOUT_LOCAL_MS>CONFIG_SEMAFORO_MAX_EDAD_DEMANDA_MS)return false;
    restringir_ip=strlen(CONFIG_SEMAFORO_UDP_IP_EMISOR)>0;
    if(restringir_ip && inet_pton(AF_INET,CONFIG_SEMAFORO_UDP_IP_EMISOR,&ip_permitida)!=1)return false;
    if(!recepcion_iniciar(&gestor,CONFIG_SEMAFORO_UDP_TIMEOUT_LOCAL_MS))return false;
    cola=(QueueHandle_t)cola_ultimo_valor;
    if(xTaskCreate(tarea_recepcion,"receptor_udp",4096,NULL,4,NULL)!=pdPASS)return false;
    iniciado=true;return true;
}
