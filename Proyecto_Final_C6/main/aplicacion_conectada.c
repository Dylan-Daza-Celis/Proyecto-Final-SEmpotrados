#include "aplicacion_conectada.h"
static bool es_verde(estado_semaforo_t estado)
{ return estado==VERDE_CARRIL_1 || estado==VERDE_CARRIL_2; }
static bool autorizado(control_conectado_t *g,operaciones_conectadas_t op)
{
    estado_recepcion_t e=op.leer(op.contexto);uint64_t ahora=op.reloj(op.contexto);
    return e.valido && e.generacion==g->generacion && ahora<e.vence;
}
static bool aplicar(controlador_semaforos_t *c,operaciones_conectadas_t op)
{
    luces_semaforo_t luces;
    if(!controlador_luces(c->estado,&luces) || !op.escribir(op.contexto,luces))return false;
    c->inicio_ms=op.reloj(op.contexto);return true;
}
bool aplicacion_conectada(control_conectado_t *g,controlador_semaforos_t *c,
    operaciones_conectadas_t op,informe_aplicacion_t *informe)
{
    uint64_t inicio=op.reloj(op.contexto);*informe=(informe_aplicacion_t){0};
    if(es_verde(c->estado) && (c->seguro_solicitado || !autorizado(g,op))) {
        op.invalidar(op.contexto);c->estado=ESTADO_SEGURO;controlador_solicitar_seguro(c);
        informe->interrumpido=true; /* Se venia de rojo: el verde aun no fue escrito. */
    }
    if(!aplicar(c,op))return false;
    if(es_verde(c->estado)) {
        informe->verde_aplicado=true;informe->inicio_verde_ms=c->inicio_ms;
        informe->estado_verde=c->estado;
        control_conectado_fase_aplicada(g,c->estado);
        if(!autorizado(g,op)) {
            /* Una invalidacion puede llegar dentro del driver. Ya hubo verde:
             * iniciar amarillo completo ahora, sin salto directo a ambos rojos. */
            op.invalidar(op.contexto);controlador_solicitar_seguro(c);
            controlador_actualizar(c,op.reloj(op.contexto));
            if(!aplicar(c,op))return false;
            informe->interrumpido=true;
        }
    }
    informe->duracion_aplicacion_ms=op.reloj(op.contexto)-inicio;
    return true;
}
