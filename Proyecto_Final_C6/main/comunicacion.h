#pragma once
#include <stdbool.h>
#include "demanda.h"

/* Wi-Fi STA y receptor UDP; ninguna funcion de este modulo escribe GPIO. */
bool wifi_manager_iniciar(void);

bool receptor_udp_iniciar(void *cola_ultimo_valor);
void receptor_udp_invalidar(void);
estado_recepcion_t receptor_udp_estado(void);
/* Notificacion local del propietario, despues de aplicar GPIO. No envia nada por red. */
void receptor_udp_estado_controlador(uint8_t estado, uint64_t generacion);
