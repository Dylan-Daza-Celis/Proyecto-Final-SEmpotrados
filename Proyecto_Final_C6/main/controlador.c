#include "controlador.h"

/* 1. Parametros y calculo de prioridad. No accede a hardware. */
/* Matemática pura: límites derivados de parámetros, sin GPIO/FreeRTOS. */
parametros_prioridad_t prioridad_parametros_iniciales(void)
{
    return (parametros_prioridad_t){5000, 13000, 2000, 1000, 2, 2000, 20000};
}

bool prioridad_parametros_validos(parametros_prioridad_t parametros)
{
    uint64_t intervalo = (uint64_t)parametros.verde_max_ms + 2 * (uint64_t)parametros.amarillo_ms +
                         2 * (uint64_t)parametros.rojo_total_ms;
    return parametros.verde_min_ms >= 5000 && parametros.verde_max_ms >= parametros.verde_min_ms &&
           parametros.amarillo_ms >= 2000 && parametros.rojo_total_ms >= 1000 &&
           parametros.umbral > 0 && parametros.incremento_ms > 0 &&
           intervalo <= parametros.objetivo_sin_verde_ms;
}

/* Calculo de prioridad: la diferencia decide cual verde puede aumentar. */
bool prioridad_calcular(parametros_prioridad_t parametros, int32_t n1, int32_t n2,
                        decision_prioridad_t *decision)
{
    if (!decision || !prioridad_parametros_validos(parametros) || n1 < 0 || n1 > 1000 || n2 < 0 ||
        n2 > 1000) {
        return false;
    }
    int64_t diferencia = (int64_t)n1 - n2;
    uint64_t magnitud = (uint64_t)(diferencia < 0 ? -diferencia : diferencia);
    *decision = (decision_prioridad_t){parametros.verde_min_ms, parametros.verde_min_ms,
                                       (int32_t)diferencia, 0};
    if (magnitud >= parametros.umbral) {
        uint64_t incremento =
            (magnitud - parametros.umbral + 1) * (uint64_t)parametros.incremento_ms;
        uint32_t limite = parametros.verde_max_ms - parametros.verde_min_ms;
        if (incremento > limite) {
            incremento = limite;
        }
        decision->carril_favorecido = diferencia > 0 ? 1 : 2;
        if (diferencia > 0) {
            decision->verde_1_ms += (uint32_t)incremento;
        } else {
            decision->verde_2_ms += (uint32_t)incremento;
        }
    }
    return true;
}

/* 2. Maquina de estados y temporizacion. */
/* Lógica pura: alternancia obligatoria y selección congelada al entrar al verde. */

bool controlador_luces(estado_semaforo_t estado, luces_semaforo_t *luces)
{
    if (!luces) {
        return false;
    }
    *luces = (luces_semaforo_t){LUZ_ROJA, LUZ_ROJA};
    switch (estado) {
        case VERDE_CARRIL_1:
            luces->carril_1 = LUZ_VERDE;
            break;
        case AMARILLO_CARRIL_1:
            luces->carril_1 = LUZ_AMARILLA;
            break;
        case VERDE_CARRIL_2:
            luces->carril_2 = LUZ_VERDE;
            break;
        case AMARILLO_CARRIL_2:
            luces->carril_2 = LUZ_AMARILLA;
            break;
        case ROJO_TOTAL_INICIAL:
        case ROJO_TOTAL_1_A_2:
        case ROJO_TOTAL_2_A_1:
        case ESTADO_SEGURO:
            break;
        default:
            return false;
    }
    return true;
}
const char *controlador_nombre(estado_semaforo_t estado)
{
    static const char *const nombres[] = {
        "ROJO_TOTAL_INICIAL", "VERDE_CARRIL_1",    "AMARILLO_CARRIL_1", "ROJO_TOTAL_1_A_2",
        "VERDE_CARRIL_2",     "AMARILLO_CARRIL_2", "ROJO_TOTAL_2_A_1",  "ESTADO_SEGURO"};
    return estado >= ROJO_TOTAL_INICIAL && estado <= ESTADO_SEGURO ? nombres[estado] : "INVALIDO";
}
/* Temporizacion: cada fase conserva su inicio y duracion seleccionada. */
bool controlador_iniciar(controlador_semaforos_t *controlador, tiempos_semaforo_t tiempos,
                         uint64_t ahora_ms)
{
    if (!controlador) {
        return false;
    }
    *controlador = (controlador_semaforos_t){.estado = ESTADO_SEGURO,
                                             .tiempos = tiempos,
                                             .inicio_ms = ahora_ms,
                                             .prioridad = prioridad_parametros_iniciales(),
                                             .max_edad_demanda_ms = 5000,
                                             .carril_inicial = 1};
    if (!tiempos.verde_1_ms || !tiempos.verde_2_ms || !tiempos.amarillo_ms ||
        !tiempos.rojo_total_ms) {
        return false;
    }
    controlador->estado = ROJO_TOTAL_INICIAL;
    return true;
}
bool controlador_configurar_adaptativo(controlador_semaforos_t *controlador,
                                       parametros_prioridad_t parametros, uint32_t max_edad_ms)
{
    if (!controlador || controlador->estado != ROJO_TOTAL_INICIAL) {
        return false;
    }
    if (!prioridad_parametros_validos(parametros) || !max_edad_ms) {
        controlador->estado = ESTADO_SEGURO;
        return false;
    }
    controlador->prioridad = parametros;
    controlador->adaptativo = true;
    controlador->max_edad_demanda_ms = max_edad_ms;
    controlador->tiempos.amarillo_ms = parametros.amarillo_ms;
    controlador->tiempos.rojo_total_ms = parametros.rojo_total_ms;
    return true;
}
resultado_demanda_t controlador_recibir_demanda(controlador_semaforos_t *controlador,
                                                demanda_vehicular_t demanda, uint64_t ahora_ms)
{
    if (!controlador) {
        return DEMANDA_REPETIDA_O_FUERA_ORDEN;
    }
    return gestor_demanda_recibir(&controlador->demanda, demanda, ahora_ms,
                                  controlador->max_edad_demanda_ms);
}
/* Estado seguro: una solicitud queda retenida hasta completar despejes. */
void controlador_solicitar_seguro(controlador_semaforos_t *controlador)
{
    if (controlador) {
        controlador->seguro_solicitado = true;
    }
}

