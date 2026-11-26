/* 1. Includes: ESP-IDF/FreeRTOS y los modulos de la aplicacion. */
#include <inttypes.h>
#include "sdkconfig.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "controlador.h"
#include "semaforo_gpio.h"
#include "comunicacion.h"

/* 2. Constantes y configuracion: Kconfig define pines confirmados, modo y tiempos. */
static const char *TAG = "semaforos";
/* 3. Variables y estructuras de ejecucion.
 * GPIO, controlador, tiempos y guardia viven en tarea_controlador: un propietario.
 * Solo comunicacion conserva su estado compartido bajo secciones criticas. */

/* 4. Identificadores de tareas y colas.
 * La cola de un valor se crea dentro del propietario y se pasa como parametro.
 * No guardamos TaskHandle_t: ninguna tarea suspende o modifica a otra. */
static void tarea_controlador(void *parametro);
#ifdef CONFIG_SEMAFORO_SIMULAR_DEMANDA
static void tarea_simulacion(void *parametro);
#endif

/* 5. Funciones auxiliares: reloj, operaciones GPIO y registro de demanda. */
static uint64_t ahora_ms(void)
{
    return (uint64_t)esp_timer_get_time() / 1000;
}
#ifdef CONFIG_SEMAFORO_CONECTADO
static estado_recepcion_t leer_red(void *contexto)
{
    (void)contexto;
    return receptor_udp_estado();
}
static uint64_t reloj_control(void *contexto)
{
    (void)contexto;
    return ahora_ms();
}
static void invalidar_red(void *contexto)
{
    (void)contexto;
    receptor_udp_invalidar();
}
static bool escribir_fase(void *contexto, luces_semaforo_t luces)
{
    return semaforo_gpio_aplicar((semaforo_gpio_t *)contexto, luces);
}
#endif

