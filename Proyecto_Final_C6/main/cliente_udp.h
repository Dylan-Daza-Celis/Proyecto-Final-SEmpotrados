#pragma once
#include "demanda_vehicular.h"
typedef struct {
    bool valido,asociado;
    uint64_t generacion,reconocida,vence,resultado,recibida_ms;
    demanda_vehicular_t demanda;
    uint8_t estado;
} estado_red_t;
/* Cola FreeRTOS de un valor de demanda; opaca para pruebas anfitrionas del nucleo. */
bool cliente_udp_iniciar(void *cola_ultimo_valor);
void cliente_udp_invalidar_local(void);
estado_red_t cliente_udp_estado(void);
void cliente_udp_estado_controlador(uint8_t estado,uint64_t generacion);
