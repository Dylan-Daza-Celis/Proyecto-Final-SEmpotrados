# The following five lines of boilerplate have to be in your project's
# CMakeLists in this exact order for cmake to work correctly
cmake_minimum_required(VERSION 3.22)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(Proyecto_Final_Cam)

# Este proyecto utiliza el bus paralelo y el pinout de la ESP32-CAM clásica.
if(NOT IDF_TARGET STREQUAL "esp32")
    message(FATAL_ERROR "Proyecto_Final_Cam requiere: idf.py set-target esp32")
endif()
