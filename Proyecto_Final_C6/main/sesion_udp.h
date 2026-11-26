#pragma once
#include "protocolo_udp.h"
/* Nucleo sin sockets: recibe solo mensajes ya autenticados por protocolo_decodificar.
 * Todos los instantes/plazos son milisegundos del reloj monotonic local C6.
 * etapa: 0 descubre servidor, 1 confirma desafio, 2 asociado.
 * generacion es retenida para el propietario; generacion_local notifica fallos a PC.
 */
typedef struct {
    uint8_t emisor[16],receptor[16],servidor[16];
    unsigned etapa;
    uint64_t nonce,t0,evento,resultado,epoca,barrera,token,ack_enviado;
    uint64_t generacion,generacion_local,vence,ultima_auth;
    uint32_t presupuesto_ms,local_ms,margen_ms,timeout_ms,comunicacion_ms,rtt_ms,edad_ms;
    uint16_t n1,n2;bool pendiente,valido;
} sesion_udp_t;
void sesion_udp_iniciar(sesion_udp_t *s,const uint8_t emisor[16],const uint8_t receptor[16]);
void sesion_udp_fallo(sesion_udp_t *s);
bool sesion_udp_solicitar(sesion_udp_t *s,uint64_t ahora,uint8_t estado,bool seguro_reconocido,mensaje_udp_t *m);
bool sesion_udp_responder(sesion_udp_t *s,const mensaje_udp_t *m,uint64_t ahora);
bool sesion_udp_vigente(const sesion_udp_t *s,uint64_t ahora);
