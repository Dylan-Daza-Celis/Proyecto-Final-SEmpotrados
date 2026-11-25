#pragma once

#include "esp_err.h"

// Solo app_main administra el ciclo de vida: evita instancias concurrentes.
esp_err_t servidor_http_iniciar(void);
esp_err_t servidor_http_detener(void);
