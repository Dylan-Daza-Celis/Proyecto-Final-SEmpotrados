#include "http_server.h"
#include "camera_driver.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include "esp_heap_caps.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_timer.h"

static const char *TAG = "http_server";
static httpd_handle_t servidor;
extern const unsigned char pagina_inicio[] asm("_binary_index_html_start");
extern const unsigned char pagina_fin[] asm("_binary_index_html_end");

static void sin_cache(httpd_req_t *peticion)
{
    httpd_resp_set_hdr(peticion, "Cache-Control", "no-store, no-cache, must-revalidate, max-age=0");
    httpd_resp_set_hdr(peticion, "Pragma", "no-cache");
    httpd_resp_set_hdr(peticion, "Expires", "0");
}

static esp_err_t responder_error(httpd_req_t *peticion, const char *estado, const char *mensaje)
{
    sin_cache(peticion);
    httpd_resp_set_status(peticion, estado);
    httpd_resp_set_type(peticion, "text/plain; charset=utf-8");
    return httpd_resp_sendstr(peticion, mensaje);
}

static esp_err_t rechazar_cuerpo(httpd_req_t *peticion, const char *estado, const char *mensaje)
{
    // No drenar cuerpos no admitidos: podrían declarar longitudes enormes.
    // ESP_FAIL indica al servidor que cierre la sesión tras enviar el error.
    responder_error(peticion, estado, mensaje);
    return ESP_FAIL;
}

static esp_err_t mostrar_inicio(httpd_req_t *peticion)
{
    sin_cache(peticion);
    httpd_resp_set_type(peticion, "text/html; charset=utf-8");
    return httpd_resp_send(peticion, (const char *)pagina_inicio, pagina_fin - pagina_inicio - 1);
}

static esp_err_t capturar_imagen(httpd_req_t *peticion)
{
    camera_fb_t *imagen = NULL;
    uint32_t identificador;
    esp_err_t resultado = camera_adquirir(&imagen, &identificador);
    if (resultado != ESP_OK) {
        ESP_LOGW(TAG, "Captura HTTP rechazada: %s", esp_err_to_name(resultado));
        return responder_error(peticion, "503 Service Unavailable", "No se pudo adquirir un JPEG completo; vuelva a intentar.");
    }
    // La cámara y el buffer siguen protegidos hasta finalizar el envío síncrono.
    char numero[16];
    char nombre[80];
    snprintf(numero, sizeof(numero), "%" PRIu32, identificador);
    snprintf(nombre, sizeof(nombre), "inline; filename=\"captura-%" PRIu32 ".jpg\"", identificador);
    sin_cache(peticion);
    httpd_resp_set_type(peticion, "image/jpeg");
    httpd_resp_set_hdr(peticion, "Content-Disposition", nombre);
    httpd_resp_set_hdr(peticion, "X-Capture-Id", numero);
    resultado = httpd_resp_send(peticion, (const char *)imagen->buf, imagen->len);
    camera_liberar(imagen); // También en desconexión o timeout de envío.
    if (resultado != ESP_OK) {
        ESP_LOGW(TAG, "Transmisión de imagen #%s fallida: %s", numero, esp_err_to_name(resultado));
    }
    return resultado;
}

static esp_err_t mostrar_estado(httpd_req_t *peticion)
{
    camera_estado_t estado;
    if (camera_obtener_estado(&estado) != ESP_OK) {
        return responder_error(peticion, "503 Service Unavailable", "Cámara ocupada; vuelva a intentar.");
    }
    char contenido[640];
    const int longitud = snprintf(contenido, sizeof(contenido),
        "{\"camera_ready\":%s,\"sensor\":\"%s\",\"pid\":%u,\"width\":%u,\"height\":%u,"
        "\"format\":\"JPEG\",\"quality\":%d,\"captures\":%" PRIu32 ",\"capture_errors\":%" PRIu32 ","
        "\"internal_free\":%zu,\"internal_minimum\":%zu,\"psram_free\":%zu,\"psram_largest\":%zu,\"uptime_ms\":%" PRId64 "}",
        estado.inicializada ? "true" : "false", estado.modelo, estado.pid, estado.ancho, estado.alto,
        estado.calidad, estado.capturas_correctas, estado.capturas_fallidas,
        heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
        heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
        heap_caps_get_free_size(MALLOC_CAP_SPIRAM), heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM),
        esp_timer_get_time() / 1000);
    if (longitud < 0 || (size_t)longitud >= sizeof(contenido)) {
        return responder_error(peticion, "500 Internal Server Error", "No se pudo generar el estado.");
    }
    sin_cache(peticion);
    httpd_resp_set_type(peticion, "application/json");
    return httpd_resp_send(peticion, contenido, longitud);
}

