#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include "prioridad_vehicular.h"
#include "gestor_demanda.h"
#include "controlador_semaforos.h"

static void probar_matematica(void)
{
    parametros_prioridad_t p=prioridad_parametros_iniciales();
    decision_prioridad_t a,b;
    assert(prioridad_parametros_validos(p));
    for (int n1=0;n1<=30;++n1) for (int n2=0;n2<=30;++n2) {
        assert(prioridad_calcular(p,n1,n2,&a)); assert(prioridad_calcular(p,n2,n1,&b));
        assert(a.verde_1_ms==b.verde_2_ms && a.verde_2_ms==b.verde_1_ms);
        assert(a.verde_1_ms>=5000 && a.verde_1_ms<=13000);
        assert(a.verde_2_ms>=5000 && a.verde_2_ms<=13000);
    }
    const uint32_t verdes[]={5000,5000,7000,9000,11000,13000,13000};
    for (int diferencia=0;diferencia<7;++diferencia) {
        assert(prioridad_calcular(p,diferencia,0,&a)); assert(a.verde_1_ms==verdes[diferencia]);
    }
    assert(prioridad_calcular(p,1000,0,&a) && a.verde_1_ms==13000);
    assert(!prioridad_calcular(p,INT_MAX,INT_MIN,&a));
    assert(!prioridad_calcular(p,-1,0,&a));
    p.verde_max_ms=15000; assert(!prioridad_parametros_validos(p)); /* Nominal 21 > 20 s. */
    p.verde_max_ms=9000; assert(prioridad_calcular(p,1000,0,&a) && a.verde_1_ms==9000);
    p.incremento_ms=UINT_MAX; assert(prioridad_calcular(p,1000,0,&a) && a.verde_1_ms==9000);
    p.umbral=0; assert(!prioridad_parametros_validos(p));
}

static void probar_demanda(void)
{
    gestor_demanda_t g={0};
    demanda_vehicular_t d={4,0,1,100,true};
    assert(!gestor_demanda_vigente(&g,100,5000));
    assert(gestor_demanda_recibir(&g,d,100,5000)==DEMANDA_NUEVA_VALIDA);
    d.valida=false;
    assert(gestor_demanda_recibir(&g,d,100,5000)==DEMANDA_REPETIDA_O_FUERA_ORDEN);
    assert(gestor_demanda_vigente(&g,100,5000));
    d.secuencia=2;
    assert(gestor_demanda_recibir(&g,d,100,5000)==DEMANDA_INVALIDACION_NUEVA);
    assert(!gestor_demanda_vigente(&g,100,5000));
    d.valida=true;d.secuencia=1;
    assert(gestor_demanda_recibir(&g,d,100,5000)==DEMANDA_REPETIDA_O_FUERA_ORDEN);
    assert(!gestor_demanda_vigente(&g,100,5000));
    d.secuencia=3; assert(gestor_demanda_recibir(&g,d,100,5000)==DEMANDA_NUEVA_VALIDA);
    assert(gestor_demanda_vigente(&g,5100,5000)); assert(!gestor_demanda_vigente(&g,5101,5000));
    assert(!gestor_demanda_vigente(&g,99,5000));
    d.secuencia=4;d.n1=-1;assert(gestor_demanda_recibir(&g,d,100,5000)==DEMANDA_INVALIDACION_NUEVA);
    d.secuencia=5;d.n1=0;d.recibida_ms=101;
    assert(gestor_demanda_recibir(&g,d,100,5000)==DEMANDA_INVALIDACION_NUEVA);
    d=(demanda_vehicular_t){0,0,6,100,true};
    assert(gestor_demanda_recibir(&g,d,100,5000)==DEMANDA_NUEVA_VALIDA);
    assert(gestor_demanda_vigente(&g,100,5000) && g.ultima.n1==0 && g.ultima.n2==0);
}

