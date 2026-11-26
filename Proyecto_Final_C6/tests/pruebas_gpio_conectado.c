/* Intercalados deterministas en el driver real con GPIO inyectado, sin placa. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "controlador.h"
#include "semaforo_gpio.h"
static gestor_recepcion_t r;
static semaforo_gpio_t gpio;
static uint64_t ahora;
static int niveles[24],escrituras,lecturas,fallo_escritura,fallo_lectura;
static bool activo,abrio,falla_hardware;
static int escribir(int pin,int nivel)
{
    niveles[pin]=nivel;assert(!(niveles[PIN_VERDE_1] && niveles[PIN_VERDE_2]));
    abrio|=niveles[PIN_VERDE_1] || niveles[PIN_VERDE_2];++ahora;
    if(activo && ++escrituras==fallo_escritura)recepcion_invalidar(&r);
    return activo && falla_hardware && escrituras==1 ? -1:0;
}
static int habilitar(uint64_t mascara) { (void)mascara;return 0; }
static bool valida(int pin) { return pin>=0 && pin<24; }
static estado_recepcion_t leer(void *ctx)
{
    (void)ctx;estado_recepcion_t copia=r.estado;
    if(++lecturas==fallo_lectura)recepcion_invalidar(&r);
    return copia;
}
static uint64_t reloj(void *ctx) { (void)ctx;return ahora; }
static void invalidar(void *ctx) { (void)ctx;recepcion_invalidar(&r); }
static bool aplicar(void *ctx,luces_semaforo_t luces)
{ (void)ctx;return semaforo_gpio_aplicar(&gpio,luces); }
int main(void)
{
    for(int punto=0;punto<6;++punto) {
        ahora=1000;escrituras=lecturas=0;fallo_escritura=fallo_lectura=0;activo=abrio=falla_hardware=false;
        memset(niveles,0,sizeof niveles);
        assert(semaforo_gpio_iniciar(&gpio,(operaciones_gpio_t){escribir,habilitar,valida}));
        assert(recepcion_iniciar(&r,5000));recepcion_conexion(&r,true);
        recepcion_atender(&r,7,r.estado.generacion);
        assert(recepcion_recibir(&r,(mensaje_conteos_t){1,5,1,true},ahora));
        control_conectado_t g={.generacion=r.estado.generacion};controlador_semaforos_t c;
        assert(controlador_iniciar(&c,(tiempos_semaforo_t){5000,5000,2000,1000},ahora-1000));
        assert(controlador_configurar_adaptativo(&c,prioridad_parametros_iniciales(),5000));
        control_conectado_paso(&g,&c,r.estado,ahora);assert(c.estado==VERDE_CARRIL_1);
        activo=true;
        if(punto==0)recepcion_invalidar(&r); /* Despues de seleccionar y antes de aplicar. */
        if(punto==1)fallo_lectura=1; /* Justo despues de copiar el chequeo previo. */
        if(punto==2)fallo_escritura=1;
        if(punto==3)fallo_escritura=2;
        if(punto==4)r.estado.vence=ahora+1;
        if(punto==5)falla_hardware=true;
        informe_aplicacion_t informe;
        bool correcto=aplicacion_conectada(&g,&c,(operaciones_conectadas_t){NULL,leer,reloj,invalidar,aplicar},&informe);
        if(punto==5) {
            assert(!correcto && gpio.bloqueado);falla_hardware=false;
            assert(!semaforo_gpio_aplicar(&gpio,(luces_semaforo_t){LUZ_VERDE,LUZ_ROJA}));continue;
        }
        assert(correcto && informe.interrumpido);
        if(punto==0)assert(!abrio && c.estado==ESTADO_SEGURO);
        else {
            assert(abrio && c.estado==AMARILLO_CARRIL_1);uint64_t inicio=c.inicio_ms;
            controlador_actualizar(&c,inicio+1999);assert(c.estado==AMARILLO_CARRIL_1);
            controlador_actualizar(&c,inicio+2000);assert(c.estado==ROJO_TOTAL_1_A_2);
            controlador_actualizar(&c,inicio+2999);assert(c.estado==ROJO_TOTAL_1_A_2);
            controlador_actualizar(&c,inicio+3000);assert(c.estado==ESTADO_SEGURO);
        }
    }
    puts("GPIO conectado: invalidacion antes/durante driver, caducidad, despejes y bloqueo hardware correctos");return 0;
}
