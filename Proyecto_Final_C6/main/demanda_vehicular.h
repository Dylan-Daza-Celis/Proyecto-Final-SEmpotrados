#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef struct { int32_t n1, n2; uint64_t secuencia, recibida_ms; bool valida; } demanda_vehicular_t;
static inline bool demanda_validar(demanda_vehicular_t demanda, uint64_t ahora_ms, uint64_t ultima_secuencia)
{
    return demanda.valida && demanda.n1>=0 && demanda.n1<=1000 && demanda.n2>=0 && demanda.n2<=1000 &&
           demanda.secuencia>ultima_secuencia && demanda.recibida_ms<=ahora_ms && ahora_ms-demanda.recibida_ms<=5000;
}