static void probar_controlador(void)
{
    controlador_semaforos_t c;
    parametros_prioridad_t p=prioridad_parametros_iniciales();
    assert(controlador_iniciar(&c,(tiempos_semaforo_t){5000,5000,2000,1000},0));
    assert(controlador_configurar_adaptativo(&c,p,5000));
    assert(controlador_actualizar(&c,1000) && c.estado==VERDE_CARRIL_1);
    assert(c.verde_seleccionado_ms==5000 && !c.demanda_aplicada_valida);
    demanda_vehicular_t d={0,1000,1,2000,true};
    controlador_recibir_demanda(&c,d,2000);
    assert(!controlador_actualizar(&c,5999)); assert(c.inicio_ms==1000);
    assert(controlador_actualizar(&c,6000) && c.estado==AMARILLO_CARRIL_1);
    assert(!controlador_actualizar(&c,7999)); assert(controlador_actualizar(&c,8000));
    assert(c.estado==ROJO_TOTAL_1_A_2);
    /* Datos caducados al usarlos: retorno nominal, no N1=N2=0 medidos. */
    assert(controlador_actualizar(&c,9000) && c.verde_seleccionado_ms==5000 && !c.demanda_aplicada_valida);
    d.secuencia=2;d.recibida_ms=10000;controlador_recibir_demanda(&c,d,10000);
    assert(c.verde_seleccionado_ms==5000); /* No extender el verde que ya empezó. */
    assert(controlador_actualizar(&c,14000)); assert(controlador_actualizar(&c,16000));
    d.secuencia=3;d.recibida_ms=16999;controlador_recibir_demanda(&c,d,16999);
    assert(controlador_actualizar(&c,17000) && c.estado==VERDE_CARRIL_1 && c.verde_seleccionado_ms==5000);
    assert(controlador_actualizar(&c,22000)); assert(controlador_actualizar(&c,24000));
    d.secuencia=4;d.recibida_ms=24999;controlador_recibir_demanda(&c,d,24999);
    assert(controlador_actualizar(&c,25000) && c.estado==VERDE_CARRIL_2 && c.verde_seleccionado_ms==13000);
    d.secuencia=5;d.valida=false;d.recibida_ms=26000;controlador_recibir_demanda(&c,d,26000);
    assert(c.verde_seleccionado_ms==13000 && c.inicio_ms==25000);
    assert(!controlador_actualizar(&c,37999)); assert(controlador_actualizar(&c,38000));
    assert(controlador_actualizar(&c,40000)); assert(controlador_actualizar(&c,41000));
    assert(c.estado==VERDE_CARRIL_1 && !c.demanda_aplicada_valida);
    assert(41000-22000==19000); /* Intervalo propio sin verde nominal máximo. */
    controlador_solicitar_seguro(&c);
    assert(controlador_actualizar(&c,41001) && c.estado==AMARILLO_CARRIL_1);
    assert(!controlador_actualizar(&c,43000)); assert(controlador_actualizar(&c,43001));
    assert(!controlador_actualizar(&c,44000)); assert(controlador_actualizar(&c,44001) && c.estado==ESTADO_SEGURO);
}
static void probar_sin_inanicion_nominal(void)
{
    controlador_semaforos_t c;
    assert(controlador_iniciar(&c,(tiempos_semaforo_t){5000,5000,2000,1000},0));
    assert(controlador_configurar_adaptativo(&c,prioridad_parametros_iniciales(),5000));
    uint64_t secuencia=0,fin[2]={0},maximo[2]={0};
    bool tiene_fin[2]={false,false};
    int aperturas[2]={0},ultimo_carril=-1;
    for (uint64_t ahora=0;ahora<=600000;ahora+=20) {
        if (ahora%1000==0) controlador_recibir_demanda(&c,(demanda_vehicular_t){1000,0,++secuencia,ahora,true},ahora);
        estado_semaforo_t antes=c.estado;
        uint64_t inicio=c.inicio_ms;
        if (!controlador_actualizar(&c,ahora)) continue;
        if (antes==AMARILLO_CARRIL_1 || antes==AMARILLO_CARRIL_2) assert(ahora-inicio>=2000);
        if (antes==ROJO_TOTAL_1_A_2 || antes==ROJO_TOTAL_2_A_1) assert(ahora-inicio>=1000);
        if (antes==VERDE_CARRIL_1 || antes==VERDE_CARRIL_2) {
            int carril=antes==VERDE_CARRIL_1 ? 0 : 1;
            fin[carril]=ahora;tiene_fin[carril]=true;
        }
        if (c.estado==VERDE_CARRIL_1 || c.estado==VERDE_CARRIL_2) {
            int carril=c.estado==VERDE_CARRIL_1 ? 0 : 1;
            assert(carril!=ultimo_carril);ultimo_carril=carril;++aperturas[carril];
            assert(c.verde_seleccionado_ms==(carril==0 ? 13000:5000));
            if (tiene_fin[carril]) {
                uint64_t intervalo=ahora-fin[carril];
                assert(intervalo<=19000);
                if (intervalo>maximo[carril]) maximo[carril]=intervalo;
            }
        }
    }
    assert(aperturas[0]>20 && aperturas[1]>20);
    assert(maximo[0]==11000 && maximo[1]==19000);
}
int main(void)
{
    probar_matematica();probar_demanda();probar_controlador();probar_sin_inanicion_nominal();
    puts("Correcto: prioridad simetrica, saturacion, demanda/invalidaciones, congelacion, alternancia y 19 s nominales");
    return 0;
}
