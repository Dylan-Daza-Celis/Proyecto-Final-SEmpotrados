#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

esp_err_t wifi_inicializar(void);
// La espera es finita y devuelve true solo si se obtuvo una dirección IPv4.
bool wifi_esperar_ip(uint32_t espera_ms);
