#include "sesion_udp.h"
#include <string.h>
#include <limits.h>
void sesion_udp_iniciar(sesion_udp_t *s,const uint8_t emisor[16],const uint8_t receptor[16])
{
    *s=(sesion_udp_t){.presupuesto_ms=12000,.local_ms=5000,.margen_ms=50,.timeout_ms=750,.comunicacion_ms=3000,
        .generacion=1,.generacion_local=1};
    memcpy(s->emisor,emisor,16);memcpy(s->receptor,receptor,16);
}
void sesion_udp_fallo(sesion_udp_t *s)
{ s->valido=false;s->vence=0;++s->generacion;++s->generacion_local; }
bool sesion_udp_vigente(const sesion_udp_t *s,uint64_t ahora)
{
    return s && s->etapa==2 && s->valido && ahora<s->vence && ahora>=s->ultima_auth &&
        ahora-s->ultima_auth<s->comunicacion_ms;
}
bool sesion_udp_solicitar(sesion_udp_t *s,uint64_t ahora,uint8_t estado,bool seguro_reconocido,mensaje_udp_t *m)
{
    if (!s || !m || s->nonce==UINT64_MAX || estado>7 ||
        (s->pendiente && (ahora<s->t0 || ahora-s->t0<=s->timeout_ms))) return false;
    *m=(mensaje_udp_t){.tipo=s->etapa==0 ? UDP_HELLO:s->etapa==1 ? UDP_CONFIRMAR:UDP_CONSULTA,
        .nonce=++s->nonce,.evento=s->generacion_local,.estado=estado,.rtt_ms=s->rtt_ms};
    memcpy(m->emisor,s->emisor,16);memcpy(m->sesion_receptor,s->receptor,16);
    if(s->etapa)memcpy(m->sesion_emisor,s->servidor,16);
    if(s->etapa==1)m->barrera=s->token;
    if(s->etapa==2 && estado==7 && seguro_reconocido) {
        m->reconocimiento=s->barrera;s->ack_enviado=s->barrera;
    }
    s->t0=ahora;s->pendiente=true;return true;
}
bool sesion_udp_responder(sesion_udp_t *s,const mensaje_udp_t *m,uint64_t ahora)
{
    if (!s || !m || !s->pendiente || ahora<s->t0 || ahora-s->t0>s->timeout_ms ||
        m->nonce!=s->nonce || memcmp(m->emisor,s->emisor,16) || memcmp(m->sesion_receptor,s->receptor,16))return false;
    if(s->etapa==0) {
        const uint8_t cero[16]={0};
        if(m->tipo!=UDP_ASOCIACION || !m->barrera || !memcmp(m->sesion_emisor,cero,16))return false;
        memcpy(s->servidor,m->sesion_emisor,16);s->token=m->barrera;s->etapa=1;
        s->evento=0;s->resultado=0;s->epoca=0;s->barrera=0;s->ack_enviado=0;s->valido=false;s->vence=0;
    } else {
        if(memcmp(m->sesion_emisor,s->servidor,16))return false;
        if(m->tipo==UDP_INVALIDACION) {
            if(!m->evento || m->evento<s->evento || m->barrera!=m->evento)return false;
            if(m->evento>s->barrera) { s->valido=false;s->vence=0;++s->generacion;s->ack_enviado=0; }
            s->barrera=m->evento;s->evento=m->evento;s->etapa=2;
        } else if(m->tipo==UDP_RESULTADO && s->etapa==2) {
            if(m->barrera!=s->barrera || s->ack_enviado!=s->barrera || m->evento<=s->evento ||
                m->resultado<=s->resultado || m->epoca<s->epoca)return false;
            uint64_t gastado=(uint64_t)m->edad_ms+s->margen_ms;
            uint64_t rtt=ahora-s->t0;
            /* No ocultar un hueco de vigencia con datos que llegan durante recv(). */
            if((s->valido && !sesion_udp_vigente(s,ahora)) ||
                gastado>=s->presupuesto_ms || rtt>=s->presupuesto_ms-gastado || !s->local_ms ||
                s->t0>UINT64_MAX-(s->presupuesto_ms-gastado) || ahora>UINT64_MAX-s->local_ms) {
                sesion_udp_fallo(s);
            } else {
                uint64_t origen=s->t0+s->presupuesto_ms-gastado,local=ahora+s->local_ms;
                s->vence=origen<local ? origen:local;s->valido=true;s->resultado=m->resultado;s->epoca=m->epoca;
                s->evento=m->evento;s->n1=m->n1;s->n2=m->n2;s->edad_ms=(uint32_t)(gastado+rtt);
            }
        } else if(m->tipo!=UDP_ESPERA || s->etapa!=2 || m->barrera!=s->barrera)return false;
    }
    s->rtt_ms=(uint32_t)(ahora-s->t0);s->ultima_auth=ahora;s->pendiente=false;return true;
}
