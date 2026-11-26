#include "cliente_udp.h"
#include <inttypes.h>
#include "wifi_manager.h"
#include "sesion_udp.h"
#include "sdkconfig.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "lwip/sockets.h"
#include <string.h>
#include <limits.h>
static portMUX_TYPE mutex=portMUX_INITIALIZER_UNLOCKED;
static estado_red_t red={.generacion=1,.estado=7};
static bool fallo_pendiente,iniciado;
static QueueHandle_t cola_demanda;
static uint8_t clave[32],emisor[16];
static uint64_t ahora_ms(void) { return (uint64_t)esp_timer_get_time()/1000; }
void cliente_udp_invalidar_local(void)
{
    portENTER_CRITICAL(&mutex);
    red.valido=false;red.vence=0;fallo_pendiente=true;
    portEXIT_CRITICAL(&mutex);
}
estado_red_t cliente_udp_estado(void)
{
    estado_red_t copia;portENTER_CRITICAL(&mutex);copia=red;portEXIT_CRITICAL(&mutex);
    demanda_vehicular_t ultima;
    if(cola_demanda && xQueuePeek(cola_demanda,&ultima,0)==pdPASS && ultima.secuencia==copia.resultado &&
        ultima.recibida_ms==copia.recibida_ms && ultima.n1==copia.demanda.n1 && ultima.n2==copia.demanda.n2 && ultima.valida)
        copia.demanda=ultima;
    /* La copia coherente protege el intervalo entre publicacion y overwrite de cola. */
    return copia;
}
void cliente_udp_estado_controlador(uint8_t estado,uint64_t generacion)
{
    portENTER_CRITICAL(&mutex);red.estado=estado;
    if(estado==7 && generacion==red.generacion)red.reconocida=generacion;
    portEXIT_CRITICAL(&mutex);
}
static bool hexadecimal(const char *texto,uint8_t *salida,size_t n)
{
    if(strlen(texto)!=2*n)return false;
    for(size_t i=0;i<n;++i) {
        unsigned v=0;
        for(int j=0;j<2;++j) {
            char c=texto[2*i+j];unsigned d=c>='0'&&c<='9' ? (unsigned)(c-'0'):
                c>='a'&&c<='f' ? (unsigned)(c-'a'+10):c>='A'&&c<='F' ? (unsigned)(c-'A'+10):16;
            if(d==16)return false;
            v=16*v+d;
        }
        salida[i]=(uint8_t)v;
    }
    return true;
}
static void publicar(const sesion_udp_t *s)
{
    bool nueva=false;demanda_vehicular_t demanda={0};
    portENTER_CRITICAL(&mutex);
    red.generacion=s->generacion;red.asociado=s->etapa==2;red.valido=s->valido && !fallo_pendiente;red.vence=red.valido ? s->vence:0;
    /* El propietario verifica tambien el plazo de transporte sin esperar al socket. */
    if(red.valido && s->ultima_auth<=UINT64_MAX-s->comunicacion_ms &&
        s->ultima_auth+s->comunicacion_ms<red.vence)red.vence=s->ultima_auth+s->comunicacion_ms;
    if(!s->valido)red.resultado=0;
    if(red.resultado!=s->resultado && s->valido) {
        red.recibida_ms=s->ultima_auth;
        red.demanda=(demanda_vehicular_t){s->n1,s->n2,s->resultado,red.recibida_ms,true};
        red.resultado=s->resultado;
        nueva=true;demanda=red.demanda;
    }
    portEXIT_CRITICAL(&mutex);
    if(nueva)xQueueOverwrite(cola_demanda,&demanda);
}
static void tarea_udp(void *arg)
{
    (void)arg;sesion_udp_t sesion;uint8_t receptor[16];esp_fill_random(receptor,16);
    sesion_udp_iniciar(&sesion,emisor,receptor);
    sesion.presupuesto_ms=CONFIG_SEMAFORO_UDP_EDAD_ORIGEN_MS;sesion.local_ms=CONFIG_SEMAFORO_UDP_VIGENCIA_MS;
    sesion.margen_ms=CONFIG_SEMAFORO_UDP_MARGEN_MS;sesion.timeout_ms=CONFIG_SEMAFORO_UDP_TIMEOUT_MS;
    sesion.comunicacion_ms=CONFIG_SEMAFORO_UDP_COMUNICACION_MS;
    int conexion=-1;bool tenia_wifi=false;
    struct sockaddr_in destino={.sin_family=AF_INET,.sin_port=htons(CONFIG_SEMAFORO_UDP_PUERTO)};
    inet_pton(AF_INET,CONFIG_SEMAFORO_UDP_IP,&destino.sin_addr);
    ESP_LOGI("udp_c6","Servidor %s:%d",CONFIG_SEMAFORO_UDP_IP,CONFIG_SEMAFORO_UDP_PUERTO);
    for(;;) {
        bool wifi=wifi_manager_conectado();
        portENTER_CRITICAL(&mutex);bool fallo=fallo_pendiente;fallo_pendiente=false;portEXIT_CRITICAL(&mutex);
        uint64_t ahora=ahora_ms();
        if(fallo || (sesion.valido && !sesion_udp_vigente(&sesion,ahora))) {
            sesion_udp_fallo(&sesion);publicar(&sesion);ESP_LOGW("udp_c6","Demanda invalidada; pedir despeje seguro");
        }
        if(!wifi) {
            if(tenia_wifi) {sesion_udp_fallo(&sesion);publicar(&sesion);}
            tenia_wifi=false;
            if(conexion>=0){close(conexion);conexion=-1;}
            sesion.etapa=0;memset(sesion.servidor,0,16);esp_fill_random(sesion.receptor,16);
            vTaskDelay(pdMS_TO_TICKS(100));continue;
        }
        tenia_wifi=true;
        if(sesion.etapa && ahora>=sesion.ultima_auth && ahora-sesion.ultima_auth>=sesion.comunicacion_ms) {
            sesion_udp_fallo(&sesion);sesion.etapa=0;memset(sesion.servidor,0,16);
            esp_fill_random(sesion.receptor,16);publicar(&sesion);ESP_LOGW("udp_c6","Timeout autenticado; nueva asociacion desde seguro");
        }
        if(conexion<0) {
            conexion=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
            if(conexion<0 || connect(conexion,(struct sockaddr*)&destino,sizeof destino)<0) {
                if(conexion>=0)close(conexion);
                conexion=-1;cliente_udp_invalidar_local();
                vTaskDelay(pdMS_TO_TICKS(1000));continue;
            }
        }
        estado_red_t control=cliente_udp_estado();mensaje_udp_t solicitud;
        uint64_t inicio=ahora_ms();
        if(!sesion_udp_solicitar(&sesion,inicio,control.estado,control.reconocida==sesion.generacion,&solicitud)) {
            cliente_udp_invalidar_local();vTaskDelay(pdMS_TO_TICKS(1000));continue;
        }
        uint8_t datos[513];
        unsigned rechazadas=0;
        if(protocolo_codificar(&solicitud,clave,datos,udp_firmar_psa) && send(conexion,datos,UDP_TAMANO,0)==UDP_TAMANO) {
            ESP_LOGI("udp_c6","Solicitud nonce=%"PRIu64,solicitud.nonce);
            while(ahora_ms()-inicio<sesion.timeout_ms && wifi_manager_conectado()) {
                uint64_t transcurrido_rx=ahora_ms()-inicio;
                if(transcurrido_rx>=sesion.timeout_ms)break;
                uint64_t restante=sesion.timeout_ms-transcurrido_rx;
                struct timeval espera={.tv_sec=0,.tv_usec=(long)(restante*1000)};
                setsockopt(conexion,SOL_SOCKET,SO_RCVTIMEO,&espera,sizeof espera);
                int n=recv(conexion,datos,sizeof datos,0);if(n<0)break;
                mensaje_udp_t respuesta;
                if(protocolo_decodificar(datos,(size_t)n,clave,&respuesta,udp_verificar_psa) &&
                    sesion_udp_responder(&sesion,&respuesta,ahora_ms())) {
                    publicar(&sesion);
                    ESP_LOGI("udp_c6","Respuesta tipo=%u motivo=%u RTT=%"PRIu32" edad_cota=%"PRIu32" resultado=%"PRIu64" evento=%"PRIu64" gen=%"PRIu64,
                        respuesta.tipo,respuesta.motivo,sesion.rtt_ms,sesion.edad_ms,sesion.resultado,sesion.evento,sesion.generacion);
                    uint64_t registro_ms=ahora_ms();
                    if(sesion.valido)ESP_LOGI("udp_c6","N1=%u N2=%u vigencia restante=%"PRIu64" ms",sesion.n1,sesion.n2,
                        registro_ms<sesion.vence ? sesion.vence-registro_ms:0);
                    break;
                } else ++rechazadas;
            }
        }
        if(rechazadas)ESP_LOGW("udp_c6","Respuestas rechazadas=%u; no modificaron demanda",rechazadas);
        uint64_t transcurrido=ahora_ms()-inicio;
        if(transcurrido<CONFIG_SEMAFORO_UDP_INTERVALO_MS)vTaskDelay(pdMS_TO_TICKS(CONFIG_SEMAFORO_UDP_INTERVALO_MS-transcurrido));
        else vTaskDelay(1);
    }
}
bool cliente_udp_iniciar(void *cola_ultimo_valor)
{
    if(iniciado)return true;
    if(!cola_ultimo_valor)return false;
    struct in_addr ip;
    if(!hexadecimal(CONFIG_SEMAFORO_UDP_CLAVE,clave,32) || !hexadecimal(CONFIG_SEMAFORO_UDP_EMISOR,emisor,16) ||
        inet_pton(AF_INET,CONFIG_SEMAFORO_UDP_IP,&ip)!=1 ||
        CONFIG_SEMAFORO_UDP_TIMEOUT_MS>=CONFIG_SEMAFORO_UDP_INTERVALO_MS ||
        CONFIG_SEMAFORO_UDP_COMUNICACION_MS<=CONFIG_SEMAFORO_UDP_INTERVALO_MS ||
        CONFIG_SEMAFORO_UDP_VIGENCIA_MS>CONFIG_SEMAFORO_MAX_EDAD_DEMANDA_MS ||
        CONFIG_SEMAFORO_UDP_MARGEN_MS>=CONFIG_SEMAFORO_UDP_EDAD_ORIGEN_MS)return false;
    cola_demanda=(QueueHandle_t)cola_ultimo_valor;
    if(xTaskCreate(tarea_udp,"cliente_udp",6144,NULL,4,NULL)!=pdPASS)return false;
    iniciado=true;return true;
}
