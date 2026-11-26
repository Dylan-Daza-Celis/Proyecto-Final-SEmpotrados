#pragma once
#include <stdbool.h>
#include <stdint.h>

/* Provisional: confirmar esquema y variante física (en SiP 10/11 pueden no salir). */
#define PIN_ROJO_1 2
#define PIN_AMARILLO_1 3
#define PIN_VERDE_1 10
#define PIN_ROJO_2 11
#define PIN_AMARILLO_2 18
#define PIN_VERDE_2 19
#define NUMERO_LEDS 6

typedef enum { LUZ_ROJA, LUZ_AMARILLA, LUZ_VERDE } color_semaforo_t;
typedef struct {
    color_semaforo_t carril_1, carril_2;
} luces_semaforo_t;

/* Solo el propietario usa esta interfaz. Operaciones inyectables para ensayos sin placa. */
typedef struct {
    int (*escribir)(int pin, int nivel);
    int (*habilitar)(uint64_t mascara);
    bool (*salida_valida)(int pin);
} operaciones_gpio_t;
typedef struct {
    operaciones_gpio_t operaciones;
    bool listo, bloqueado;
    int niveles[6];
} semaforo_gpio_t;
bool semaforo_pines_validos(const int pines[6], bool (*salida_valida)(int));
bool semaforo_gpio_iniciar(semaforo_gpio_t *gpio, operaciones_gpio_t operaciones);
bool semaforo_gpio_aplicar(semaforo_gpio_t *gpio, luces_semaforo_t luces);
void semaforo_gpio_seguro(semaforo_gpio_t *gpio);
operaciones_gpio_t semaforo_operaciones_idf(void);
