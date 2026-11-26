#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include "sesion_udp.h"
#include "control_conectado.h"

static sesion_udp_t s;
static uint64_t reloj;
static mensaje_udp_t respuesta(uint8_t tipo)
{
    mensaje_udp_t q,m;
    assert(sesion_udp_solicitar(&s,reloj,7,true,&q));
    m=(mensaje_udp_t){.tipo=tipo,.nonce=q.nonce,.barrera=s.barrera};
    memcpy(m.emisor,s.emisor,16);memcpy(m.sesion_receptor,s.receptor,16);
    memcpy(m.sesion_emisor,s.servidor,16);
    return m;
}
static void asociar(void)
{
    uint8_t e[16]={1},r[16]={2};sesion_udp_iniciar(&s,e,r);reloj=1000;
    mensaje_udp_t m=respuesta(UDP_ASOCIACION);m.sesion_emisor[0]=3;m.barrera=40;
    assert(sesion_udp_responder(&s,&m,reloj+10));assert(s.etapa==1);
    reloj+=1000;m=respuesta(UDP_INVALIDACION);m.evento=m.barrera=1;
    assert(sesion_udp_responder(&s,&m,reloj+10));assert(!s.valido && s.etapa==2);
    reloj+=1000;m=respuesta(UDP_ESPERA);
    assert(sesion_udp_responder(&s,&m,reloj+10));assert(s.ack_enviado==1);
}
static mensaje_udp_t resultado(void)
{
    reloj+=1000;mensaje_udp_t m=respuesta(UDP_RESULTADO);
    m.valido=true;m.resultado=1;m.evento=2;m.epoca=1;m.edad_ms=1000;return m;
}
static void probar_nonces_sesiones(void)
{
    asociar();mensaje_udp_t m=resultado();sesion_udp_t copia=s;
    m.nonce++;assert(!sesion_udp_responder(&s,&m,reloj+10));assert(!memcmp(&s,&copia,sizeof s));m.nonce--;
    m.sesion_emisor[0]++;assert(!sesion_udp_responder(&s,&m,reloj+10));m.sesion_emisor[0]--;
    m.sesion_receptor[0]++;assert(!sesion_udp_responder(&s,&m,reloj+10));m.sesion_receptor[0]--;
    assert(!sesion_udp_responder(&s,&m,reloj+751));assert(!sesion_udp_responder(&s,&m,reloj-1));
    assert(sesion_udp_responder(&s,&m,reloj+50));assert(sesion_udp_vigente(&s,reloj+50));
    assert(s.n1==0 && s.n2==0); /* Cero valido, diferente de ausencia. */
    assert(s.edad_ms==1100 && s.vence==reloj+50+5000);
    assert(!sesion_udp_responder(&s,&m,reloj+51)); /* Un nonce, una respuesta. */
    uint64_t vence=s.vence;reloj+=1000;m=respuesta(UDP_ESPERA);
    assert(sesion_udp_responder(&s,&m,reloj+10));assert(s.vence==vence);
    reloj+=1000;m=respuesta(UDP_RESULTADO);m.valido=true;m.resultado=1;m.evento=3;m.epoca=1;
    copia=s;assert(!sesion_udp_responder(&s,&m,reloj+10));assert(!memcmp(&s,&copia,sizeof s));
    assert(!sesion_udp_vigente(&s,vence));
    assert(!sesion_udp_vigente(&s,s.ultima_auth+3000)); /* Perdida de paquetes sin renovar TTL. */
}
static void probar_edad_desbordamientos(void)
{
    asociar();mensaje_udp_t m=resultado();m.edad_ms=11000;
    assert(sesion_udp_responder(&s,&m,reloj+200));assert(s.vence==reloj+950 && s.edad_ms==11250);
    assert(sesion_udp_vigente(&s,reloj+949));assert(!sesion_udp_vigente(&s,reloj+950));
    reloj+=1000;m=respuesta(UDP_RESULTADO);m.valido=true;m.resultado=2;m.evento=3;m.epoca=1;
    assert(sesion_udp_responder(&s,&m,reloj+10));assert(!s.valido && s.generacion_local==2);
    asociar();m=resultado();m.edad_ms=11900;
    assert(sesion_udp_responder(&s,&m,reloj+50));assert(!s.valido); /* Igual al vencimiento. */
    asociar();m=resultado();m.edad_ms=UINT32_MAX;
    assert(sesion_udp_responder(&s,&m,reloj+10));assert(!s.valido);
    asociar();reloj=UINT64_MAX-2000;m=resultado(); /* No permitir overflow del vencimiento. */
    assert(sesion_udp_responder(&s,&m,reloj+10));assert(!s.valido);
    asociar();s.nonce=UINT64_MAX;mensaje_udp_t q;
    assert(!sesion_udp_solicitar(&s,reloj+1000,7,true,&q));
}
static void probar_barreras_y_reinicio(void)
{
    asociar();mensaje_udp_t m=resultado();assert(sesion_udp_responder(&s,&m,reloj+10));
    uint64_t generacion=s.generacion;reloj+=1000;m=respuesta(UDP_INVALIDACION);m.evento=m.barrera=3;
    assert(sesion_udp_responder(&s,&m,reloj+10));assert(s.generacion==generacion+1 && !s.valido);
    reloj+=1000;m=respuesta(UDP_INVALIDACION);m.evento=m.barrera=3;
    assert(sesion_udp_responder(&s,&m,reloj+10));assert(s.generacion==generacion+1);
    s.ack_enviado=0;reloj+=1000;m=respuesta(UDP_RESULTADO);s.ack_enviado=0;
    m.resultado=2;m.evento=4;m.epoca=1;
    assert(!sesion_udp_responder(&s,&m,reloj+10));
    sesion_udp_fallo(&s);assert(!s.valido && s.generacion_local==2); /* Wi-Fi/perdida local. */
    s.etapa=0;memset(s.servidor,0,16);s.receptor[0]++;
    reloj+=1000;m=respuesta(UDP_ASOCIACION);m.sesion_emisor[0]=4;m.barrera=99;
    assert(sesion_udp_responder(&s,&m,reloj+10));assert(s.resultado==0 && s.evento==0 && s.ack_enviado==0);
}
static void comprobar_exclusion(controlador_semaforos_t *c)
{
    luces_semaforo_t luces;assert(controlador_luces(c->estado,&luces));
    assert(!(luces.carril_1==LUZ_VERDE && luces.carril_2==LUZ_VERDE));
}
static void probar_seguridad_recuperacion(void)
{
    for(int fase=VERDE_CARRIL_1;fase<=ROJO_TOTAL_2_A_1;++fase) {
        controlador_semaforos_t c;control_conectado_t g={.generacion=1,.resultado=1,.ultimo_carril=1};
        tiempos_semaforo_t t={5000,5000,2000,1000};assert(controlador_iniciar(&c,t,0));
        assert(controlador_configurar_adaptativo(&c,prioridad_parametros_iniciales(),5000));
        c.estado=(estado_semaforo_t)fase;c.verde_seleccionado_ms=5000;c.inicio_ms=0;
        estado_red_t red={.generacion=2,.asociado=true};
        control_conectado_paso(&g,&c,red,100);assert(c.seguro_solicitado);
        if(fase==VERDE_CARRIL_1 || fase==VERDE_CARRIL_2)
            assert(c.estado==AMARILLO_CARRIL_1 || c.estado==AMARILLO_CARRIL_2);
        /* Un resultado nuevo no cancela despeje, aunque sobrescriba el buzon ordinario. */
        red.valido=true;red.reconocida=1;red.vence=20000;red.resultado=2;
        red.demanda=(demanda_vehicular_t){8,0,2,100,true};
        for(uint64_t ms=120;ms<=4000;ms+=20) {
            control_conectado_paso(&g,&c,red,ms);comprobar_exclusion(&c);
        }
        assert(c.estado==ESTADO_SEGURO);
        red.reconocida=2;red.resultado=3;red.demanda=(demanda_vehicular_t){0,0,3,4001,true};
        assert(control_conectado_paso(&g,&c,red,4001));assert(c.estado==ROJO_TOTAL_INICIAL);
        control_conectado_paso(&g,&c,red,5000);assert(c.estado==ROJO_TOTAL_INICIAL);
        control_conectado_paso(&g,&c,red,5001);assert(c.estado==VERDE_CARRIL_2);comprobar_exclusion(&c);
        assert(g.ultimo_carril==1); /* Una propuesta abortada antes del GPIO no cuenta como verde. */
        control_conectado_fase_aplicada(&g,c.estado);assert(g.ultimo_carril==2);
        assert(c.verde_seleccionado_ms==5000);
        red.vence=5020;control_conectado_paso(&g,&c,red,5020);assert(c.estado==AMARILLO_CARRIL_2);
        control_conectado_paso(&g,&c,red,7019);assert(c.estado==AMARILLO_CARRIL_2);
        control_conectado_paso(&g,&c,red,7020);assert(c.estado==ROJO_TOTAL_2_A_1);
        control_conectado_paso(&g,&c,red,8020);assert(c.estado==ESTADO_SEGURO);
        /* Reinicio de emisor: resultado numerico igual, generacion diferente. */
        red.generacion=3;red.reconocida=3;red.resultado=3;red.vence=20000;
        red.demanda.recibida_ms=8021;
        control_conectado_paso(&g,&c,red,8021);assert(c.estado==ROJO_TOTAL_INICIAL);
    }
}
int main(void)
{
    probar_nonces_sesiones();probar_edad_desbordamientos();probar_barreras_y_reinicio();
    probar_seguridad_recuperacion();puts("UDP C: 4 grupos correctos (sesiones, plazos, barreras y 6 fases de seguridad)");return 0;
}
