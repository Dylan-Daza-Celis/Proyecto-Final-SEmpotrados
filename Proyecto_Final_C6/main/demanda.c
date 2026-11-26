#include "demanda.h"
#include <limits.h>

/* 1. Validacion de demanda y gestor ordinario. */
bool demanda_validar(demanda_vehicular_t demanda, uint64_t ahora_ms, uint64_t ultima_secuencia)
{
    return demanda.valida && demanda.n1 >= 0 && demanda.n1 <= DEMANDA_MAX_VEHICULOS &&
           demanda.n2 >= 0 && demanda.n2 <= DEMANDA_MAX_VEHICULOS &&
           demanda.secuencia > ultima_secuencia && demanda.recibida_ms <= ahora_ms &&
           ahora_ms - demanda.recibida_ms <= DEMANDA_VIGENCIA_INICIAL_MS;
}

bool gestor_demanda_vigente(const gestor_demanda_t *gestor, uint64_t ahora_ms, uint32_t max_edad_ms)
{
    return gestor && gestor->disponible && gestor->ultima.valida && max_edad_ms > 0 &&
           gestor->ultima.n1 >= 0 && gestor->ultima.n1 <= 1000 && gestor->ultima.n2 >= 0 &&
           gestor->ultima.n2 <= 1000 && gestor->ultima.recibida_ms <= ahora_ms &&
           ahora_ms - gestor->ultima.recibida_ms <= max_edad_ms;
}
resultado_demanda_t gestor_demanda_recibir(gestor_demanda_t *gestor, demanda_vehicular_t demanda,
                                           uint64_t ahora_ms, uint32_t max_edad_ms)
{
    if (!gestor || demanda.secuencia <= gestor->ultima_secuencia) {
        return DEMANDA_REPETIDA_O_FUERA_ORDEN;
    }
    gestor->ultima_secuencia = demanda.secuencia;
    gestor->ultima = demanda;
    gestor->disponible = true;
    if (!gestor_demanda_vigente(gestor, ahora_ms, max_edad_ms)) {
        gestor->disponible = false;
        return DEMANDA_INVALIDACION_NUEVA;
    }
    return DEMANDA_NUEVA_VALIDA;
}

/* 2. Decodificacion ASCII y gestion de recepcion conectada. */
/* ASCII estricto y estado puro: probado sin Wi-Fi ni placa. */
bool conteos_decodificar(const char *datos, size_t longitud, mensaje_conteos_t *salida)
{
    if (!datos || !salida || longitud < 7 || longitud > CONTEOS_UDP_MAX_BYTES) {
        return false;
    }
    uint64_t campos[4] = {0};
    unsigned campo = 0, digitos = 0;
    bool empieza_cero = false;
    for (size_t i = 0; i < longitud; ++i) {
        unsigned char caracter = (unsigned char)datos[i];
        if (caracter == ',') {
            if (!digitos || campo == 3) {
                return false;
            }
            ++campo;
            digitos = 0;
            empieza_cero = false;
            continue;
        }
        if (caracter < '0' || caracter > '9' || (digitos && empieza_cero)) {
            return false;
        }
        unsigned digito = caracter - '0';
        uint64_t limite = campo == 0 ? UINT64_MAX : campo == 3 ? 1 : 1000;
        if (campos[campo] > limite / 10 || (campos[campo] == limite / 10 && digito > limite % 10)) {
            return false;
        }
        campos[campo] = campos[campo] * 10 + digito;
        if (!digitos) {
            empieza_cero = caracter == '0';
        }
        ++digitos;
    }
    if (campo != 3 || !digitos || !campos[0]) {
        return false;
    }
    *salida =
        (mensaje_conteos_t){campos[0], (uint16_t)campos[1], (uint16_t)campos[2], campos[3] == 1};
    return true;
}
bool recepcion_iniciar(gestor_recepcion_t *gestor, uint32_t timeout_ms)
{
    if (!gestor || timeout_ms < 100 || timeout_ms > 60000) {
        return false;
    }
    *gestor = (gestor_recepcion_t){
        .estado = {.generacion = 1}, .timeout_ms = timeout_ms, .fase = RECEPCION_FASE_SEGURA};
    return true;
}
void recepcion_invalidar(gestor_recepcion_t *gestor)
{
    if (gestor->estado.generacion == UINT64_MAX) {
        gestor->bloqueado = true;
    } else {
        ++gestor->estado.generacion;
    }
    gestor->estado.valido = false;
    gestor->estado.recuperable = false;
    gestor->estado.vence = 0;
}
void recepcion_caducar(gestor_recepcion_t *gestor, uint64_t ahora_ms)
{
    if (gestor->estado.valido &&
        (ahora_ms < gestor->estado.recibida_ms || ahora_ms >= gestor->estado.vence)) {
        recepcion_invalidar(gestor);
    }
}
void recepcion_conexion(gestor_recepcion_t *gestor, bool conectado)
{
    gestor->conectado = conectado;
    if (!conectado) {
        recepcion_invalidar(gestor);
    }
}
void recepcion_atender(gestor_recepcion_t *gestor, uint8_t fase, uint64_t generacion)
{
    gestor->fase = fase;
    if (fase == RECEPCION_FASE_SEGURA && generacion == gestor->estado.generacion) {
        gestor->estado.atendida = generacion;
    }
}
bool recepcion_recibir(gestor_recepcion_t *gestor, mensaje_conteos_t mensaje, uint64_t ahora_ms)
{
    recepcion_caducar(gestor, ahora_ms);
    if (!gestor->conectado || gestor->bloqueado || !mensaje.secuencia || mensaje.n1 > 1000 ||
        mensaje.n2 > 1000) {
        return false;
    }
    if (mensaje.secuencia <= gestor->ultima_secuencia) {
        bool anterior_caduco =
            !gestor->tiene_valida || (ahora_ms >= gestor->ultima_valida_ms &&
                                      ahora_ms - gestor->ultima_valida_ms >= gestor->timeout_ms);
        /* Reinicio sencillo: solo demanda caducada, rojos atendidos y nuevo valido. */
        if (!mensaje.valido || !anterior_caduco || gestor->fase != RECEPCION_FASE_SEGURA ||
            gestor->estado.atendida != gestor->estado.generacion) {
            return false;
        }
        gestor->ultima_secuencia = 0;
    }
    gestor->ultima_secuencia = mensaje.secuencia;
    if (!mensaje.valido) {
        recepcion_invalidar(gestor);
        return true;
    }
    if (ahora_ms > UINT64_MAX - gestor->timeout_ms || gestor->estado.resultado == UINT64_MAX) {
        recepcion_invalidar(gestor);
        gestor->bloqueado = true;
        return false;
    }
    gestor->tiene_valida = true;
    gestor->ultima_valida_ms = ahora_ms;
    gestor->estado.valido = true;
    gestor->estado.recibida_ms = ahora_ms;
    gestor->estado.vence = ahora_ms + gestor->timeout_ms;
    gestor->estado.recuperable = gestor->fase == RECEPCION_FASE_SEGURA &&
                                 gestor->estado.atendida == gestor->estado.generacion;
    ++gestor->estado.resultado; /* Identidad local creciente, incluso al reiniciar Python. */
    gestor->estado.demanda =
        (demanda_vehicular_t){mensaje.n1, mensaje.n2, gestor->estado.resultado, ahora_ms, true};
    return true;
}
