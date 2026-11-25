#pragma once
#include <stdbool.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
bool simulador_demanda_iniciar(QueueHandle_t cola);
