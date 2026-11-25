#include <inttypes.h>
#include "sdkconfig.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "controlador_semaforos.h"
#include "semaforo_gpio.h"
#include "simulador_demanda.h"

static const char *TAG="semaforos";
static uint64_t ahora_ms(void) { return (uint64_t)esp_timer_get_time()/1000; }

static void registrar_demanda(const controlador_semaforos_t *controlador, uint64_t ahora)
{
    const gestor_demanda_t *gestor=&controlador->demanda;
    if (!gestor_demanda_vigente(gestor,ahora,controlador->max_edad_demanda_ms)) {
        if (gestor->ultima_secuencia && gestor->ultima.recibida_ms<=ahora)
            ESP_LOGI(TAG,"Demanda NO vigente; edad=%"PRIu64" ms seq=%"PRIu64"; sin medicion N1/N2",
                ahora-gestor->ultima.recibida_ms,gestor->ultima_secuencia);
        else ESP_LOGI(TAG,"Demanda NO vigente; edad no disponible; sin medicion N1/N2");
        ESP_LOGI(TAG,"Proxima seleccion sin demanda usa verde convencional; fase actual conserva duracion");
        return;
    }
    ESP_LOGI(TAG,"N1=%"PRId32" N2=%"PRId32" D=%"PRId32" valida=1 edad=%"PRIu64" ms seq=%"PRIu64,
        gestor->ultima.n1,gestor->ultima.n2,gestor->ultima.n1-gestor->ultima.n2,
        ahora-gestor->ultima.recibida_ms,gestor->ultima.secuencia);
}
static void tarea_controlador(void *parametro)
{
    (void)parametro;
#ifndef CONFIG_SEMAFORO_PINOUT_CONFIRMADO
    ESP_LOGE(TAG,"Confirmar placa/esquema y pinout provisional en menuconfig; salidas deshabilitadas");
    vTaskDelete(NULL); return;
#endif
    semaforo_gpio_t gpio;
    if (!semaforo_gpio_iniciar(&gpio,semaforo_operaciones_idf())) {
        ESP_LOGE(TAG,"Fallo GPIO; transiciones detenidas"); vTaskDelete(NULL); return;
    }
    controlador_semaforos_t controlador;
    tiempos_semaforo_t tiempos={CONFIG_SEMAFORO_VERDE_1_MS,CONFIG_SEMAFORO_VERDE_2_MS,
        CONFIG_SEMAFORO_AMARILLO_MS,CONFIG_SEMAFORO_ROJO_TOTAL_MS};
    if (!controlador_iniciar(&controlador,tiempos,ahora_ms())) {
        ESP_LOGE(TAG,"Tiempos invalidos"); semaforo_gpio_seguro(&gpio); vTaskDelete(NULL); return;
    }
    controlador.max_edad_demanda_ms=CONFIG_SEMAFORO_MAX_EDAD_DEMANDA_MS;
#ifdef CONFIG_SEMAFORO_ADAPTATIVO
    parametros_prioridad_t parametros={CONFIG_SEMAFORO_VERDE_MIN_MS,CONFIG_SEMAFORO_VERDE_MAX_MS,
        CONFIG_SEMAFORO_AMARILLO_MS,CONFIG_SEMAFORO_ROJO_TOTAL_MS,CONFIG_SEMAFORO_UMBRAL,
        CONFIG_SEMAFORO_INCREMENTO_MS,CONFIG_SEMAFORO_OBJETIVO_SIN_VERDE_MS};
    if (!controlador_configurar_adaptativo(&controlador,parametros,CONFIG_SEMAFORO_MAX_EDAD_DEMANDA_MS)) {
        ESP_LOGE(TAG,"Parametros adaptativos incompatibles con objetivo nominal");
        semaforo_gpio_seguro(&gpio); vTaskDelete(NULL); return;
    }
#endif
    uint64_t maximo_convencional=tiempos.verde_1_ms>tiempos.verde_2_ms ? tiempos.verde_1_ms : tiempos.verde_2_ms;
    if (!controlador.adaptativo && maximo_convencional+2*(uint64_t)tiempos.amarillo_ms+
        2*(uint64_t)tiempos.rojo_total_ms>CONFIG_SEMAFORO_OBJETIVO_SIN_VERDE_MS) {
        ESP_LOGE(TAG,"Tiempos convencionales incompatibles con objetivo nominal");
        semaforo_gpio_seguro(&gpio); vTaskDelete(NULL); return;
    }
    ESP_LOGI(TAG,"Modo %s, inicio ambos rojos, sin UDP/Wi-Fi",controlador.adaptativo ? "ADAPTATIVO SIMULADO":"CONVENCIONAL");
    QueueHandle_t cola=xQueueCreate(1,sizeof(demanda_vehicular_t));
    if (!cola) {
        ESP_LOGE(TAG,"Fallo creando cola"); semaforo_gpio_seguro(&gpio); vTaskDelete(NULL); return;
    }
#ifdef CONFIG_SEMAFORO_SIMULAR_DEMANDA
    if (!simulador_demanda_iniciar(cola)) {
        ESP_LOGE(TAG,"Fallo simulador"); semaforo_gpio_seguro(&gpio);
        vQueueDelete(cola); vTaskDelete(NULL); return;
    }
#endif
    uint64_t fin_verde[2]={0}; bool tiene_fin[2]={false,false};
    for (;;) {
        demanda_vehicular_t demanda;
        if (xQueueReceive(cola,&demanda,0)==pdPASS) {
            resultado_demanda_t resultado=controlador_recibir_demanda(&controlador,demanda,ahora_ms());
            ESP_LOGI(TAG,"Demanda SIMULADA seq=%"PRIu64" recepcion=%s",demanda.secuencia,
                resultado==DEMANDA_NUEVA_VALIDA ? "VALIDA" :
                resultado==DEMANDA_INVALIDACION_NUEVA ? "INVALIDACION NUEVA":"DUPLICADA/FUERA DE ORDEN");
            registrar_demanda(&controlador,ahora_ms());
        }
        estado_semaforo_t anterior=controlador.estado;
        uint64_t inicio_anterior=controlador.inicio_ms;
        if (controlador_actualizar(&controlador,ahora_ms())) {
            luces_semaforo_t luces;
            uint64_t antes_gpio=ahora_ms();
            if (!controlador_luces(controlador.estado,&luces) || !semaforo_gpio_aplicar(&gpio,luces)) {
                ESP_LOGE(TAG,"Fallo GPIO/estado: bloquear y pedir rojos");
                semaforo_gpio_seguro(&gpio); controlador.estado=ESTADO_SEGURO; vTaskDelete(NULL); return;
            }
            uint64_t aplicada=ahora_ms();
            controlador.inicio_ms=aplicada;
            ESP_LOGI(TAG,"%s -> %s duracion real fase=%"PRIu64" ms",
                controlador_nombre(anterior),controlador_nombre(controlador.estado),aplicada-inicio_anterior);
            registrar_demanda(&controlador,aplicada);
            if (anterior==VERDE_CARRIL_1 || anterior==VERDE_CARRIL_2) {
                int carril=anterior==VERDE_CARRIL_1 ? 0 : 1;
                fin_verde[carril]=antes_gpio; tiene_fin[carril]=true;
            }
            if (controlador.estado==VERDE_CARRIL_1 || controlador.estado==VERDE_CARRIL_2) {
                int carril=controlador.estado==VERDE_CARRIL_1 ? 0 : 1;
                ESP_LOGI(TAG,"Carril %d verde seleccionado=%"PRIu32" ms favorecido=%u motivo=%s",
                    carril+1,controlador.verde_seleccionado_ms,controlador.decision.carril_favorecido,
                    !controlador.adaptativo ? "convencional" : !controlador.demanda_aplicada_valida ? "sin demanda vigente" :
                    controlador.decision.carril_favorecido ? "diferencia supera umbral":"demanda equilibrada");
                if (tiene_fin[carril]) {
                    uint64_t intervalo=aplicada-fin_verde[carril];
                    ESP_LOGI(TAG,"Carril %d intervalo observado sin verde=%"PRIu64" ms",carril+1,intervalo);
                    if (intervalo>CONFIG_SEMAFORO_OBJETIVO_SIN_VERDE_MS)
                        ESP_LOGW(TAG,"Intervalo supera objetivo nominal; no es garantia de tiempo real");
                } else ESP_LOGI(TAG,"Carril %d sin intervalo previo medible",carril+1);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
void app_main(void)
{
    if (xTaskCreate(tarea_controlador,"controlador_semaforos",5120,NULL,5,NULL)!=pdPASS)
        ESP_LOGE(TAG,"No se pudo crear propietario; GPIO sin inicializar");
}
