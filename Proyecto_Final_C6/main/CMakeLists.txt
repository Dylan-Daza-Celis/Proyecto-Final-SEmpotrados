idf_component_register(
    SRCS "main.c" "controlador.c" "demanda.c" "comunicacion.c"
         "semaforo_gpio.c" "semaforo_gpio_idf.c"
    INCLUDE_DIRS "."
    REQUIRES esp_driver_gpio esp_timer freertos log esp_wifi esp_event esp_netif nvs_flash lwip
)
