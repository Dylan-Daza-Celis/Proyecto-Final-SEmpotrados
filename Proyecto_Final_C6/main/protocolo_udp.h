#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define UDP_CUERPO 120
#define UDP_TAMANO 152
enum { UDP_HELLO=1,UDP_ASOCIACION,UDP_CONFIRMAR,UDP_CONSULTA,UDP_RESULTADO,UDP_INVALIDACION,UDP_ESPERA };
enum { UDP_SIN_DATOS=1,UDP_CAMARA,UDP_INFERENCIA,UDP_PAUSA,UDP_CONTEXTO,UDP_EDAD,UDP_COMUNICACION };
typedef struct {
    uint8_t tipo,motivo,estado; bool valido;
    uint8_t emisor[16],sesion_emisor[16],sesion_receptor[16];
    uint64_t epoca,resultado,evento,nonce,reconocimiento,barrera;
    uint32_t edad_ms,rtt_ms; uint16_t n1,n2;
} mensaje_udp_t;
typedef bool (*udp_firmar_fn)(const uint8_t clave[32],const uint8_t *datos,size_t longitud,uint8_t tag[32]);
typedef bool (*udp_verificar_fn)(const uint8_t clave[32],const uint8_t *datos,size_t longitud,const uint8_t tag[32]);
bool protocolo_codificar(const mensaje_udp_t *m,const uint8_t clave[32],uint8_t salida[UDP_TAMANO],udp_firmar_fn firmar);
bool protocolo_decodificar(const uint8_t *datos,size_t longitud,const uint8_t clave[32],mensaje_udp_t *m,udp_verificar_fn verificar);
bool udp_firmar_psa(const uint8_t clave[32],const uint8_t *datos,size_t n,uint8_t tag[32]);
bool udp_verificar_psa(const uint8_t clave[32],const uint8_t *datos,size_t n,const uint8_t tag[32]);
