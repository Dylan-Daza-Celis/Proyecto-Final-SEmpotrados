#pragma once
#include <stddef.h>
#include "demanda_vehicular.h"
#define CONTEOS_UDP_MAX_BYTES 48
typedef struct { uint64_t secuencia;uint16_t n1,n2;bool valido; } mensaje_conteos_t;
typedef struct {
    bool valido,recuperable;
    uint64_t generacion,atendida,vence,resultado,recibida_ms;
    demanda_vehicular_t demanda;
} estado_recepcion_t;
typedef struct {
    estado_recepcion_t estado;
    uint64_t ultima_secuencia,ultima_valida_ms;
    uint32_t timeout_ms;
    uint8_t fase;
    bool tiene_valida,bloqueado,conectado;
} gestor_recepcion_t;
bool conteos_decodificar(const char *datos,size_t longitud,mensaje_conteos_t *salida);
bool recepcion_iniciar(gestor_recepcion_t *g,uint32_t timeout_ms);
void recepcion_invalidar(gestor_recepcion_t *g);
void recepcion_conexion(gestor_recepcion_t *g,bool conectado);
void recepcion_caducar(gestor_recepcion_t *g,uint64_t ahora);
bool recepcion_recibir(gestor_recepcion_t *g,mensaje_conteos_t m,uint64_t ahora);
void recepcion_atender(gestor_recepcion_t *g,uint8_t fase,uint64_t generacion);
