idf_component_register(
    SRCS "main.c" "camera_driver.c" "wifi_manager.c" "http_server.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES esp_psram heap log freertos esp_system esp_driver_ledc
                  esp_wifi esp_netif esp_event nvs_flash esp_http_server esp_timer
    EMBED_TXTFILES "web/index.html"
)
