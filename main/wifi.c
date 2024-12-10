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
static const char *TAG = "wifi_station";
httpd_handle_t server = NULL;
const char *form_html =
    "<html><body><form action=\"/submit\" method=\"POST\">"
            "SSID: <input type=\"text\" name=\"ssid\"><br>"
            "Password: <input type=\"password\" name=\"password\"><br>"
        "<input type=\"submit\" value=\"Submit\">"
    "</form></body></html>";

void wifi_initialize();
esp_err_t form_get_handler(httpd_req_t *req);
esp_err_t form_post_handler(httpd_req_t *req);
void start_webserver_ap();
void stop_webserver();
void replace_dollar(char *str);
void inicio_wifi();

void inicio_wifi(){
	esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    // Inicializar el event loop
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    wifi_initialize();
    ESP_LOGI(TAG, "ESP32 configurado como puerto serial y Wi-Fi inicializado");
    //ESP_ERROR_CHECK(init_spiffs());
    start_webserver_ap();
}

void wifi_initialize(){
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    esp_netif_init();  // Inicializar la biblioteca de red
    esp_netif_t *ap_netif = esp_netif_create_default_wifi_ap();

    wifi_config_t wifi_config = {
        .ap = {
            .ssid = "ESP32-H2",             // Nombre del Wi-Fi (SSID)
            .ssid_len = strlen("ESP32-H2"), // Longitud del SSID
            .password = "hola12345",         // Contraseña
            .max_connection = 10,  // Número máximo de conexiones
               .authmode =WIFI_AUTH_WPA2_PSK ,
               .channel = 6,
            //.authmode = WIFI_AUTH_WPA_WPA2_PSK,  // Modo de autenticación
        },
    };

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    esp_netif_dhcps_start(ap_netif);


}


void start_webserver_ap() {
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    ESP_ERROR_CHECK(httpd_start(&server, &config));

    // Manejar la raíz con el formulario HTML
    httpd_uri_t uri_form = {
        .uri       = "/",
        .method    = HTTP_GET,
        .handler   = form_get_handler,
        .user_ctx  = NULL
    };

    // Manejar el formulario de envío
    httpd_uri_t uri_submit = {
        .uri       = "/submit",
        .method    = HTTP_POST,
        .handler   = form_post_handler,
        .user_ctx  = NULL
    };

    httpd_register_uri_handler(server, &uri_form);
    httpd_register_uri_handler(server, &uri_submit);
}

void stop_webserver() {
    httpd_stop(server);
    ESP_LOGE(TAG,"Servidor en pausa");
}

// Manejar solicitudes GET
esp_err_t form_get_handler(httpd_req_t *req) {
    httpd_resp_send(req, form_html, strlen(form_html));
    return ESP_OK;
}

// Manejar solicitudes POST
esp_err_t form_post_handler(httpd_req_t *req) {
    char buf[1024];  // Aumentar el tamaño del buffer
    int ret, total_len = 0;

    // Leer el cuerpo de la solicitud
    while ((ret = httpd_req_recv(req, buf + total_len, sizeof(buf) - total_len)) > 0) {
        total_len += ret;
        // Verificar si hemos alcanzado el tamaño máximo esperado
        if (total_len >= sizeof(buf) - 1) {
            ESP_LOGE(TAG, "Buffer overflow. Request is too large.");
            httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Request too large");
            return ESP_FAIL;
        }
    }

    // Manejar errores de lectura
    if (ret < 0) {
        ESP_LOGE(TAG, "Failed to receive request");
        return ESP_FAIL;
    }

    // Procesar los datos del formulario
    buf[total_len] = '\0';  // Terminar la cadena

    char *ssid_start = strstr(buf, "ssid=");
    char *password_start = strstr(buf, "password=");

    if (ssid_start && password_start) {
        ssid_start += 5;  // Mover el puntero después de "ssid="
        password_start += 9;  // Mover el puntero después de "password="

        // Extraer SSID y contraseña
        char ssid[32];
        char password[32];

        sscanf(ssid_start, "%31[^&]", ssid);
        sscanf(password_start, "%31s", password);
        wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
        ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    // Crea un objeto de red
        esp_netif_init();
        esp_netif_create_default_wifi_sta();

		replace_dollar(password);
        // Cambiar al modo Station
        ESP_LOGI(TAG, "Cambiando a modo Station y conectando a la red: %s", password);

        // Detener el modo AP
        ESP_ERROR_CHECK(esp_wifi_stop());

        // Configurar en modo Station
        wifi_config_t wifi_config = {
            .sta = {
                .ssid = "",
                .password = "",
            },
        };
        

        ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA)); // Cambiar a modo Station

        // Asignar el SSID y la contraseña de forma segura
        strncpy((char *)wifi_config.sta.ssid, ssid, sizeof(wifi_config.sta.ssid) - 1);
        wifi_config.sta.ssid[sizeof(wifi_config.sta.ssid) - 1] = '\0'; // Asegurar terminación con null

        strncpy((char *)wifi_config.sta.password, password, sizeof(wifi_config.sta.password) - 1);
        wifi_config.sta.password[sizeof(wifi_config.sta.password) - 1] = '\0'; // Asegurar terminación con null

        // Luego puedes configurar el wifi con
        ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));




        ESP_ERROR_CHECK(esp_wifi_start()); // Iniciar Wi-Fi en modo Station
        ESP_ERROR_CHECK(esp_wifi_connect()); // Intentar conectarse a la red

    }

    return ESP_OK;
}

void replace_dollar(char *str) {
    char *ptr;
    while ((ptr = strstr(str, "%24")) != NULL) {
        *ptr = '$'; // Reemplaza % por $
        memmove(ptr + 1, ptr + 3, strlen(ptr + 3) + 1); // Mueve el resto del string
    }
}

