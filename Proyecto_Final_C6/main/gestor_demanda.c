#include "gestor_demanda.h"
bool gestor_demanda_vigente(const gestor_demanda_t *g, uint64_t ahora_ms, uint32_t max_edad_ms)
{
    return g && g->disponible && g->ultima.valida && max_edad_ms>0 && g->ultima.n1>=0 && g->ultima.n1<=1000 &&
        g->ultima.n2>=0 && g->ultima.n2<=1000 && g->ultima.recibida_ms<=ahora_ms &&
        ahora_ms-g->ultima.recibida_ms<=max_edad_ms;
}
resultado_demanda_t gestor_demanda_recibir(gestor_demanda_t *g, demanda_vehicular_t demanda,
                                         uint64_t ahora_ms, uint32_t max_edad_ms)
{
    if (!g || demanda.secuencia<=g->ultima_secuencia) return DEMANDA_REPETIDA_O_FUERA_ORDEN;
    g->ultima_secuencia=demanda.secuencia;
    g->ultima=demanda;
    g->disponible=true;
    if (!gestor_demanda_vigente(g,ahora_ms,max_edad_ms)) {
        g->disponible=false;
        return DEMANDA_INVALIDACION_NUEVA;
    }
    return DEMANDA_NUEVA_VALIDA;
}
