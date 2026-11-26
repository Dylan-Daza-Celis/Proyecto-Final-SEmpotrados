#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "prioridad_vehicular.h"
#include "gestor_demanda.h"

typedef enum {
    ROJO_TOTAL_INICIAL, VERDE_CARRIL_1, AMARILLO_CARRIL_1, ROJO_TOTAL_1_A_2,
    VERDE_CARRIL_2, AMARILLO_CARRIL_2, ROJO_TOTAL_2_A_1, ESTADO_SEGURO
} estado_semaforo_t;
typedef enum { LUZ_ROJA, LUZ_AMARILLA, LUZ_VERDE } color_semaforo_t;
typedef struct { color_semaforo_t carril_1, carril_2; } luces_semaforo_t;
typedef struct { uint32_t verde_1_ms, verde_2_ms, amarillo_ms, rojo_total_ms; } tiempos_semaforo_t;
typedef struct {
    estado_semaforo_t estado;
    tiempos_semaforo_t tiempos;
    uint64_t inicio_ms;
    bool seguro_solicitado;
    bool adaptativo, demanda_aplicada_valida;
    uint32_t verde_seleccionado_ms, max_edad_demanda_ms;
    parametros_prioridad_t prioridad;
    gestor_demanda_t demanda;
    demanda_vehicular_t demanda_aplicada;
    decision_prioridad_t decision;
    unsigned carril_inicial;
} controlador_semaforos_t;

bool controlador_iniciar(controlador_semaforos_t *controlador, tiempos_semaforo_t tiempos, uint64_t ahora_ms);
bool controlador_actualizar(controlador_semaforos_t *controlador, uint64_t ahora_ms);
bool controlador_configurar_adaptativo(controlador_semaforos_t *controlador, parametros_prioridad_t parametros, uint32_t max_edad_ms);
resultado_demanda_t controlador_recibir_demanda(controlador_semaforos_t *controlador, demanda_vehicular_t demanda, uint64_t ahora_ms);
void controlador_solicitar_seguro(controlador_semaforos_t *controlador);
bool controlador_luces(estado_semaforo_t estado, luces_semaforo_t *luces);
const char *controlador_nombre(estado_semaforo_t estado);
