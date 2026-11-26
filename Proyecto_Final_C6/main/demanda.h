#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

/* Tipos compartidos sin depender de controlador.h ni de ESP-IDF.
 * Los instantes y plazos se expresan en milisegundos monotonicos de C6. */
enum {
    DEMANDA_MAX_VEHICULOS = 1000,
    DEMANDA_VIGENCIA_INICIAL_MS = 5000,
    RECEPCION_FASE_SEGURA = 7
};

/* Demanda ordinaria y validacion. */
typedef struct {
    int32_t n1, n2;
    uint64_t secuencia, recibida_ms;
    bool valida;
} demanda_vehicular_t;
bool demanda_validar(demanda_vehicular_t demanda, uint64_t ahora_ms, uint64_t ultima_secuencia);

/* Gestor de la ultima demanda aceptada. */
typedef enum {
    DEMANDA_NUEVA_VALIDA,
    DEMANDA_INVALIDACION_NUEVA,
    DEMANDA_REPETIDA_O_FUERA_ORDEN
} resultado_demanda_t;
typedef struct {
    demanda_vehicular_t ultima;
    uint64_t ultima_secuencia;
    bool disponible;
} gestor_demanda_t;
resultado_demanda_t gestor_demanda_recibir(gestor_demanda_t *gestor, demanda_vehicular_t demanda,
                                           uint64_t ahora_ms, uint32_t max_edad_ms);
bool gestor_demanda_vigente(const gestor_demanda_t *gestor, uint64_t ahora_ms,
                            uint32_t max_edad_ms);

/* Datagramas ASCII, secuencias y retencion de invalidaciones. */
#define CONTEOS_UDP_MAX_BYTES 48
typedef struct {
    uint64_t secuencia;
    uint16_t n1, n2;
    bool valido;
} mensaje_conteos_t;
typedef struct {
    bool valido, recuperable;
    uint64_t generacion, atendida, vence, resultado, recibida_ms;
    demanda_vehicular_t demanda;
} estado_recepcion_t;
typedef struct {
    estado_recepcion_t estado;
    uint64_t ultima_secuencia, ultima_valida_ms;
    uint32_t timeout_ms;
    uint8_t fase;
    bool tiene_valida, bloqueado, conectado;
} gestor_recepcion_t;
bool conteos_decodificar(const char *datos, size_t longitud, mensaje_conteos_t *salida);
bool recepcion_iniciar(gestor_recepcion_t *g, uint32_t timeout_ms);
void recepcion_invalidar(gestor_recepcion_t *g);
void recepcion_conexion(gestor_recepcion_t *g, bool conectado);
void recepcion_caducar(gestor_recepcion_t *g, uint64_t ahora);
bool recepcion_recibir(gestor_recepcion_t *g, mensaje_conteos_t m, uint64_t ahora);
void recepcion_atender(gestor_recepcion_t *g, uint8_t fase, uint64_t generacion);
