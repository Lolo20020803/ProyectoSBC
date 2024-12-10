#ifndef WIFI_H
#define WIFI_H

#include <stdio.h>
#include <stdbool.h>
#include <string.h>
#include <unistd.h>
#include "esp_wifi.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_http_server.h"
#include "esp_spiffs.h"
#include <sys/stat.h> // Para struct stat y la función stat


#ifdef __cplusplus
extern "C" {
#endif

extern bool isConnected;
void inicio_wifi();
/**
 * @brief Inicializa el Wi-Fi en modo Access Point (AP).
 *
 * Esta función configura y arranca el modo AP del ESP32, permitiendo que otros dispositivos se conecten a él.
 */
void wifi_initialize();

/**
 * @brief Maneja las solicitudes HTTP GET para mostrar el formulario HTML.
 *
 * @param req Puntero a la estructura de la solicitud HTTP.
 * @return Código de error ESP_OK si la operación fue exitosa.
 */
esp_err_t form_get_handler(httpd_req_t *req);

/**
 * @brief Maneja las solicitudes HTTP POST cuando se envía el formulario.
 *
 * @param req Puntero a la estructura de la solicitud HTTP.
 * @return Código de error ESP_OK si la operación fue exitosa, o un código de error apropiado en caso contrario.
 */
esp_err_t form_post_handler(httpd_req_t *req);

/**
 * @brief Inicia el servidor web HTTP.
 *
 * Configura y arranca el servidor web, registrando los manejadores para las rutas específicas.
 */
void start_webserver_ap();

/**
 * @brief Detiene el servidor web HTTP.
 *
 * Detiene el servidor web si está en ejecución y registra un mensaje de log.
 */
void stop_webserver();

/**
 * @brief Reemplaza las ocurrencias de "%24" por "$" en una cadena.
 *
 * Esta función es útil para decodificar caracteres especiales en las entradas del formulario.
 *
 * @param str Puntero a la cadena que se modificará.
 */
void replace_dollar(char *str);

/**
 * @brief Punto de entrada principal para la aplicación.
 *
 * Esta función debe ser llamada desde `app_main` en el archivo principal.
 */
void wifi_app_main();

extern httpd_handle_t server;
extern const char *form_html;

#ifdef __cplusplus
}
#endif

#endif // WIFI_MANAGER_H
