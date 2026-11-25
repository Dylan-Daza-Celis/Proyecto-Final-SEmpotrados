/* Lógica pura. Cada fase empieza al aplicar sus luces, sin recuperar tiempo perdido. */
#include "controlador_semaforos.h"

bool controlador_luces(estado_semaforo_t estado, luces_semaforo_t *luces)
{
    if (!luces) return false;
    *luces = (luces_semaforo_t){LUZ_ROJA, LUZ_ROJA};
    switch (estado) {
        case VERDE_CARRIL_1: luces->carril_1 = LUZ_VERDE; break;
        case AMARILLO_CARRIL_1: luces->carril_1 = LUZ_AMARILLA; break;
        case VERDE_CARRIL_2: luces->carril_2 = LUZ_VERDE; break;
        case AMARILLO_CARRIL_2: luces->carril_2 = LUZ_AMARILLA; break;
        case ROJO_TOTAL_INICIAL: case ROJO_TOTAL_1_A_2: case ROJO_TOTAL_2_A_1: case ESTADO_SEGURO: break;
        default: return false;
    }
    return true;
}

const char *controlador_nombre(estado_semaforo_t estado)
{
    static const char *const nombres[] = {"ROJO_TOTAL_INICIAL", "VERDE_CARRIL_1", "AMARILLO_CARRIL_1",
        "ROJO_TOTAL_1_A_2", "VERDE_CARRIL_2", "AMARILLO_CARRIL_2", "ROJO_TOTAL_2_A_1", "ESTADO_SEGURO"};
    return estado >= ROJO_TOTAL_INICIAL && estado <= ESTADO_SEGURO ? nombres[estado] : "INVALIDO";
}

bool controlador_iniciar(controlador_semaforos_t *controlador, tiempos_semaforo_t tiempos, uint64_t ahora_ms)
{
    if (!controlador) return false;
    *controlador = (controlador_semaforos_t){.estado=ESTADO_SEGURO, .tiempos=tiempos, .inicio_ms=ahora_ms};
    if (!tiempos.verde_1_ms || !tiempos.verde_2_ms || !tiempos.amarillo_ms || !tiempos.rojo_total_ms) return false;
    controlador->estado = ROJO_TOTAL_INICIAL;
    return true;
}

void controlador_solicitar_seguro(controlador_semaforos_t *controlador) { if (controlador) controlador->seguro_solicitado = true; }

bool controlador_actualizar(controlador_semaforos_t *controlador, uint64_t ahora_ms)
{
    if (!controlador) return false;
    uint32_t duracion_ms;
    estado_semaforo_t siguiente;
    switch (controlador->estado) {
        case ROJO_TOTAL_INICIAL: duracion_ms=controlador->tiempos.rojo_total_ms; siguiente=VERDE_CARRIL_1; break;
        case VERDE_CARRIL_1: duracion_ms=controlador->tiempos.verde_1_ms; siguiente=AMARILLO_CARRIL_1; break;
        case AMARILLO_CARRIL_1: duracion_ms=controlador->tiempos.amarillo_ms; siguiente=ROJO_TOTAL_1_A_2; break;
        case ROJO_TOTAL_1_A_2: duracion_ms=controlador->tiempos.rojo_total_ms; siguiente=VERDE_CARRIL_2; break;
        case VERDE_CARRIL_2: duracion_ms=controlador->tiempos.verde_2_ms; siguiente=AMARILLO_CARRIL_2; break;
        case AMARILLO_CARRIL_2: duracion_ms=controlador->tiempos.amarillo_ms; siguiente=ROJO_TOTAL_2_A_1; break;
        case ROJO_TOTAL_2_A_1: duracion_ms=controlador->tiempos.rojo_total_ms; siguiente=VERDE_CARRIL_1; break;
        case ESTADO_SEGURO: return false;
        default: controlador->estado=ESTADO_SEGURO; controlador->inicio_ms=ahora_ms; return true;
    }
    if (ahora_ms < controlador->inicio_ms || !duracion_ms) {
        controlador->estado=ESTADO_SEGURO; controlador->inicio_ms=ahora_ms; return true;
    }
    if (controlador->seguro_solicitado && (controlador->estado==VERDE_CARRIL_1 || controlador->estado==VERDE_CARRIL_2)) {
        /* Salida controlada: amarillo completo incluso si se interrumpe el verde. */
    } else if (ahora_ms-controlador->inicio_ms < duracion_ms) return false;
    if (controlador->seguro_solicitado && (controlador->estado==ROJO_TOTAL_INICIAL ||
        controlador->estado==ROJO_TOTAL_1_A_2 || controlador->estado==ROJO_TOTAL_2_A_1)) siguiente=ESTADO_SEGURO;
    controlador->estado=siguiente;
    controlador->inicio_ms=ahora_ms;
    return true;
}
