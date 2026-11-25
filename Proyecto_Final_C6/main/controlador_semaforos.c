/* Lógica pura: alternancia obligatoria y selección congelada al entrar al verde. */
#include "controlador_semaforos.h"

bool controlador_luces(estado_semaforo_t estado, luces_semaforo_t *luces)
{
    if (!luces) return false;
    *luces=(luces_semaforo_t){LUZ_ROJA,LUZ_ROJA};
    switch (estado) {
        case VERDE_CARRIL_1: luces->carril_1=LUZ_VERDE; break;
        case AMARILLO_CARRIL_1: luces->carril_1=LUZ_AMARILLA; break;
        case VERDE_CARRIL_2: luces->carril_2=LUZ_VERDE; break;
        case AMARILLO_CARRIL_2: luces->carril_2=LUZ_AMARILLA; break;
        case ROJO_TOTAL_INICIAL: case ROJO_TOTAL_1_A_2: case ROJO_TOTAL_2_A_1: case ESTADO_SEGURO: break;
        default: return false;
    }
    return true;
}
const char *controlador_nombre(estado_semaforo_t estado)
{
    static const char *const nombres[]={"ROJO_TOTAL_INICIAL","VERDE_CARRIL_1","AMARILLO_CARRIL_1",
        "ROJO_TOTAL_1_A_2","VERDE_CARRIL_2","AMARILLO_CARRIL_2","ROJO_TOTAL_2_A_1","ESTADO_SEGURO"};
    return estado>=ROJO_TOTAL_INICIAL && estado<=ESTADO_SEGURO ? nombres[estado] : "INVALIDO";
}
bool controlador_iniciar(controlador_semaforos_t *controlador, tiempos_semaforo_t tiempos, uint64_t ahora_ms)
{
    if (!controlador) return false;
    *controlador=(controlador_semaforos_t){.estado=ESTADO_SEGURO,.tiempos=tiempos,.inicio_ms=ahora_ms,
        .prioridad=prioridad_parametros_iniciales(),.max_edad_demanda_ms=5000};
    if (!tiempos.verde_1_ms || !tiempos.verde_2_ms || !tiempos.amarillo_ms || !tiempos.rojo_total_ms) return false;
    controlador->estado=ROJO_TOTAL_INICIAL;
    return true;
}
bool controlador_configurar_adaptativo(controlador_semaforos_t *controlador, parametros_prioridad_t parametros, uint32_t max_edad_ms)
{
    if (!controlador || controlador->estado!=ROJO_TOTAL_INICIAL) return false;
    if (!prioridad_parametros_validos(parametros) || !max_edad_ms) { controlador->estado=ESTADO_SEGURO; return false; }
    controlador->prioridad=parametros; controlador->adaptativo=true; controlador->max_edad_demanda_ms=max_edad_ms;
    controlador->tiempos.amarillo_ms=parametros.amarillo_ms; controlador->tiempos.rojo_total_ms=parametros.rojo_total_ms;
    return true;
}
resultado_demanda_t controlador_recibir_demanda(controlador_semaforos_t *controlador, demanda_vehicular_t demanda, uint64_t ahora_ms)
{
    if (!controlador) return DEMANDA_REPETIDA_O_FUERA_ORDEN;
    return gestor_demanda_recibir(&controlador->demanda,demanda,ahora_ms,controlador->max_edad_demanda_ms);
}
void controlador_solicitar_seguro(controlador_semaforos_t *controlador) { if (controlador) controlador->seguro_solicitado=true; }

static bool seleccionar_verde(controlador_semaforos_t *controlador, estado_semaforo_t siguiente, uint64_t ahora_ms)
{
    controlador->demanda_aplicada_valida=gestor_demanda_vigente(&controlador->demanda,ahora_ms,controlador->max_edad_demanda_ms);
    controlador->demanda_aplicada=controlador->demanda_aplicada_valida ? controlador->demanda.ultima : (demanda_vehicular_t){0};
    controlador->decision=(decision_prioridad_t){controlador->tiempos.verde_1_ms,controlador->tiempos.verde_2_ms,0,0};
    if (controlador->adaptativo) {
        controlador->decision=(decision_prioridad_t){controlador->prioridad.verde_min_ms,controlador->prioridad.verde_min_ms,0,0};
        if (controlador->demanda_aplicada_valida && !prioridad_calcular(controlador->prioridad,controlador->demanda_aplicada.n1,
            controlador->demanda_aplicada.n2,&controlador->decision)) return false;
    }
    controlador->verde_seleccionado_ms=siguiente==VERDE_CARRIL_1 ? controlador->decision.verde_1_ms : controlador->decision.verde_2_ms;
    return true;
}
bool controlador_actualizar(controlador_semaforos_t *controlador, uint64_t ahora_ms)
{
    if (!controlador) return false;
    uint32_t duracion_ms;
    estado_semaforo_t siguiente;
    switch (controlador->estado) {
        case ROJO_TOTAL_INICIAL: duracion_ms=controlador->tiempos.rojo_total_ms; siguiente=VERDE_CARRIL_1; break;
        case VERDE_CARRIL_1: duracion_ms=controlador->verde_seleccionado_ms; siguiente=AMARILLO_CARRIL_1; break;
        case AMARILLO_CARRIL_1: duracion_ms=controlador->tiempos.amarillo_ms; siguiente=ROJO_TOTAL_1_A_2; break;
        case ROJO_TOTAL_1_A_2: duracion_ms=controlador->tiempos.rojo_total_ms; siguiente=VERDE_CARRIL_2; break;
        case VERDE_CARRIL_2: duracion_ms=controlador->verde_seleccionado_ms; siguiente=AMARILLO_CARRIL_2; break;
        case AMARILLO_CARRIL_2: duracion_ms=controlador->tiempos.amarillo_ms; siguiente=ROJO_TOTAL_2_A_1; break;
        case ROJO_TOTAL_2_A_1: duracion_ms=controlador->tiempos.rojo_total_ms; siguiente=VERDE_CARRIL_1; break;
        case ESTADO_SEGURO: return false;
        default: controlador->estado=ESTADO_SEGURO; controlador->inicio_ms=ahora_ms; return true;
    }
    if (ahora_ms<controlador->inicio_ms || !duracion_ms) {
        controlador->estado=ESTADO_SEGURO; controlador->inicio_ms=ahora_ms; return true;
    }
    bool verde=controlador->estado==VERDE_CARRIL_1 || controlador->estado==VERDE_CARRIL_2;
    if (!(controlador->seguro_solicitado && verde) && ahora_ms-controlador->inicio_ms<duracion_ms) return false;
    if (controlador->seguro_solicitado && (controlador->estado==ROJO_TOTAL_INICIAL || controlador->estado==ROJO_TOTAL_1_A_2 ||
        controlador->estado==ROJO_TOTAL_2_A_1)) siguiente=ESTADO_SEGURO;
    if ((siguiente==VERDE_CARRIL_1 || siguiente==VERDE_CARRIL_2) && !seleccionar_verde(controlador,siguiente,ahora_ms))
        siguiente=ESTADO_SEGURO;
    controlador->estado=siguiente; controlador->inicio_ms=ahora_ms;
    return true;
}
