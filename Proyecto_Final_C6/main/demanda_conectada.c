/* ASCII estricto y estado puro: probado sin Wi-Fi ni placa. */
#include "demanda_conectada.h"
#include <limits.h>
bool conteos_decodificar(const char *datos,size_t longitud,mensaje_conteos_t *salida)
{
    if(!datos || !salida || longitud<7 || longitud>CONTEOS_UDP_MAX_BYTES)return false;
    uint64_t campos[4]={0};unsigned campo=0,digitos=0;bool empieza_cero=false;
    for(size_t i=0;i<longitud;++i) {
        unsigned char c=(unsigned char)datos[i];
        if(c==',') {
            if(!digitos || campo==3)return false;
            ++campo;digitos=0;empieza_cero=false;continue;
        }
        if(c<'0' || c>'9' || (digitos && empieza_cero))return false;
        unsigned d=c-'0';uint64_t limite=campo==0 ? UINT64_MAX:campo==3 ? 1:1000;
        if(campos[campo]>limite/10 || (campos[campo]==limite/10 && d>limite%10))return false;
        campos[campo]=campos[campo]*10+d;
        if(!digitos)empieza_cero=c=='0';
        ++digitos;
    }
    if(campo!=3 || !digitos || !campos[0])return false;
    *salida=(mensaje_conteos_t){campos[0],(uint16_t)campos[1],(uint16_t)campos[2],campos[3]==1};
    return true;
}
bool recepcion_iniciar(gestor_recepcion_t *g,uint32_t timeout_ms)
{
    if(!g || timeout_ms<100 || timeout_ms>60000)return false;
    *g=(gestor_recepcion_t){.estado={.generacion=1},.timeout_ms=timeout_ms,.fase=7};return true;
}
void recepcion_invalidar(gestor_recepcion_t *g)
{
    if(g->estado.generacion==UINT64_MAX)g->bloqueado=true;
    else ++g->estado.generacion;
    g->estado.valido=false;g->estado.recuperable=false;g->estado.vence=0;
}
void recepcion_caducar(gestor_recepcion_t *g,uint64_t ahora)
{
    if(g->estado.valido && (ahora<g->estado.recibida_ms || ahora>=g->estado.vence))recepcion_invalidar(g);
}
void recepcion_conexion(gestor_recepcion_t *g,bool conectado)
{
    g->conectado=conectado;
    if(!conectado)recepcion_invalidar(g);
}
void recepcion_atender(gestor_recepcion_t *g,uint8_t fase,uint64_t generacion)
{
    g->fase=fase;
    if(fase==7 && generacion==g->estado.generacion)g->estado.atendida=generacion;
}
bool recepcion_recibir(gestor_recepcion_t *g,mensaje_conteos_t m,uint64_t ahora)
{
    recepcion_caducar(g,ahora);
    if(!g->conectado || g->bloqueado || !m.secuencia || m.n1>1000 || m.n2>1000)return false;
    if(m.secuencia<=g->ultima_secuencia) {
        bool anterior_caduco=!g->tiene_valida || (ahora>=g->ultima_valida_ms && ahora-g->ultima_valida_ms>=g->timeout_ms);
        /* Reinicio sencillo: solo demanda caducada, rojos atendidos y nuevo valido. */
        if(!m.valido || !anterior_caduco || g->fase!=7 || g->estado.atendida!=g->estado.generacion)return false;
        g->ultima_secuencia=0;
    }
    g->ultima_secuencia=m.secuencia;
    if(!m.valido) { recepcion_invalidar(g);return true; }
    if(ahora>UINT64_MAX-g->timeout_ms || g->estado.resultado==UINT64_MAX) {
        recepcion_invalidar(g);g->bloqueado=true;return false;
    }
    g->tiene_valida=true;g->ultima_valida_ms=ahora;
    g->estado.valido=true;g->estado.recibida_ms=ahora;g->estado.vence=ahora+g->timeout_ms;
    g->estado.recuperable=g->fase==7 && g->estado.atendida==g->estado.generacion;
    ++g->estado.resultado; /* Identidad local creciente, incluso al reiniciar Python. */
    g->estado.demanda=(demanda_vehicular_t){m.n1,m.n2,g->estado.resultado,ahora,true};return true;
}
