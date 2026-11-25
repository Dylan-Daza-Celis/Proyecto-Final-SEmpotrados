#pragma once
#include "demanda_vehicular.h"
typedef enum { DEMANDA_NUEVA_VALIDA, DEMANDA_INVALIDACION_NUEVA, DEMANDA_REPETIDA_O_FUERA_ORDEN } resultado_demanda_t;
typedef struct { demanda_vehicular_t ultima; uint64_t ultima_secuencia; bool disponible; } gestor_demanda_t;
resultado_demanda_t gestor_demanda_recibir(gestor_demanda_t *gestor, demanda_vehicular_t demanda,
                                         uint64_t ahora_ms, uint32_t max_edad_ms);
bool gestor_demanda_vigente(const gestor_demanda_t *gestor, uint64_t ahora_ms, uint32_t max_edad_ms);
