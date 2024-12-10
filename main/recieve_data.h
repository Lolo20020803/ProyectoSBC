#ifndef RECIEVE_DATA_H
#define RECIEVE_DATA_H

#include <stdio.h>
#include <string.h>
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "nvs_flash.h"
#include "esp_http_server.h"
#include "lwip/ip4_addr.h"
#include "cJSON.h" 
#include "mqtt_client.h"

// Definición de la macro MIN si no está definida previamente
#ifndef MIN
#define MIN(a, b) ((a) < (b) ? (a) : (b))
#endif

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Maneja las solicitudes HTTP POST para recibir mensajes.
 *
 * Esta función procesa los datos recibidos a través de una solicitud HTTP POST,
 * actualiza el contador de aforo y responde al cliente.
 *
 * @param req Puntero a la estructura de la solicitud HTTP.
 * @return ESP_OK si la operación fue exitosa, ESP_FAIL en caso contrario.
 */
esp_err_t message_post_handler(httpd_req_t *req);

/**
 * @brief Define la URI para manejar solicitudes POST.
 *
 * Esta estructura define la ruta, el método HTTP y el manejador asociado para las solicitudes POST.
 */
extern const httpd_uri_t message_uri;

/**
 * @brief Inicia el servidor web HTTP.
 *
 * Configura y arranca el servidor web, registrando los manejadores para las rutas específicas.
 *
 * @return Un handle al servidor HTTP iniciado si fue exitoso, NULL en caso contrario.
 */
httpd_handle_t start_webserver(void);

/**
 * @brief Inicializa y configura el cliente MQTT.
 *
 * Esta función configura el cliente MQTT con los parámetros necesarios,
 * registra los eventos y comienza la conexión.
 */
void mqtt_app_start(void);


/**
 * @brief Contador de aforo de personas.
 *
 * Variable global que mantiene el conteo actual de personas en el aforo.
 */
extern int contadorAforo;

/**
 * @brief Handle del cliente MQTT.
 *
 * Variable global que mantiene el handle del cliente MQTT activo.
 */
extern esp_mqtt_client_handle_t client;

/**
 * @brief Estado de conexión MQTT.
 *
 * Variable global que indica si el ESP32 está conectado al broker MQTT.
 */
extern bool connected;

#ifdef __cplusplus
}
#endif

#endif // WIFI_H
