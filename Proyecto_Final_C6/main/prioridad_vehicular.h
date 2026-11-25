#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef struct {
    uint32_t verde_min_ms, verde_max_ms, amarillo_ms, rojo_total_ms;
    uint32_t umbral, incremento_ms, objetivo_sin_verde_ms;
} parametros_prioridad_t;
typedef struct {
    uint32_t verde_1_ms, verde_2_ms;
    int32_t diferencia;
    unsigned carril_favorecido;
} decision_prioridad_t;
parametros_prioridad_t prioridad_parametros_iniciales(void);
bool prioridad_parametros_validos(parametros_prioridad_t parametros);
bool prioridad_calcular(parametros_prioridad_t parametros, int32_t n1, int32_t n2, decision_prioridad_t *decision);
