#include <inttypes.h>
#include "sdkconfig.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "controlador_semaforos.h"
#include "semaforo_gpio.h"
#include "simulador_demanda.h"
#include "demanda_vehicular.h"

static const char *TAG="semaforos";
static uint64_t ahora_ms(void) { return (uint64_t)esp_timer_get_time()/1000; }
static void tarea_controlador(void *parametro)
{
    (void)parametro;
#ifndef CONFIG_SEMAFORO_PINOUT_CONFIRMADO
    ESP_LOGE(TAG,"Pines provisionales: confirmar placa/esquema y habilitar en menuconfig antes de conectar LEDs");
    vTaskDelete(NULL);
    return;
#endif
    semaforo_gpio_t gpio;
    if (!semaforo_gpio_iniciar(&gpio,semaforo_operaciones_idf())) {
        ESP_LOGE(TAG,"Fallo de inicializacion GPIO; se detienen transiciones");
        vTaskDelete(NULL); return;
    }
    controlador_semaforos_t controlador;
    tiempos_semaforo_t tiempos={CONFIG_SEMAFORO_VERDE_1_MS,CONFIG_SEMAFORO_VERDE_2_MS,
        CONFIG_SEMAFORO_AMARILLO_MS,CONFIG_SEMAFORO_ROJO_TOTAL_MS};
    if (!controlador_iniciar(&controlador,tiempos,ahora_ms())) {
        ESP_LOGE(TAG,"Tiempos invalidos; intentar ambos rojos y detener");
        semaforo_gpio_seguro(&gpio); vTaskDelete(NULL); return;
    }
    ESP_LOGI(TAG,"Modo demostracion autonoma; inicio en ambos rojos; sin UDP ni prioridad");
    QueueHandle_t cola=xQueueCreate(1,sizeof(demanda_vehicular_t));
    if (!cola) {
        ESP_LOGE(TAG,"No se pudo crear cola de ultimo valor; intentar ambos rojos y detener");
        semaforo_gpio_seguro(&gpio); vTaskDelete(NULL); return;
    }
#ifdef CONFIG_SEMAFORO_SIMULAR_DEMANDA
    if (!simulador_demanda_iniciar(cola)) {
        ESP_LOGE(TAG,"No se pudo crear simulador; permanece en seguro");
        semaforo_gpio_seguro(&gpio); vQueueDelete(cola); vTaskDelete(NULL); return;
    }
#endif
    uint64_t ultima_secuencia=0;
    for (;;) {
        demanda_vehicular_t demanda;
        if (xQueueReceive(cola,&demanda,0)==pdPASS) {
            if (demanda_validar(demanda,ahora_ms(),ultima_secuencia)) {
                ultima_secuencia=demanda.secuencia;
                ESP_LOGI(TAG,"Demanda simulada N1=%"PRId32" N2=%"PRId32" seq=%"PRIu64"; ciclo fijo",
                         demanda.n1,demanda.n2,demanda.secuencia);
            } else ESP_LOGW(TAG,"Demanda rechazada; no altera ciclo de demostracion");
        }
        if (controlador_actualizar(&controlador,ahora_ms())) {
            luces_semaforo_t luces;
            if (!controlador_luces(controlador.estado,&luces) || !semaforo_gpio_aplicar(&gpio,luces)) {
                ESP_LOGE(TAG,"Fallo GPIO/estado; intentar ambos rojos y detener transiciones");
                semaforo_gpio_seguro(&gpio); controlador.estado=ESTADO_SEGURO;
                vTaskDelete(NULL); return; /* El simulador puede conservar su cola, sin acceso a GPIO. */
            }
            controlador.inicio_ms=ahora_ms(); /* Duración completa desde aplicación, incluso con planificación tardía. */
            ESP_LOGI(TAG,"Estado %s",controlador_nombre(controlador.estado));
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}

void app_main(void)
{
    if (xTaskCreate(tarea_controlador,"controlador_semaforos",4096,NULL,5,NULL)!=pdPASS)
        ESP_LOGE(TAG,"No se pudo crear propietario; GPIO sin inicializar");
}
