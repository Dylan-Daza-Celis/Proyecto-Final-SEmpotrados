#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include "demanda_conectada.h"
#include "control_conectado.h"
static mensaje_conteos_t mensaje(uint64_t seq,bool valido)
{ return (mensaje_conteos_t){seq,3,1,valido}; }
static void iniciar(gestor_recepcion_t *r)
{
    assert(recepcion_iniciar(r,5000));recepcion_conexion(r,true);
    recepcion_atender(r,7,r->estado.generacion);
}
static void probar_ascii(void)
{
    mensaje_conteos_t m;
    assert(conteos_decodificar("42,5,1,1",8,&m));assert(m.secuencia==42 && m.n1==5 && m.n2==1 && m.valido);
    const char *maximo="18446744073709551615,1000,1000,1";
    assert(conteos_decodificar(maximo,strlen(maximo),&m));assert(m.secuencia==UINT64_MAX);
    const char *malos[]={"","0,0,0,1","1,0,0","1,0,0,1,2","1,1001,0,1","1,-1,0,1","1,0,0,2",
        "1,0,0,1\n"," 1,0,0,1","01,0,0,1","1,00,0,1","18446744073709551616,0,0,1"};
    for(unsigned i=0;i<sizeof malos/sizeof malos[0];++i) {
        m=(mensaje_conteos_t){123,7,8,true};
        assert(!conteos_decodificar(malos[i],strlen(malos[i]),&m));assert(m.secuencia==123);
    }
    assert(!conteos_decodificar("1,0,0,1\0",8,&m));
    char grande[49];memset(grande,'1',sizeof grande);assert(!conteos_decodificar(grande,sizeof grande,&m));
}
static void probar_duplicados_y_cero(void)
{
    gestor_recepcion_t r;iniciar(&r);mensaje_conteos_t cero={10,0,0,true};
    assert(recepcion_recibir(&r,cero,100));assert(r.estado.valido && r.estado.demanda.n1==0);
    uint64_t vence=r.estado.vence;
    assert(!recepcion_recibir(&r,cero,1000));assert(r.estado.vence==vence);
    assert(!recepcion_recibir(&r,mensaje(9,true),1001));assert(r.estado.vence==vence);
    assert(recepcion_recibir(&r,mensaje(11,false),1002));assert(!r.estado.valido);
    assert(r.estado.demanda.secuencia==1); /* Invalidacion no publica una medicion0/0. */
    uint64_t gen=r.estado.generacion;
    assert(!recepcion_recibir(&r,mensaje(11,false),1003));assert(r.estado.generacion==gen);
}
static void probar_timeout_reinicio_y_wifi(void)
{
    gestor_recepcion_t r;iniciar(&r);
    assert(recepcion_recibir(&r,mensaje(100,true),100));
    assert(!recepcion_recibir(&r,mensaje(1,true),200));
    recepcion_atender(&r,1,r.estado.generacion);recepcion_caducar(&r,5100);
    assert(!r.estado.valido);uint64_t gen=r.estado.generacion;
    recepcion_caducar(&r,5200);assert(r.estado.generacion==gen);
    assert(!recepcion_recibir(&r,mensaje(1,true),5200)); /* Aun no se alcanzaron rojos. */
    recepcion_atender(&r,7,gen-1);assert(!recepcion_recibir(&r,mensaje(1,true),5201));
    recepcion_atender(&r,7,gen);assert(recepcion_recibir(&r,mensaje(1,true),5202));
    assert(r.ultima_secuencia==1 && r.estado.resultado==2 && r.estado.recuperable);
    recepcion_conexion(&r,false);assert(!r.estado.valido);
    assert(!recepcion_recibir(&r,mensaje(2,true),5203)); /* Paquete en vuelo despues de perdida Wi-Fi. */
    recepcion_conexion(&r,true);recepcion_atender(&r,7,r.estado.generacion);
    assert(recepcion_recibir(&r,mensaje(2,true),5204));assert(r.estado.valido);
    iniciar(&r);assert(!recepcion_recibir(&r,mensaje(1,true),UINT64_MAX-100));assert(r.bloqueado);
}
static void comprobar_exclusion(controlador_semaforos_t *c)
{
    luces_semaforo_t l;assert(controlador_luces(c->estado,&l));
    assert(!(l.carril_1==LUZ_VERDE && l.carril_2==LUZ_VERDE));
}
static void probar_despejes_y_recuperacion(void)
{
    for(unsigned fase=1;fase<=6;++fase) {
        gestor_recepcion_t r;iniciar(&r);assert(recepcion_recibir(&r,mensaje(1,true),0));
        controlador_semaforos_t c;control_conectado_t g={.generacion=r.estado.generacion,
            .resultado=1,.ultimo_carril=fase<4 ? 1:2};
        assert(controlador_iniciar(&c,(tiempos_semaforo_t){5000,5000,2000,1000},0));
        assert(controlador_configurar_adaptativo(&c,prioridad_parametros_iniciales(),5000));
        c.estado=(estado_semaforo_t)fase;c.verde_seleccionado_ms=5000;
        recepcion_atender(&r,(uint8_t)fase,r.estado.generacion);
        assert(recepcion_recibir(&r,mensaje(2,false),100));
        control_conectado_paso(&g,&c,r.estado,100);assert(c.seguro_solicitado);
        assert(recepcion_recibir(&r,mensaje(3,true),200));assert(!r.estado.recuperable);
        for(uint64_t ms=200;ms<=4000;ms+=20) {
            control_conectado_paso(&g,&c,r.estado,ms);comprobar_exclusion(&c);
            recepcion_atender(&r,(uint8_t)c.estado,g.generacion);
        }
        assert(c.estado==ESTADO_SEGURO); /* La observacion de200ms no habilita rearme. */
        unsigned anterior=g.ultimo_carril;
        assert(recepcion_recibir(&r,mensaje(4,true),4001));assert(r.estado.recuperable);
        control_conectado_paso(&g,&c,r.estado,4001);assert(c.estado==ROJO_TOTAL_INICIAL);
        control_conectado_paso(&g,&c,r.estado,5000);assert(c.estado==ROJO_TOTAL_INICIAL);
        control_conectado_paso(&g,&c,r.estado,5001);
        assert(c.estado==(anterior==1 ? VERDE_CARRIL_2:VERDE_CARRIL_1));comprobar_exclusion(&c);
        uint64_t gen=r.estado.generacion;
        recepcion_invalidar(&r);assert(recepcion_recibir(&r,mensaje(5,true),5002));
        assert(r.estado.generacion>gen); /* El ultimo valor valido no borra invalidacion critica. */
        control_conectado_paso(&g,&c,r.estado,5002);
        assert(c.estado==AMARILLO_CARRIL_1 || c.estado==AMARILLO_CARRIL_2);
    }
}
int main(void)
{
    probar_ascii();probar_duplicados_y_cero();probar_timeout_reinicio_y_wifi();probar_despejes_y_recuperacion();
    puts("UDP ASCII C: formato, duplicados, timeout, reinicio, Wi-Fi, 6 fases y recuperacion correctos");return 0;
}
