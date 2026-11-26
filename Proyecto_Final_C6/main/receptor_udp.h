#pragma once
#include "demanda_conectada.h"
bool receptor_udp_iniciar(void *cola_ultimo_valor);
void receptor_udp_invalidar(void);
void receptor_udp_conexion(bool conectado);
estado_recepcion_t receptor_udp_estado(void);
/* Notificacion local del propietario, despues de aplicar GPIO. No envia nada por red. */
void receptor_udp_estado_controlador(uint8_t estado,uint64_t generacion);