static esp_err_t controlar_camara(httpd_req_t *peticion)
{
    // Contrato estricto y pequeño: application/x-www-form-urlencoded.
    // Se aceptan exactamente resolution=QVGA|VGA|SVGA y quality=10..40.
    char tipo[64];
    if (httpd_req_get_hdr_value_str(peticion, "Content-Type", tipo, sizeof(tipo)) != ESP_OK ||
        strcmp(tipo, "application/x-www-form-urlencoded") != 0) {
        return rechazar_cuerpo(peticion, "415 Unsupported Media Type", "Utilice application/x-www-form-urlencoded.");
    }
    char contenido[80];
    if (peticion->content_len == 0 || peticion->content_len >= sizeof(contenido)) {
        return rechazar_cuerpo(peticion, "400 Bad Request", "Cuerpo de control vacío o demasiado grande.");
    }
    size_t recibidos = 0;
    const int64_t limite = esp_timer_get_time() + 5000000;
    while (recibidos < peticion->content_len) {
        if (esp_timer_get_time() > limite) {
            httpd_resp_send_err(peticion, HTTPD_408_REQ_TIMEOUT, "Tiempo de recepción agotado.");
            return ESP_FAIL; // Cierra la conexión con cuerpo incompleto.
        }
        const int leidos = httpd_req_recv(peticion, contenido + recibidos, peticion->content_len - recibidos);
        if (leidos <= 0) {
            if (leidos == HTTPD_SOCK_ERR_TIMEOUT) {
                httpd_resp_send_err(peticion, HTTPD_408_REQ_TIMEOUT, "Tiempo de recepción agotado.");
            }
            return ESP_FAIL;
        }
        recibidos += leidos;
    }
    contenido[recibidos] = '\0';
    // Rechaza NUL incrustado, campos desconocidos, duplicados, signos y decimales.
    char resolucion[5] = {0};
    int calidad = 0;
    int consumidos = 0;
    const int campos = sscanf(contenido, "resolution=%4[A-Z]&quality=%2[0-9]", resolucion, tipo);
    if (campos == 2) {
        sscanf(tipo, "%d", &calidad);
        char canonico[80];
        consumidos = snprintf(canonico, sizeof(canonico), "resolution=%s&quality=%d", resolucion, calidad);
        if (consumidos < 0 || (size_t)consumidos != recibidos || memcmp(canonico, contenido, recibidos) != 0) {
            calidad = 0;
        }
    }
    framesize_t tamano = FRAMESIZE_INVALID;
    if (strcmp(resolucion, "QVGA") == 0) { tamano = FRAMESIZE_QVGA; }
    if (strcmp(resolucion, "VGA") == 0) { tamano = FRAMESIZE_VGA; }
    if (strcmp(resolucion, "SVGA") == 0) { tamano = FRAMESIZE_SVGA; }
    if (campos != 2 || calidad < 10 || calidad > 40 || tamano == FRAMESIZE_INVALID) {
        return responder_error(peticion, "400 Bad Request", "Use resolution=QVGA|VGA|SVGA&quality=10..40, en ese orden y sin campos adicionales.");
    }
    const esp_err_t resultado = camera_reconfigurar(tamano, calidad);
    if (resultado != ESP_OK) {
        ESP_LOGE(TAG, "Control de cámara falló: %s", esp_err_to_name(resultado));
        return responder_error(peticion, "503 Service Unavailable", "No se pudo cambiar la configuración; consulte /status y el monitor serie.");
    }
    return mostrar_estado(peticion);
}

esp_err_t servidor_http_iniciar(void)
{
    if (servidor != NULL) {
        return ESP_OK;
    }
    httpd_config_t configuracion = HTTPD_DEFAULT_CONFIG();
    configuracion.stack_size = 8192;
    configuracion.max_uri_handlers = 4;
    configuracion.max_open_sockets = 3;
    configuracion.lru_purge_enable = true;
    configuracion.recv_wait_timeout = 5;
    configuracion.send_wait_timeout = 5;
    esp_err_t resultado = httpd_start(&servidor, &configuracion);
    if (resultado != ESP_OK) { return resultado; }
    const httpd_uri_t rutas[] = {
        {.uri = "/", .method = HTTP_GET, .handler = mostrar_inicio},
        {.uri = "/capture", .method = HTTP_GET, .handler = capturar_imagen},
        {.uri = "/status", .method = HTTP_GET, .handler = mostrar_estado},
        {.uri = "/control", .method = HTTP_POST, .handler = controlar_camara},
    };
    for (size_t indice = 0; indice < sizeof(rutas) / sizeof(rutas[0]); ++indice) {
        resultado = httpd_register_uri_handler(servidor, &rutas[indice]);
        if (resultado != ESP_OK) {
            servidor_http_detener();
            return resultado;
        }
    }
    ESP_LOGI(TAG, "Servidor HTTP iniciado en puerto 80.");
    return ESP_OK;
}

esp_err_t servidor_http_detener(void)
{
    if (servidor == NULL) { return ESP_OK; }
    const esp_err_t resultado = httpd_stop(servidor);
    if (resultado == ESP_OK) {
        servidor = NULL;
        ESP_LOGI(TAG, "Servidor HTTP detenido.");
    }
    return resultado;
}
