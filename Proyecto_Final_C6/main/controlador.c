#include "controlador.h"

/* 1. Parametros y calculo de prioridad. No accede a hardware. */
/* Matemática pura: límites derivados de parámetros, sin GPIO/FreeRTOS. */
parametros_prioridad_t prioridad_parametros_iniciales(void)
{
    return (parametros_prioridad_t){5000, 13000, 2000, 1000, 2, 2000, 20000};
}

bool prioridad_parametros_validos(parametros_prioridad_t p)
{
    uint64_t intervalo =
        (uint64_t)p.verde_max_ms + 2 * (uint64_t)p.amarillo_ms + 2 * (uint64_t)p.rojo_total_ms;
    return p.verde_min_ms >= 5000 && p.verde_max_ms >= p.verde_min_ms && p.amarillo_ms >= 2000 &&
           p.rojo_total_ms >= 1000 && p.umbral > 0 && p.incremento_ms > 0 &&
           intervalo <= p.objetivo_sin_verde_ms;
}

bool prioridad_calcular(parametros_prioridad_t p, int32_t n1, int32_t n2,
                        decision_prioridad_t *decision)
{
    if (!decision || !prioridad_parametros_validos(p) || n1 < 0 || n1 > 1000 || n2 < 0 ||
        n2 > 1000) {
        return false;
    }
    int64_t diferencia = (int64_t)n1 - n2;
    uint64_t magnitud = (uint64_t)(diferencia < 0 ? -diferencia : diferencia);
    *decision = (decision_prioridad_t){p.verde_min_ms, p.verde_min_ms, (int32_t)diferencia, 0};
    if (magnitud >= p.umbral) {
        uint64_t incremento = (magnitud - p.umbral + 1) * (uint64_t)p.incremento_ms;
        uint32_t limite = p.verde_max_ms - p.verde_min_ms;
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
bool control_conectado_paso(control_conectado_t *g, controlador_semaforos_t *c,
                            estado_recepcion_t red, uint64_t ahora)
{
    bool vigente = red.valido && ahora < red.vence;
    if (g->generacion != red.generacion || !vigente) {
        if (g->generacion != red.generacion) {
            g->resultado = 0;
        }
        g->generacion = red.generacion;
        c->demanda.disponible = false;
        controlador_solicitar_seguro(c);
    }
    bool rearmar = c->estado == ESTADO_SEGURO && vigente && red.recuperable &&
                   red.atendida == red.generacion && red.resultado != g->resultado;
    if (rearmar) {
        tiempos_semaforo_t tiempos = c->tiempos;
        parametros_prioridad_t parametros = c->prioridad;
        uint32_t edad = c->max_edad_demanda_ms;
        if (!controlador_iniciar(c, tiempos, ahora) ||
            !controlador_configurar_adaptativo(c, parametros, edad)) {
            return true;
        }
        c->carril_inicial = g->ultimo_carril == 1 ? 2 : 1;
    }
    if (vigente && !c->seguro_solicitado && red.resultado != g->resultado) {
        controlador_recibir_demanda(c, red.demanda, ahora);
        g->resultado = red.resultado;
    }
    bool cambio = controlador_actualizar(c, ahora);
    return cambio || rearmar;
}
void control_conectado_fase_aplicada(control_conectado_t *g, estado_semaforo_t estado)
{
    if (estado == VERDE_CARRIL_1 || estado == VERDE_CARRIL_2) {
        g->ultimo_carril = estado == VERDE_CARRIL_1 ? 1 : 2;
    }
}

/* 4. Aplicacion de fases: comprobar antes y despues de GPIO. */
static bool es_verde(estado_semaforo_t estado)
{
    return estado == VERDE_CARRIL_1 || estado == VERDE_CARRIL_2;
}
static bool autorizado(control_conectado_t *g, operaciones_conectadas_t op)
{
    estado_recepcion_t e = op.leer(op.contexto);
    uint64_t ahora = op.reloj(op.contexto);
    return e.valido && e.generacion == g->generacion && ahora < e.vence;
}
static bool aplicar(controlador_semaforos_t *c, operaciones_conectadas_t op)
{
    luces_semaforo_t luces;
    if (!controlador_luces(c->estado, &luces) || !op.escribir(op.contexto, luces)) {
        return false;
    }
    c->inicio_ms = op.reloj(op.contexto);
    return true;
}
bool aplicacion_conectada(control_conectado_t *g, controlador_semaforos_t *c,
                          operaciones_conectadas_t op, informe_aplicacion_t *informe)
{
    uint64_t inicio = op.reloj(op.contexto);
    *informe = (informe_aplicacion_t){0};
    if (es_verde(c->estado) && (c->seguro_solicitado || !autorizado(g, op))) {
        op.invalidar(op.contexto);
        c->estado = ESTADO_SEGURO;
        controlador_solicitar_seguro(c);
        informe->interrumpido = true; /* Se venia de rojo: el verde aun no fue escrito. */
    }
    if (!aplicar(c, op)) {
        return false;
    }
    if (es_verde(c->estado)) {
        informe->verde_aplicado = true;
        informe->inicio_verde_ms = c->inicio_ms;
        informe->estado_verde = c->estado;
        control_conectado_fase_aplicada(g, c->estado);
        if (!autorizado(g, op)) {
            /* Una invalidacion puede llegar dentro del driver. Ya hubo verde:
             * iniciar amarillo completo ahora, sin salto directo a ambos rojos. */
            op.invalidar(op.contexto);
            controlador_solicitar_seguro(c);
            controlador_actualizar(c, op.reloj(op.contexto));
            if (!aplicar(c, op)) {
                return false;
            }
            informe->interrumpido = true;
        }
    }
    informe->duracion_aplicacion_ms = op.reloj(op.contexto) - inicio;
    return true;
}