static void registrar_demanda(const controlador_semaforos_t *controlador, uint64_t ahora)
{
    const gestor_demanda_t *gestor = &controlador->demanda;
    if (!gestor_demanda_vigente(gestor, ahora, controlador->max_edad_demanda_ms)) {
        if (gestor->ultima_secuencia && gestor->ultima.recibida_ms <= ahora) {
            ESP_LOGI(TAG,
                     "Demanda NO vigente; edad=%" PRIu64 " ms seq=%" PRIu64 "; sin medicion N1/N2",
                     ahora - gestor->ultima.recibida_ms, gestor->ultima_secuencia);
        } else {
            ESP_LOGI(TAG, "Demanda NO vigente; edad no disponible; sin medicion N1/N2");
        }
#ifndef CONFIG_SEMAFORO_CONECTADO
        ESP_LOGI(
            TAG,
            "Proxima seleccion sin demanda usa verde convencional; fase actual conserva duracion");
#endif
        return;
    }
    ESP_LOGI(TAG,
             "N1=%" PRId32 " N2=%" PRId32 " D=%" PRId32 " valida=1 edad=%" PRIu64
             " ms seq=%" PRIu64,
             gestor->ultima.n1, gestor->ultima.n2, gestor->ultima.n1 - gestor->ultima.n2,
             ahora - gestor->ultima.recibida_ms, gestor->ultima.secuencia);
}
/* 6. Tarea controladora: inicializa y es la unica propietaria de GPIO. */
static void tarea_controlador(void *parametro)
{
    (void)parametro;
#ifndef CONFIG_SEMAFORO_PINOUT_CONFIRMADO
    ESP_LOGE(TAG,
             "Confirmar placa/esquema y pinout provisional en menuconfig; salidas deshabilitadas");
    vTaskDelete(NULL);
    return;
#endif
    semaforo_gpio_t gpio;
    if (!semaforo_gpio_iniciar(&gpio, semaforo_operaciones_idf())) {
        ESP_LOGE(TAG, "Fallo GPIO; transiciones detenidas");
        vTaskDelete(NULL);
        return;
    }
    controlador_semaforos_t controlador;
    tiempos_semaforo_t tiempos = {CONFIG_SEMAFORO_VERDE_1_MS, CONFIG_SEMAFORO_VERDE_2_MS,
                                  CONFIG_SEMAFORO_AMARILLO_MS, CONFIG_SEMAFORO_ROJO_TOTAL_MS};
    if (!controlador_iniciar(&controlador, tiempos, ahora_ms())) {
        ESP_LOGE(TAG, "Tiempos invalidos");
        semaforo_gpio_seguro(&gpio);
        vTaskDelete(NULL);
        return;
    }
    controlador.max_edad_demanda_ms = CONFIG_SEMAFORO_MAX_EDAD_DEMANDA_MS;
#if defined(CONFIG_SEMAFORO_ADAPTATIVO) || defined(CONFIG_SEMAFORO_CONECTADO)
    parametros_prioridad_t parametros = {CONFIG_SEMAFORO_VERDE_MIN_MS,
                                         CONFIG_SEMAFORO_VERDE_MAX_MS,
                                         CONFIG_SEMAFORO_AMARILLO_MS,
                                         CONFIG_SEMAFORO_ROJO_TOTAL_MS,
                                         CONFIG_SEMAFORO_UMBRAL,
                                         CONFIG_SEMAFORO_INCREMENTO_MS,
                                         CONFIG_SEMAFORO_OBJETIVO_SIN_VERDE_MS};
    if (!controlador_configurar_adaptativo(&controlador, parametros,
                                           CONFIG_SEMAFORO_MAX_EDAD_DEMANDA_MS)) {
        ESP_LOGE(TAG, "Parametros adaptativos incompatibles con objetivo nominal");
        semaforo_gpio_seguro(&gpio);
        vTaskDelete(NULL);
        return;
    }
#endif
    uint64_t maximo_convencional =
        tiempos.verde_1_ms > tiempos.verde_2_ms ? tiempos.verde_1_ms : tiempos.verde_2_ms;
    if (!controlador.adaptativo && maximo_convencional + 2 * (uint64_t)tiempos.amarillo_ms +
                                           2 * (uint64_t)tiempos.rojo_total_ms >
                                       CONFIG_SEMAFORO_OBJETIVO_SIN_VERDE_MS) {
        ESP_LOGE(TAG, "Tiempos convencionales incompatibles con objetivo nominal");
        semaforo_gpio_seguro(&gpio);
        vTaskDelete(NULL);
        return;
    }
    ESP_LOGI(TAG, "Modo %s, inicio ambos rojos",
             controlador.adaptativo ? "ADAPTATIVO" : "CONVENCIONAL");
    QueueHandle_t cola = xQueueCreate(1, sizeof(demanda_vehicular_t));
    if (!cola) {
        ESP_LOGE(TAG, "Fallo creando cola");
        semaforo_gpio_seguro(&gpio);
        vTaskDelete(NULL);
        return;
    }
#ifdef CONFIG_SEMAFORO_CONECTADO
    control_conectado_t guardia = {0};
    controlador.estado = ESTADO_SEGURO;
    if (!receptor_udp_iniciar(cola) || !wifi_manager_iniciar()) {
        ESP_LOGE(TAG, "Configuracion/red no disponible; mantener rojos hasta corregir y reiniciar");
        semaforo_gpio_seguro(&gpio);
        vTaskDelete(NULL);
        return;
    }
    ESP_LOGI(TAG, "Adaptativo CONECTADO: esperar observacion nueva valida en ambos rojos");
#endif
#ifdef CONFIG_SEMAFORO_SIMULAR_DEMANDA
    if (xTaskCreate(tarea_simulacion, "demanda_simulada", 3072, cola, 3, NULL) != pdPASS) {
        ESP_LOGE(TAG, "Fallo simulador");
        semaforo_gpio_seguro(&gpio);
        vQueueDelete(cola);
        vTaskDelete(NULL);
        return;
    }
#endif
    uint64_t fin_verde[2] = {0};
    bool tiene_fin[2] = {false, false};
    for (;;) {
#ifndef CONFIG_SEMAFORO_CONECTADO
        demanda_vehicular_t demanda;
        if (xQueueReceive(cola, &demanda, 0) == pdPASS) {
            resultado_demanda_t resultado =
                controlador_recibir_demanda(&controlador, demanda, ahora_ms());
            ESP_LOGI(TAG, "Demanda SIMULADA seq=%" PRIu64 " recepcion=%s", demanda.secuencia,
                     resultado == DEMANDA_NUEVA_VALIDA         ? "VALIDA"
                     : resultado == DEMANDA_INVALIDACION_NUEVA ? "INVALIDACION NUEVA"
                                                               : "DUPLICADA/FUERA DE ORDEN");
            registrar_demanda(&controlador, ahora_ms());
        }
#endif
        estado_semaforo_t anterior = controlador.estado;
        uint64_t inicio_anterior = controlador.inicio_ms;
#ifdef CONFIG_SEMAFORO_CONECTADO
        estado_recepcion_t estado_red = receptor_udp_estado();
        if (estado_red.valido && ahora_ms() >= estado_red.vence) {
            receptor_udp_invalidar();
        }
        bool cambio =
            control_conectado_paso(&guardia, &controlador, receptor_udp_estado(), ahora_ms());
        if (anterior == ESTADO_SEGURO && controlador.estado == ROJO_TOTAL_INICIAL) {
            ESP_LOGI(TAG, "Recuperacion desde seguro: nueva observacion valida recibida en seguro, "
                          "rojo inicial completo");
        }
#else
        bool cambio = controlador_actualizar(&controlador, ahora_ms());
#endif
        if (cambio) {
#ifdef CONFIG_SEMAFORO_CONECTADO
            uint64_t antes_gpio = ahora_ms();
            informe_aplicacion_t informe;
            operaciones_conectadas_t op = {&gpio, leer_red, reloj_control, invalidar_red,
                                           escribir_fase};
            bool aplicada_ok = aplicacion_conectada(&guardia, &controlador, op, &informe);
#else
            luces_semaforo_t luces;
            uint64_t antes_gpio = ahora_ms();
            bool aplicada_ok = controlador_luces(controlador.estado, &luces) &&
                               semaforo_gpio_aplicar(&gpio, luces);
            if (aplicada_ok) {
                controlador.inicio_ms = ahora_ms();
            }
#endif
            if (!aplicada_ok) {
                ESP_LOGE(TAG, "Fallo GPIO/estado: bloquear y pedir rojos");
                semaforo_gpio_seguro(&gpio);
                controlador.estado = ESTADO_SEGURO;
                vTaskDelete(NULL);
                return;
            }
            uint64_t aplicada = ahora_ms();
#ifdef CONFIG_SEMAFORO_CONECTADO
            if (informe.interrumpido) {
                ESP_LOGW(
                    TAG,
                    "Vigencia interrumpida al aplicar GPIO; verde aplicado=%u; despeje completo",
                    (unsigned)informe.verde_aplicado);
            }
            if (informe.verde_aplicado && informe.interrumpido) {
                unsigned carril = informe.estado_verde == VERDE_CARRIL_1 ? 0 : 1;
                fin_verde[carril] = controlador.inicio_ms;
                tiene_fin[carril] = true;
            }
#endif
            ESP_LOGI(TAG, "%s -> %s duracion real fase=%" PRIu64 " ms",
                     controlador_nombre(anterior), controlador_nombre(controlador.estado),
                     aplicada - inicio_anterior);
            registrar_demanda(&controlador, aplicada);
            if (anterior == VERDE_CARRIL_1 || anterior == VERDE_CARRIL_2) {
                int carril = anterior == VERDE_CARRIL_1 ? 0 : 1;
                fin_verde[carril] = antes_gpio;
                tiene_fin[carril] = true;
            }
            if (controlador.estado == VERDE_CARRIL_1 || controlador.estado == VERDE_CARRIL_2) {
                int carril = controlador.estado == VERDE_CARRIL_1 ? 0 : 1;
                ESP_LOGI(TAG, "Carril %d verde seleccionado=%" PRIu32 " ms favorecido=%u motivo=%s",
                         carril + 1, controlador.verde_seleccionado_ms,
                         controlador.decision.carril_favorecido,
                         !controlador.adaptativo                  ? "convencional"
                         : !controlador.demanda_aplicada_valida   ? "sin demanda vigente"
                         : controlador.decision.carril_favorecido ? "diferencia supera umbral"
                                                                  : "demanda equilibrada");
                if (tiene_fin[carril]) {
                    uint64_t intervalo = aplicada - fin_verde[carril];
                    ESP_LOGI(TAG, "Carril %d intervalo observado sin verde=%" PRIu64 " ms",
                             carril + 1, intervalo);
                    if (intervalo > CONFIG_SEMAFORO_OBJETIVO_SIN_VERDE_MS) {
                        ESP_LOGW(
                            TAG,
                            "Intervalo supera objetivo nominal; no es garantia de tiempo real");
                    }
                } else {
                    ESP_LOGI(TAG, "Carril %d sin intervalo previo medible", carril + 1);
                }
            }
        }
#ifdef CONFIG_SEMAFORO_CONECTADO
        receptor_udp_estado_controlador((uint8_t)controlador.estado, guardia.generacion);
#endif
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
/* 7. Simulador: publica demanda; no controla salidas ni tiempos de fases. */
#ifdef CONFIG_SEMAFORO_SIMULAR_DEMANDA
static void tarea_simulacion(void *parametro)
{
    QueueHandle_t cola = (QueueHandle_t)parametro;
    uint64_t secuencia = 0;
    typedef struct {
        int32_t n1, n2;
        bool valida;
        uint32_t pausa_ms;
        const char *nombre;
    } escenario_t;
    static const escenario_t escenarios[] = {
        {0, 0, true, 2000, "vacio medido"},
        {3, 3, true, 2000, "equilibrio"},
        {4, 1, true, 2000, "carril 1"},
        {1, 5, true, 2000, "carril 2"},
        {2, 0, true, 2000, "diferencia creciente 2"},
        {3, 0, true, 2000, "diferencia creciente 3"},
        {5, 0, true, 2000, "saturacion"},
        {10, 0, true, 2000, "congestion sostenida 1"},
        {10, 0, true, 2000, "congestion sostenida 2"},
        {10, 0, true, 2000, "congestion sostenida 3"},
        {10, 0, true, 2000, "congestion sostenida 4"},
        {0, 10, true, 2000, "cambio durante verde"},
        {0, 0, false, 2000, "invalidacion explicita"},
        {4, 1, true, 10000, "interrupcion de actualizaciones"}};
    unsigned indice = 0;
    for (;;) {
        const escenario_t *escenario = &escenarios[indice];
        demanda_vehicular_t d = {.n1 = escenario->n1,
                                 .n2 = escenario->n2,
                                 .secuencia = ++secuencia,
                                 .recibida_ms = (uint64_t)esp_timer_get_time() / 1000,
                                 .valida = escenario->valida};
        ESP_LOGI("simulador", "SIMULADO: %s; pausa siguiente=%" PRIu32 " ms", escenario->nombre,
                 escenario->pausa_ms);
        xQueueOverwrite(cola, &d);
        vTaskDelay(pdMS_TO_TICKS(escenario->pausa_ms));
        indice = (indice + 1) % (sizeof escenarios / sizeof escenarios[0]);
    }
}
#endif

/* 8. Punto de entrada ESP-IDF. La inicializacion GPIO queda en el propietario:
 * trasladarla aqui dividiria la responsabilidad de las salidas entre tareas. */
void app_main(void)
{
    if (xTaskCreate(tarea_controlador, "controlador_semaforos", 5120, NULL, 5, NULL) != pdPASS) {
        ESP_LOGE(TAG, "No se pudo crear propietario; GPIO sin inicializar");
    }
}
