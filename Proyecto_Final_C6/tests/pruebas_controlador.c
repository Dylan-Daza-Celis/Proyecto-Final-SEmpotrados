/* Ejecutable anfitrión C99. Usa las mismas fuentes que el firmware, con GPIO simulado. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "controlador_semaforos.h"
#include "semaforo_gpio.h"
#include "semaforo_pinout.h"
#include "demanda_vehicular.h"

static int niveles[24], llamadas, fallar_en, habilitado, habilitar_falla;
static bool valida(int pin) { return pin>=0 && pin<24; }
static int escribir(int pin, int nivel)
{
    if (++llamadas==fallar_en) return -1;
    niveles[pin]=nivel;
    assert(!(niveles[PIN_VERDE_1] && niveles[PIN_VERDE_2]));
    assert(niveles[PIN_ROJO_1]+niveles[PIN_AMARILLO_1]+niveles[PIN_VERDE_1]<=1);
    assert(niveles[PIN_ROJO_2]+niveles[PIN_AMARILLO_2]+niveles[PIN_VERDE_2]<=1);
    if (habilitado) {
        if (niveles[PIN_VERDE_1]) assert(niveles[PIN_ROJO_2]);
        if (niveles[PIN_VERDE_2]) assert(niveles[PIN_ROJO_1]);
    }
    return 0;
}
static int habilitar(uint64_t mascara)
{
    assert(mascara!=0);
    assert(niveles[PIN_ROJO_1] && niveles[PIN_ROJO_2]);
    assert(!niveles[PIN_VERDE_1] && !niveles[PIN_VERDE_2]);
    habilitado=1; return habilitar_falla;
}
static void comprobar_rojos(void)
{
    assert(niveles[PIN_ROJO_1] && niveles[PIN_ROJO_2]);
    assert(!niveles[PIN_VERDE_1] && !niveles[PIN_VERDE_2]);
    assert(!niveles[PIN_AMARILLO_1] && !niveles[PIN_AMARILLO_2]);
}
static void pruebas_secuencia(void)
{
    controlador_semaforos_t c;
    tiempos_semaforo_t t={5000,5000,2000,1000};
    assert(controlador_iniciar(&c,t,0));
    assert(c.estado==ROJO_TOTAL_INICIAL);
    luces_semaforo_t luces;
    assert(controlador_luces(c.estado,&luces));
    assert(luces.carril_1==LUZ_ROJA && luces.carril_2==LUZ_ROJA);
    const estado_semaforo_t esperados[]={VERDE_CARRIL_1,AMARILLO_CARRIL_1,ROJO_TOTAL_1_A_2,
        VERDE_CARRIL_2,AMARILLO_CARRIL_2,ROJO_TOTAL_2_A_1,VERDE_CARRIL_1};
    const int duraciones[]={1000,5000,2000,1000,5000,2000,1000};
    uint64_t ahora=0;
    for (int i=0; i<7; ++i) {
        ahora+=duraciones[i];
        assert(!controlador_actualizar(&c,ahora-1));
        assert(controlador_actualizar(&c,ahora));
        assert(c.estado==esperados[i]);
        assert(controlador_luces(c.estado,&luces));
        assert(luces.carril_1==LUZ_ROJA || luces.carril_2==LUZ_ROJA);
    }
    /* Retraso grande: avanza una fase, sin saltar amarillo/rojo. */
    assert(controlador_actualizar(&c,ahora+60000));
    assert(c.estado==AMARILLO_CARRIL_1);
    assert(!controlador_actualizar(&c,ahora+61999));
    assert(controlador_actualizar(&c,ahora+62000));
    assert(c.estado==ROJO_TOTAL_1_A_2);
    assert(!controlador_actualizar(&c,ahora+62999));
    assert(controlador_actualizar(&c,ahora+63000));
    assert(c.estado==VERDE_CARRIL_2);
    controlador_solicitar_seguro(&c);
    assert(controlador_actualizar(&c,ahora+63001));
    assert(c.estado==AMARILLO_CARRIL_2);
    assert(!controlador_actualizar(&c,ahora+65000));
    assert(controlador_actualizar(&c,ahora+65001));
    assert(c.estado==ROJO_TOTAL_2_A_1);
    assert(!controlador_actualizar(&c,ahora+66000));
    assert(controlador_actualizar(&c,ahora+66001));
    assert(c.estado==ESTADO_SEGURO);
    assert(!controlador_actualizar(&c,ahora+99999));
    c.estado=(estado_semaforo_t)999;
    assert(controlador_actualizar(&c,1) && c.estado==ESTADO_SEGURO);
    assert(!controlador_luces((estado_semaforo_t)-1,&luces));
    assert(!controlador_iniciar(&c,(tiempos_semaforo_t){0,5,2,1},0));
    assert(controlador_iniciar(&c,t,50));
    assert(controlador_actualizar(&c,49) && c.estado==ESTADO_SEGURO);
}
static void pruebas_gpio(void)
{
    operaciones_gpio_t op={escribir,habilitar,valida};
    semaforo_gpio_t g;
    assert(semaforo_gpio_iniciar(&g,op));
    assert(habilitado); comprobar_rojos();
    for (int estado=0; estado<=ESTADO_SEGURO; ++estado) {
        luces_semaforo_t luces;
        assert(controlador_luces((estado_semaforo_t)estado,&luces));
        assert(semaforo_gpio_aplicar(&g,luces));
        assert(niveles[PIN_ROJO_1]+niveles[PIN_AMARILLO_1]+niveles[PIN_VERDE_1]==1);
        assert(niveles[PIN_ROJO_2]+niveles[PIN_AMARILLO_2]+niveles[PIN_VERDE_2]==1);
    }
    assert(!semaforo_gpio_aplicar(&g,(luces_semaforo_t){LUZ_VERDE,LUZ_VERDE}));
    comprobar_rojos(); assert(g.bloqueado);
    assert(!semaforo_gpio_aplicar(&g,(luces_semaforo_t){LUZ_VERDE,LUZ_ROJA}));
    /* Fallar cada escritura de inicialización y aplicación, de una en una. */
    for (int fallo=1; fallo<=6; ++fallo) {
        llamadas=0; fallar_en=fallo; memset(niveles,0,sizeof niveles);
        assert(!semaforo_gpio_iniciar(&g,op));
        assert(g.bloqueado); comprobar_rojos();
    }
    fallar_en=0;
    for (int fallo=1; fallo<=2; ++fallo) {
        llamadas=0; assert(semaforo_gpio_iniciar(&g,op));
        fallar_en=llamadas+fallo;
        assert(!semaforo_gpio_aplicar(&g,(luces_semaforo_t){LUZ_VERDE,LUZ_ROJA}));
        comprobar_rojos(); fallar_en=0;
    }
    habilitar_falla=-1; assert(!semaforo_gpio_iniciar(&g,op)); comprobar_rojos();
    habilitar_falla=0;
    for (int desde=0; desde<=ESTADO_SEGURO; ++desde) for (int hasta=0; hasta<=ESTADO_SEGURO; ++hasta) {
        luces_semaforo_t origen,destino;
        controlador_luces((estado_semaforo_t)desde,&origen);
        controlador_luces((estado_semaforo_t)hasta,&destino);
        assert(semaforo_gpio_iniciar(&g,op)); assert(semaforo_gpio_aplicar(&g,origen));
        int inicio=llamadas;
        assert(semaforo_gpio_aplicar(&g,destino));
        int numero_escrituras=llamadas-inicio;
        for (int fallo=1; fallo<=numero_escrituras; ++fallo) {
            assert(semaforo_gpio_iniciar(&g,op)); assert(semaforo_gpio_aplicar(&g,origen));
            fallar_en=llamadas+fallo;
            assert(!semaforo_gpio_aplicar(&g,destino)); comprobar_rojos();
            fallar_en=0;
        }
    }
    int pines[]={2,3,10,11,18,19};
    assert(semaforo_pines_validos(pines,valida));
    const int prohibidos[]={2,4,5,8,9,12,13,15,16,17,24,-1};
    for (unsigned i=0; i<sizeof prohibidos/sizeof prohibidos[0]; ++i) {
        pines[5]=prohibidos[i]; assert(!semaforo_pines_validos(pines,valida));
    }
}
static void pruebas_demanda(void)
{
    demanda_vehicular_t d={3,1,1,100,true};
    assert(demanda_validar(d,100,0));
    assert(!demanda_validar(d,100,1));
    assert(!demanda_validar(d,99,0));
    assert(!demanda_validar(d,5101,0));
    d.n1=-1; assert(!demanda_validar(d,100,0));
    d.n1=1001; assert(!demanda_validar(d,100,0));
    d.n1=0; d.n2=-1; assert(!demanda_validar(d,100,0));
    d.n2=0; d.valida=false; assert(!demanda_validar(d,100,0));
}
int main(void)
{
    pruebas_secuencia(); pruebas_gpio(); pruebas_demanda();
    puts("Correcto: secuencia/tiempos, retrasos, seguro, GPIO, fallos y demanda");
    return 0;
}
