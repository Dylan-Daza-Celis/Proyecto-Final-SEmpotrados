/* Matemática pura: límites derivados de parámetros, sin GPIO/FreeRTOS. */
#include "prioridad_vehicular.h"
parametros_prioridad_t prioridad_parametros_iniciales(void)
{ return (parametros_prioridad_t){5000,13000,2000,1000,2,2000,20000}; }

bool prioridad_parametros_validos(parametros_prioridad_t p)
{
    uint64_t intervalo=(uint64_t)p.verde_max_ms+2*(uint64_t)p.amarillo_ms+2*(uint64_t)p.rojo_total_ms;
    return p.verde_min_ms>=5000 && p.verde_max_ms>=p.verde_min_ms && p.amarillo_ms>=2000 &&
        p.rojo_total_ms>=1000 && p.umbral>0 && p.incremento_ms>0 && intervalo<=p.objetivo_sin_verde_ms;
}

bool prioridad_calcular(parametros_prioridad_t p, int32_t n1, int32_t n2, decision_prioridad_t *decision)
{
    if (!decision || !prioridad_parametros_validos(p) || n1<0 || n1>1000 || n2<0 || n2>1000) return false;
    int64_t diferencia=(int64_t)n1-n2;
    uint64_t magnitud=(uint64_t)(diferencia<0 ? -diferencia : diferencia);
    *decision=(decision_prioridad_t){p.verde_min_ms,p.verde_min_ms,(int32_t)diferencia,0};
    if (magnitud>=p.umbral) {
        uint64_t incremento=(magnitud-p.umbral+1)*(uint64_t)p.incremento_ms;
        uint32_t limite=p.verde_max_ms-p.verde_min_ms;
        if (incremento>limite) incremento=limite;
        decision->carril_favorecido=diferencia>0 ? 1 : 2;
        if (diferencia>0) decision->verde_1_ms+=(uint32_t)incremento;
        else decision->verde_2_ms+=(uint32_t)incremento;
    }
    return true;
}
