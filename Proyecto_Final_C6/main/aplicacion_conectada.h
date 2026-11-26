#pragma once
#include "control_conectado.h"
typedef struct {
    void *contexto;
    estado_recepcion_t (*leer)(void *contexto);
    uint64_t (*reloj)(void *contexto);
    void (*invalidar)(void *contexto);
    bool (*escribir)(void *contexto,luces_semaforo_t luces);
} operaciones_conectadas_t;
typedef struct {
    bool verde_aplicado,interrumpido;
    estado_semaforo_t estado_verde;
    uint64_t inicio_verde_ms,duracion_aplicacion_ms;
} informe_aplicacion_t;
/* Propietario unico, solo al cambiar de fase. Antes de verde se viene de rojo.
 * Comprobar antes y despues de GPIO sin bloquear red. */
bool aplicacion_conectada(control_conectado_t *g,controlador_semaforos_t *c,
    operaciones_conectadas_t op,informe_aplicacion_t *informe);
