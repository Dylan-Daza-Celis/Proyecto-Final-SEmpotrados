#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "demanda.h"
#include "semaforo_gpio.h"

/* Parametros y decision matematica: tiempos en ms, conteos sin ponderacion. */
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
bool prioridad_calcular(parametros_prioridad_t parametros, int32_t n1, int32_t n2,
                        decision_prioridad_t *decision);

/* Estado y temporizacion del controlador. */
typedef enum {
    ROJO_TOTAL_INICIAL,
    VERDE_CARRIL_1,
    AMARILLO_CARRIL_1,
    ROJO_TOTAL_1_A_2,
    VERDE_CARRIL_2,
    AMARILLO_CARRIL_2,
    ROJO_TOTAL_2_A_1,
    ESTADO_SEGURO = RECEPCION_FASE_SEGURA
} estado_semaforo_t;
typedef struct {
    uint32_t verde_1_ms, verde_2_ms, amarillo_ms, rojo_total_ms;
} tiempos_semaforo_t;
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

bool controlador_iniciar(controlador_semaforos_t *controlador, tiempos_semaforo_t tiempos,
                         uint64_t ahora_ms);
bool controlador_actualizar(controlador_semaforos_t *controlador, uint64_t ahora_ms);
bool controlador_configurar_adaptativo(controlador_semaforos_t *controlador,
                                       parametros_prioridad_t parametros, uint32_t max_edad_ms);
resultado_demanda_t controlador_recibir_demanda(controlador_semaforos_t *controlador,
                                                demanda_vehicular_t demanda, uint64_t ahora_ms);
void controlador_solicitar_seguro(controlador_semaforos_t *controlador);
bool controlador_luces(estado_semaforo_t estado, luces_semaforo_t *luces);
const char *controlador_nombre(estado_semaforo_t estado);

/* Seguridad y recuperacion del modo conectado. */
typedef struct {
    uint64_t generacion, resultado;
    unsigned ultimo_carril;
} control_conectado_t;
/* No toca GPIO. Una seguridad solicitada solo termina tras despeje completo.
 * El propietario reconoce generacion DESPUES de aplicar ambos rojos fisicos.
 */
bool control_conectado_paso(control_conectado_t *guardia, controlador_semaforos_t *c,
                            estado_recepcion_t red, uint64_t ahora);
/* Registrar alternancia solo cuando GPIO confirmo aplicar la fase. */
void control_conectado_fase_aplicada(control_conectado_t *guardia, estado_semaforo_t estado);

/* Operaciones inyectables: el anfitrion prueba sin driver ni placa. */
typedef struct {
    void *contexto;
    estado_recepcion_t (*leer)(void *contexto);
    uint64_t (*reloj)(void *contexto);
    void (*invalidar)(void *contexto);
    bool (*escribir)(void *contexto, luces_semaforo_t luces);
} operaciones_conectadas_t;
typedef struct {
    bool verde_aplicado, interrumpido;
    estado_semaforo_t estado_verde;
    uint64_t inicio_verde_ms, duracion_aplicacion_ms;
} informe_aplicacion_t;
/* Propietario unico, solo al cambiar de fase. Antes de verde se viene de rojo.
 * Comprobar antes y despues de GPIO sin bloquear red. */
bool aplicacion_conectada(control_conectado_t *g, controlador_semaforos_t *c,
                          operaciones_conectadas_t op, informe_aplicacion_t *informe);