static bool seleccionar_verde(controlador_semaforos_t *controlador, estado_semaforo_t siguiente,
                              uint64_t ahora_ms)
{
    controlador->demanda_aplicada_valida =
        gestor_demanda_vigente(&controlador->demanda, ahora_ms, controlador->max_edad_demanda_ms);
    controlador->demanda_aplicada = controlador->demanda_aplicada_valida
                                        ? controlador->demanda.ultima
                                        : (demanda_vehicular_t){0};
    controlador->decision = (decision_prioridad_t){controlador->tiempos.verde_1_ms,
                                                   controlador->tiempos.verde_2_ms, 0, 0};
    if (controlador->adaptativo) {
        controlador->decision = (decision_prioridad_t){controlador->prioridad.verde_min_ms,
                                                       controlador->prioridad.verde_min_ms, 0, 0};
        if (controlador->demanda_aplicada_valida &&
            !prioridad_calcular(controlador->prioridad, controlador->demanda_aplicada.n1,
                                controlador->demanda_aplicada.n2, &controlador->decision)) {
            return false;
        }
    }
    controlador->verde_seleccionado_ms = siguiente == VERDE_CARRIL_1
                                             ? controlador->decision.verde_1_ms
                                             : controlador->decision.verde_2_ms;
    return true;
}
/* Maquina de estados: como maximo una transicion por actualizacion. */
bool controlador_actualizar(controlador_semaforos_t *controlador, uint64_t ahora_ms)
{
    if (!controlador) {
        return false;
    }
    uint32_t duracion_ms;
    estado_semaforo_t siguiente;
    switch (controlador->estado) {
        case ROJO_TOTAL_INICIAL:
            duracion_ms = controlador->tiempos.rojo_total_ms;
            siguiente = controlador->carril_inicial == 2 ? VERDE_CARRIL_2 : VERDE_CARRIL_1;
            break;
        case VERDE_CARRIL_1:
            duracion_ms = controlador->verde_seleccionado_ms;
            siguiente = AMARILLO_CARRIL_1;
            break;
        case AMARILLO_CARRIL_1:
            duracion_ms = controlador->tiempos.amarillo_ms;
            siguiente = ROJO_TOTAL_1_A_2;
            break;
        case ROJO_TOTAL_1_A_2:
            duracion_ms = controlador->tiempos.rojo_total_ms;
            siguiente = VERDE_CARRIL_2;
            break;
        case VERDE_CARRIL_2:
            duracion_ms = controlador->verde_seleccionado_ms;
            siguiente = AMARILLO_CARRIL_2;
            break;
        case AMARILLO_CARRIL_2:
            duracion_ms = controlador->tiempos.amarillo_ms;
            siguiente = ROJO_TOTAL_2_A_1;
            break;
        case ROJO_TOTAL_2_A_1:
            duracion_ms = controlador->tiempos.rojo_total_ms;
            siguiente = VERDE_CARRIL_1;
            break;
        case ESTADO_SEGURO:
            return false;
        default:
            controlador->estado = ESTADO_SEGURO;
            controlador->inicio_ms = ahora_ms;
            return true;
    }
    if (ahora_ms < controlador->inicio_ms || !duracion_ms) {
        controlador->estado = ESTADO_SEGURO;
        controlador->inicio_ms = ahora_ms;
        return true;
    }
    bool verde = controlador->estado == VERDE_CARRIL_1 || controlador->estado == VERDE_CARRIL_2;
    if (!(controlador->seguro_solicitado && verde) &&
        ahora_ms - controlador->inicio_ms < duracion_ms) {
        return false;
    }
    if (controlador->seguro_solicitado &&
        (controlador->estado == ROJO_TOTAL_INICIAL || controlador->estado == ROJO_TOTAL_1_A_2 ||
         controlador->estado == ROJO_TOTAL_2_A_1)) {
        siguiente = ESTADO_SEGURO;
    }
    if ((siguiente == VERDE_CARRIL_1 || siguiente == VERDE_CARRIL_2) &&
        !seleccionar_verde(controlador, siguiente, ahora_ms)) {
        siguiente = ESTADO_SEGURO;
    }
    controlador->estado = siguiente;
    controlador->inicio_ms = ahora_ms;
    return true;
}

