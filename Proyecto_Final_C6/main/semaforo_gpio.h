#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "controlador_semaforos.h"

/* Solo el propietario usa esta interfaz. Operaciones inyectables para ensayos sin placa. */
typedef struct {
    int (*escribir)(int pin, int nivel);
    int (*habilitar)(uint64_t mascara);
    bool (*salida_valida)(int pin);
} operaciones_gpio_t;
typedef struct { operaciones_gpio_t operaciones; bool listo, bloqueado; } semaforo_gpio_t;
bool semaforo_pines_validos(const int pines[6], bool (*salida_valida)(int));
bool semaforo_gpio_iniciar(semaforo_gpio_t *gpio, operaciones_gpio_t operaciones);
bool semaforo_gpio_aplicar(semaforo_gpio_t *gpio, luces_semaforo_t luces);
void semaforo_gpio_seguro(semaforo_gpio_t *gpio);
operaciones_gpio_t semaforo_operaciones_idf(void);
