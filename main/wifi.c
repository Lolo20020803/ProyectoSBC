#include <stdio.h>
#include <stdbool.h>
#include <string.h>
#include <unistd.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_wifi.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_http_server.h"
#include "esp_spiffs.h"
#include "wifi.h"
#include <sys/stat.h> // Para struct stat y la función stat

static EventGroupHandle_t wifi_event_group;
const int CONNECTED_BIT = BIT0;  // Bit para indicar conexión exitosa

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
void startStation();
extern bool isConnected = false;
bool existe = false;
const char *file_path = "/spiffs/credenciales.txt";
char ssid[32];
char password[32];

static void wifi_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data) {
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        ESP_LOGI(TAG, "Wi-Fi STA iniciado, conectando...");
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGI(TAG, "Desconectado de la red Wi-Fi, intentando reconectar...");
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *) event_data;
        ESP_LOGI(TAG, "Dirección IP obtenida: " IPSTR, IP2STR(&event->ip_info.ip));
        xEventGroupSetBits(wifi_event_group, CONNECTED_BIT);
    }
}

void init_spiffs() {
    esp_vfs_spiffs_conf_t conf = {
        .base_path = "/spiffs",         // Ruta base para montar SPIFFS
        .partition_label = NULL,       // Usa la partición etiquetada como "spiffs"
        .max_files = 5,                // Número máximo de archivos abiertos simultáneamente
        .format_if_mount_failed = true // Formatear si el montaje falla
    };

    esp_err_t ret = esp_vfs_spiffs_register(&conf);

    if (ret != ESP_OK) {
        if (ret == ESP_FAIL) {
            ESP_LOGE("SPIFFS", "Fallo al montar el sistema de archivos");
        } else if (ret == ESP_ERR_NOT_FOUND) {
            ESP_LOGE("SPIFFS", "Partición no encontrada");
        } else {
            ESP_LOGE("SPIFFS", "Error al inicializar SPIFFS (%s)", esp_err_to_name(ret));
        }
        return;
    }

    size_t total = 0, used = 0;
    ret = esp_spiffs_info(NULL, &total, &used);
    if (ret != ESP_OK) {
        ESP_LOGE("SPIFFS", "Error obteniendo información de SPIFFS (%s)", esp_err_to_name(ret));
    } else {
        ESP_LOGI("SPIFFS", "Sistema de archivos montado. Total: %d, Usado: %d", total, used);
    }

    struct stat st;
    if (stat(file_path, &st) == 0) {
        ESP_LOGI(TAG, "El archivo '%s' existe.", file_path);
        FILE *f = fopen(file_path, "r");
        char line[128];
        fgets(line, sizeof(line), f);
        strcpy(ssid, line);
        fgets(line, sizeof(line), f);
        strcpy(password, line);
        fclose(f);
        existe = true;
    } else {
        ESP_LOGW(TAG, "El archivo '%s' no existe.", file_path);
    }
}

void inicio_wifi(){
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    init_spiffs();
	

    // Inicializar el event loop
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    
    if (!existe) {
        wifi_initialize();    
        ESP_LOGI(TAG, "ESP32 configurado como puerto serial y Wi-Fi inicializado");
        //ESP_ERROR_CHECK(init_spiffs());
        start_webserver_ap();
    }else{
        startStation();
    }
    
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
    ESP_LOGI(TAG,"Servidor en pausa");
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
        

        sscanf(ssid_start, "%31[^&]", ssid);
        sscanf(password_start, "%31s", password);
        replace_dollar(password);
        
		FILE *f = fopen(file_path, "w");
        if (f == NULL) {
            ESP_LOGE(TAG, "Fallo al abrir el archivo para escritura");
        } else {
            // Escribir en diferentes líneas
            char buffer[128];
            sprintf(buffer, "%s\n", ssid); // Concatenar ssid con un salto de línea
            fprintf(f, buffer);
            sprintf(buffer, "%s\n", password); // Concatenar ssid con un salto de línea
            fprintf(f, buffer);
            fclose(f);
            ESP_LOGI(TAG, "Archivo escrito correctamente");
        }

        

        ESP_ERROR_CHECK(esp_wifi_stop()); // Detener WiFi
        ESP_ERROR_CHECK(esp_netif_deinit()); // Liberar la interfaz de red
        
        stop_webserver();    
        startStation();
        
    } else {
        ESP_LOGE(TAG, "Datos del formulario incompletos");
    }

    return ESP_OK;
}
void remove_last_char(char *str) {
    size_t len = strlen(str);
    if (len > 0) {
        str[len - 1] = '\0';
    }
}

void startStation(){
        wifi_event_group = xEventGroupCreate();
    if (wifi_event_group == NULL) {
        ESP_LOGE(TAG, "Error al crear el Event Group");
        return; // O maneja el error adecuadamente
    }
    
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg)); // InicialiStatzar WiFi

    ESP_ERROR_CHECK(esp_netif_init());
    
    
    esp_netif_create_default_wifi_sta(); // Crear interfaz de red por defecto para WiFi STA
    

    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, NULL));
    wifi_config_t wifi_config = {
            .sta = {
                .ssid = "",
                .password = "",
            },
        };
    remove_last_char(ssid);
    remove_last_char(password);

    ESP_LOGI(TAG, "Conectando a la red Wi-Fi...");
    ESP_LOGI(TAG, "SSID: %s", ssid);
    ESP_LOGI(TAG, "Password: %s", password);
    
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA)); // Cambiar a modo Station

    strncpy((char *)wifi_config.sta.ssid, ssid, sizeof(wifi_config.sta.ssid) - 1);
    wifi_config.sta.ssid[sizeof(wifi_config.sta.ssid) - 1] = '\0'; // Asegurar terminación con null

    strncpy((char *)wifi_config.sta.password, password, sizeof(wifi_config.sta.password) - 1);
    wifi_config.sta.password[sizeof(wifi_config.sta.password) - 1] = '\0'; // Asegurar terminación con null    
    
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));

    ESP_ERROR_CHECK(esp_wifi_start()); // Iniciar Wi-Fi en modo Station
    ESP_LOGI(TAG, "SSID: %s, Password: %s", ssid, password);
     ESP_LOGI(TAG, "Esperando conexión...");
    EventBits_t bits = xEventGroupWaitBits(wifi_event_group, CONNECTED_BIT, pdFALSE, pdTRUE, portMAX_DELAY);
    if (bits & CONNECTED_BIT    ) {
        ESP_LOGI(TAG, "Conexión Wi-Fi establecida con éxito.");
        isConnected = true;
    } else {
        ESP_LOGE(TAG, "Error inesperado en la conexión Wi-Fi.");
    }
}
void replace_dollar(char *str) {
    char *ptr;
    while ((ptr = strstr(str, "%24")) != NULL) {
        *ptr = '$'; // Reemplaza % por $
        memmove(ptr + 1, ptr + 3, strlen(ptr + 3) + 1); // Mueve el resto del string
    }
}

