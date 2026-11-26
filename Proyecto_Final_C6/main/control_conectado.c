#include "control_conectado.h"
bool control_conectado_paso(control_conectado_t *g,controlador_semaforos_t *c,estado_recepcion_t red,uint64_t ahora)
{
    bool vigente=red.valido && ahora<red.vence;
    if(g->generacion!=red.generacion || !vigente) {
        if(g->generacion!=red.generacion)g->resultado=0;
        g->generacion=red.generacion;
        c->demanda.disponible=false;controlador_solicitar_seguro(c);
    }
    bool rearmar=c->estado==ESTADO_SEGURO && vigente && red.recuperable && red.atendida==red.generacion && red.resultado!=g->resultado;
    if(rearmar) {
        tiempos_semaforo_t tiempos=c->tiempos;parametros_prioridad_t parametros=c->prioridad;
        uint32_t edad=c->max_edad_demanda_ms;
        if(!controlador_iniciar(c,tiempos,ahora) || !controlador_configurar_adaptativo(c,parametros,edad))return true;
        c->carril_inicial=g->ultimo_carril==1 ? 2:1;
    }
    if(vigente && !c->seguro_solicitado && red.resultado!=g->resultado) {
        controlador_recibir_demanda(c,red.demanda,ahora);g->resultado=red.resultado;
    }
    bool cambio=controlador_actualizar(c,ahora);
    return cambio || rearmar;
}
void control_conectado_fase_aplicada(control_conectado_t *g,estado_semaforo_t estado)
{
    if(estado==VERDE_CARRIL_1 || estado==VERDE_CARRIL_2)
        g->ultimo_carril=estado==VERDE_CARRIL_1 ? 1:2;
}