/* 3. Seguridad y recuperacion: no cancelar despejes. */
bool control_conectado_paso(control_conectado_t *guardia, controlador_semaforos_t *controlador,
                            estado_recepcion_t red, uint64_t ahora)
{
    bool vigente = red.valido && ahora < red.vence;
    if (guardia->generacion != red.generacion || !vigente) {
        if (guardia->generacion != red.generacion) {
            guardia->resultado = 0;
        }
        guardia->generacion = red.generacion;
        controlador->demanda.disponible = false;
        controlador_solicitar_seguro(controlador);
    }
    bool rearmar = controlador->estado == ESTADO_SEGURO && vigente && red.recuperable &&
                   red.atendida == red.generacion && red.resultado != guardia->resultado;
    if (rearmar) {
        tiempos_semaforo_t tiempos = controlador->tiempos;
        parametros_prioridad_t parametros = controlador->prioridad;
        uint32_t edad = controlador->max_edad_demanda_ms;
        if (!controlador_iniciar(controlador, tiempos, ahora) ||
            !controlador_configurar_adaptativo(controlador, parametros, edad)) {
            return true;
        }
        controlador->carril_inicial = guardia->ultimo_carril == 1 ? 2 : 1;
    }
    if (vigente && !controlador->seguro_solicitado && red.resultado != guardia->resultado) {
        controlador_recibir_demanda(controlador, red.demanda, ahora);
        guardia->resultado = red.resultado;
    }
    bool cambio = controlador_actualizar(controlador, ahora);
    return cambio || rearmar;
}
void control_conectado_fase_aplicada(control_conectado_t *guardia, estado_semaforo_t estado)
{
    if (estado == VERDE_CARRIL_1 || estado == VERDE_CARRIL_2) {
        guardia->ultimo_carril = estado == VERDE_CARRIL_1 ? 1 : 2;
    }
}

/* 4. Aplicacion de fases: comprobar antes y despues de GPIO. */
static bool es_verde(estado_semaforo_t estado)
{
    return estado == VERDE_CARRIL_1 || estado == VERDE_CARRIL_2;
}
static bool autorizado(control_conectado_t *guardia, operaciones_conectadas_t operaciones)
{
    estado_recepcion_t estado_red = operaciones.leer(operaciones.contexto);
    uint64_t ahora = operaciones.reloj(operaciones.contexto);
    return estado_red.valido && estado_red.generacion == guardia->generacion &&
           ahora < estado_red.vence;
}
static bool aplicar(controlador_semaforos_t *controlador, operaciones_conectadas_t operaciones)
{
    luces_semaforo_t luces;
    if (!controlador_luces(controlador->estado, &luces) ||
        !operaciones.escribir(operaciones.contexto, luces)) {
        return false;
    }
    controlador->inicio_ms = operaciones.reloj(operaciones.contexto);
    return true;
}
bool aplicacion_conectada(control_conectado_t *guardia, controlador_semaforos_t *controlador,
                          operaciones_conectadas_t operaciones, informe_aplicacion_t *informe)
{
    uint64_t inicio = operaciones.reloj(operaciones.contexto);
    *informe = (informe_aplicacion_t){0};
    if (es_verde(controlador->estado) &&
        (controlador->seguro_solicitado || !autorizado(guardia, operaciones))) {
        operaciones.invalidar(operaciones.contexto);
        controlador->estado = ESTADO_SEGURO;
        controlador_solicitar_seguro(controlador);
        informe->interrumpido = true; /* Se venia de rojo: el verde aun no fue escrito. */
    }
    if (!aplicar(controlador, operaciones)) {
        return false;
    }
    if (es_verde(controlador->estado)) {
        informe->verde_aplicado = true;
        informe->inicio_verde_ms = controlador->inicio_ms;
        informe->estado_verde = controlador->estado;
        control_conectado_fase_aplicada(guardia, controlador->estado);
        if (!autorizado(guardia, operaciones)) {
            /* Una invalidacion puede llegar dentro del driver. Ya hubo verde:
             * iniciar amarillo completo ahora, sin salto directo a ambos rojos. */
            operaciones.invalidar(operaciones.contexto);
            controlador_solicitar_seguro(controlador);
            controlador_actualizar(controlador, operaciones.reloj(operaciones.contexto));
            if (!aplicar(controlador, operaciones)) {
                return false;
            }
            informe->interrumpido = true;
        }
    }
    informe->duracion_aplicacion_ms = operaciones.reloj(operaciones.contexto) - inicio;
    return true;
}
