#include "simulador_demanda.h"
#include <inttypes.h>
#include "demanda_vehicular.h"
#include "esp_timer.h"
#include "freertos/task.h"
#include "esp_log.h"
static void tarea_simulacion(void *parametro)
{
    QueueHandle_t cola=(QueueHandle_t)parametro;
    uint64_t secuencia=0;
    typedef struct { int32_t n1,n2; bool valida; uint32_t pausa_ms; const char *nombre; } escenario_t;
    static const escenario_t escenarios[]={
        {0,0,true,2000,"vacio medido"},{3,3,true,2000,"equilibrio"},
        {4,1,true,2000,"carril 1"},{1,5,true,2000,"carril 2"},
        {2,0,true,2000,"diferencia creciente 2"},{3,0,true,2000,"diferencia creciente 3"},
        {5,0,true,2000,"saturacion"},{10,0,true,2000,"congestion sostenida 1"},
        {10,0,true,2000,"congestion sostenida 2"},{10,0,true,2000,"congestion sostenida 3"},
        {10,0,true,2000,"congestion sostenida 4"},{0,10,true,2000,"cambio durante verde"},
        {0,0,false,2000,"invalidacion explicita"},{4,1,true,10000,"interrupcion de actualizaciones"}
    };
    unsigned indice=0;
    for (;;) {
        const escenario_t *escenario=&escenarios[indice];
        demanda_vehicular_t d={.n1=escenario->n1, .n2=escenario->n2, .secuencia=++secuencia,
            .recibida_ms=(uint64_t)esp_timer_get_time()/1000, .valida=escenario->valida};
        ESP_LOGI("simulador","SIMULADO: %s; pausa siguiente=%"PRIu32" ms",escenario->nombre,escenario->pausa_ms);
        xQueueOverwrite(cola,&d);
        vTaskDelay(pdMS_TO_TICKS(escenario->pausa_ms));
        indice=(indice+1)%(sizeof escenarios/sizeof escenarios[0]);
    }
}
bool simulador_demanda_iniciar(QueueHandle_t cola)
{ return xTaskCreate(tarea_simulacion,"demanda_simulada",3072,cola,3,NULL)==pdPASS; }
