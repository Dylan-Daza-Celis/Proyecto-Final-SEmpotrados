#include "semaforo_gpio.h"
static const int pines[NUMERO_LEDS] = {PIN_ROJO_1, PIN_AMARILLO_1, PIN_VERDE_1,
                                       PIN_ROJO_2, PIN_AMARILLO_2, PIN_VERDE_2};

bool semaforo_pines_validos(const int lista[6], bool (*valida)(int))
{
    if (!lista || !valida) {
        return false;
    }
    for (int i = 0; i < 6; ++i) {
        int pin = lista[i];
        if (!valida(pin) || pin < 0 || pin >= 24 || pin == 4 || pin == 5 || pin == 8 || pin == 9 ||
            pin == 12 || pin == 13 || pin == 15 || pin == 16 || pin == 17) {
            return false;
        }
        for (int j = 0; j < i; ++j) {
            if (lista[j] == pin) {
                return false;
            }
        }
    }
    return true;
}

void semaforo_gpio_seguro(semaforo_gpio_t *gpio)
{
    if (!gpio || !gpio->operaciones.escribir) {
        return;
    }
    gpio->bloqueado = true;
    /* Intentar cada operación, aun si alguna falla. No garantiza hardware averiado. */
    gpio->operaciones.escribir(PIN_VERDE_1, 0);
    gpio->operaciones.escribir(PIN_VERDE_2, 0);
    gpio->operaciones.escribir(PIN_AMARILLO_1, 0);
    gpio->operaciones.escribir(PIN_AMARILLO_2, 0);
    gpio->operaciones.escribir(PIN_ROJO_1, 1);
    gpio->operaciones.escribir(PIN_ROJO_2, 1);
}

static bool escribir_cambio(semaforo_gpio_t *gpio, int indice, int nivel)
{
    if (gpio->niveles[indice] == nivel) {
        return true;
    }
    if (gpio->operaciones.escribir(pines[indice], nivel)) {
        return false;
    }
    gpio->niveles[indice] = nivel;
    return true;
}

bool semaforo_gpio_aplicar(semaforo_gpio_t *gpio, luces_semaforo_t luces)
{
    if (!gpio || !gpio->listo || gpio->bloqueado) {
        return false;
    }
    if ((luces.carril_1 != LUZ_ROJA && luces.carril_2 != LUZ_ROJA) || luces.carril_1 < LUZ_ROJA ||
        luces.carril_1 > LUZ_VERDE || luces.carril_2 < LUZ_ROJA || luces.carril_2 > LUZ_VERDE) {
        semaforo_gpio_seguro(gpio);
        return false;
    }
    int deseados[6] = {0};
    deseados[luces.carril_1] = 1;
    deseados[3 + luces.carril_2] = 1;
    /* Quitar incompatibles, asegurar rojos opuestos y solo entonces abrir el carril. */
    const int orden[] = {2, 5, 1, 4, 0, 3, 0, 3, 1, 4, 2, 5};
    for (int paso = 0; paso < 12; ++paso) {
        int indice = orden[paso];
        bool escribir = (paso < 4   ? !deseados[indice]
                         : paso < 6 ? deseados[indice]
                         : paso < 8 ? !deseados[indice]
                                    : deseados[indice]);
        if (escribir && !escribir_cambio(gpio, indice, deseados[indice])) {
            semaforo_gpio_seguro(gpio);
            return false;
        }
    }
    return true;
}

bool semaforo_gpio_iniciar(semaforo_gpio_t *gpio, operaciones_gpio_t operaciones)
{
    if (!gpio) {
        return false;
    }
    *gpio = (semaforo_gpio_t){.operaciones = operaciones};
    if (!operaciones.escribir || !operaciones.habilitar ||
        !semaforo_pines_validos(pines, operaciones.salida_valida)) {
        return false;
    }
    uint64_t mascara = 0;
    for (int i = 0; i < 6; ++i) {
        mascara |= UINT64_C(1) << pines[i];
    }
    /* Precargar registros antes de habilitar salida: rojos altos, resto bajos. */
    const int orden_inicial[] = {2, 5, 1, 4, 0, 3};
    for (int i = 0; i < 6; ++i) {
        int indice = orden_inicial[i];
        gpio->niveles[indice] = indice == 0 || indice == 3;
        if (operaciones.escribir(pines[indice], gpio->niveles[indice])) {
            semaforo_gpio_seguro(gpio);
            return false;
        }
    }
    if (operaciones.habilitar(mascara)) {
        semaforo_gpio_seguro(gpio);
        return false;
    }
    gpio->listo = true;
    return semaforo_gpio_aplicar(gpio, (luces_semaforo_t){LUZ_ROJA, LUZ_ROJA});
}
