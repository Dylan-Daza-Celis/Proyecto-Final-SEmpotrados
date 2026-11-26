idf_component_register(SRCS "main.c" "controlador_semaforos.c" "semaforo_gpio.c"
    "semaforo_gpio_idf.c" "simulador_demanda.c" "prioridad_vehicular.c" "gestor_demanda.c"
    "protocolo_udp.c" "sesion_udp.c" "udp_criptografia.c" "cliente_udp.c" "wifi_manager.c" "control_conectado.c"
    INCLUDE_DIRS "." REQUIRES esp_driver_gpio esp_timer freertos log esp_wifi esp_event esp_netif nvs_flash lwip mbedtls)
