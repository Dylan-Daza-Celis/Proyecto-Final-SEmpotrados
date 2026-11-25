idf_component_register(SRCS "main.c" "controlador_semaforos.c" "semaforo_gpio.c"
    "semaforo_gpio_idf.c" "simulador_demanda.c"
    INCLUDE_DIRS "." REQUIRES esp_driver_gpio esp_timer freertos log)
