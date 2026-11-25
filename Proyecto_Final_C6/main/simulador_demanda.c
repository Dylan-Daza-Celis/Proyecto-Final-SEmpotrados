#include "simulador_demanda.h"
#include "demanda_vehicular.h"
#include "esp_timer.h"
#include "freertos/task.h"
static void tarea_simulacion(void *parametro)
{
    QueueHandle_t cola=(QueueHandle_t)parametro;
    uint64_t secuencia=0;
    for (;;) {
        demanda_vehicular_t d={.n1=3, .n2=1, .secuencia=++secuencia,
            .recibida_ms=(uint64_t)esp_timer_get_time()/1000, .valida=true};
        xQueueOverwrite(cola,&d);
        vTaskDelay(pdMS_TO_TICKS(2000));
    }
}
bool simulador_demanda_iniciar(QueueHandle_t cola)
{ return xTaskCreate(tarea_simulacion,"demanda_simulada",3072,cola,3,NULL)==pdPASS; }
