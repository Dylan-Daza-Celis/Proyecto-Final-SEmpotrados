#pragma once
#include "controlador_semaforos.h"
#include "cliente_udp.h"
typedef struct { uint64_t generacion,resultado;unsigned ultimo_carril; } control_conectado_t;
/* No toca GPIO. Una seguridad solicitada solo termina tras despeje completo.
 * El propietario reconoce generacion DESPUES de aplicar ambos rojos fisicos.
 */
bool control_conectado_paso(control_conectado_t *guardia,controlador_semaforos_t *c,estado_red_t red,uint64_t ahora);
/* Registrar alternancia solo cuando GPIO confirmo aplicar la fase. */
void control_conectado_fase_aplicada(control_conectado_t *guardia,estado_semaforo_t estado);
