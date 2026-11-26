#include "semaforo_gpio.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_err.h"
static int escribir(int pin, int nivel)
{
    esp_err_t error = gpio_set_level((gpio_num_t)pin, nivel);
    if (error != ESP_OK) {
        ESP_LOGE("semaforo_gpio", "GPIO %d nivel %d: %s", pin, nivel, esp_err_to_name(error));
    }
    return error;
}
static bool valida(int pin)
{
    return GPIO_IS_VALID_OUTPUT_GPIO(pin);
}
static int habilitar(uint64_t mascara)
{
    gpio_config_t config = {.pin_bit_mask = mascara,
                            .mode = GPIO_MODE_OUTPUT,
                            .pull_up_en = GPIO_PULLUP_DISABLE,
                            .pull_down_en = GPIO_PULLDOWN_DISABLE,
                            .intr_type = GPIO_INTR_DISABLE};
    esp_err_t error = gpio_config(&config);
    if (error != ESP_OK) {
        ESP_LOGE("semaforo_gpio", "Habilitacion: %s", esp_err_to_name(error));
    }
    return error;
}
operaciones_gpio_t semaforo_operaciones_idf(void)
{
    return (operaciones_gpio_t){escribir, habilitar, valida};
}
