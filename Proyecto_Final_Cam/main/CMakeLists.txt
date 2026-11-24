idf_component_register(
    SRCS "main.c" "camera_driver.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES esp_psram heap log freertos esp_system esp_driver_ledc
)
