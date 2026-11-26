#include "protocolo_udp.h"
#include <string.h>
static void escribir_entero(uint8_t *p,uint64_t v,int n) { for (int i=n-1;i>=0;--i) { p[i]=(uint8_t)v;v>>=8; } }
static uint64_t leer_entero(const uint8_t *p,int n) { uint64_t v=0;for(int i=0;i<n;++i)v=(v<<8)|p[i];return v; }
static bool valido(const mensaje_udp_t *m)
{
    return m && m->tipo>=1 && m->tipo<=7 && m->motivo<=7 && m->estado<=7 && m->n1<=1000 && m->n2<=1000 &&
        m->valido==(m->tipo==UDP_RESULTADO) && (m->tipo==UDP_RESULTADO ?
            (m->resultado && m->evento && !m->motivo) : (!m->n1 && !m->n2));
}
bool protocolo_codificar(const mensaje_udp_t *m,const uint8_t clave[32],uint8_t p[UDP_TAMANO],udp_firmar_fn firmar)
{
    if (!valido(m) || !clave || !p || !firmar) return false;
    memset(p,0,UDP_TAMANO);memcpy(p,"SE07",4);p[4]=1;p[5]=m->tipo;p[6]=m->valido;p[7]=m->motivo;
    memcpy(p+8,m->emisor,16);memcpy(p+24,m->sesion_emisor,16);memcpy(p+40,m->sesion_receptor,16);
    uint64_t campos[]={m->epoca,m->resultado,m->evento,m->nonce,m->reconocimiento,m->barrera};
    for(int i=0;i<6;++i)escribir_entero(p+56+8*i,campos[i],8);
    escribir_entero(p+104,m->edad_ms,4);escribir_entero(p+108,m->n1,2);escribir_entero(p+110,m->n2,2);
    p[112]=m->estado;escribir_entero(p+116,m->rtt_ms,4);
    return firmar(clave,p,UDP_CUERPO,p+UDP_CUERPO);
}
bool protocolo_decodificar(const uint8_t *p,size_t n,const uint8_t clave[32],mensaje_udp_t *m,udp_verificar_fn verificar)
{
    if (!p || !clave || !m || n!=UDP_TAMANO || !verificar || !verificar(clave,p,UDP_CUERPO,p+UDP_CUERPO))return false;
    if (memcmp(p,"SE07",4) || p[4]!=1 || p[6]>1 || p[113] || p[114] || p[115])return false;
    mensaje_udp_t temporal={.tipo=p[5],.valido=p[6],.motivo=p[7],.estado=p[112]};
    memcpy(temporal.emisor,p+8,16);memcpy(temporal.sesion_emisor,p+24,16);memcpy(temporal.sesion_receptor,p+40,16);
    temporal.epoca=leer_entero(p+56,8);temporal.resultado=leer_entero(p+64,8);temporal.evento=leer_entero(p+72,8);
    temporal.nonce=leer_entero(p+80,8);temporal.reconocimiento=leer_entero(p+88,8);temporal.barrera=leer_entero(p+96,8);
    temporal.edad_ms=(uint32_t)leer_entero(p+104,4);temporal.n1=(uint16_t)leer_entero(p+108,2);
    temporal.n2=(uint16_t)leer_entero(p+110,2);temporal.rtt_ms=(uint32_t)leer_entero(p+116,4);
    if(!valido(&temporal))return false;
    *m=temporal;return true;
}
