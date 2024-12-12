#include "wifi.h"


//void write_credencials();
mosquitto_pub -d -q 1 -h demo.thingsboard.io -p 1883 -t v1/devices/me/telemetry -u "BWmHVi7XYSP5onYzBcUK" -m "{contadorAforo:25,nivelLuz}"
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

#ifndef MIN
#define MIN(a, b) ((a) < (b) ? (a) : (b))
#endif


static const char *TAG = "HTTP_SERVER";
int contadorAforo = 0;
static const char *token = "BWmHVi7XYSP5onYzBcUK";
esp_mqtt_client_handle_t client;
bool connected = false;
float porcentajeLuz,porcentajeAire;
floa
static void send_data(void *pvParameters) {
    while (1) {
		 
        cJSON *root = cJSON_CreateObject();
        cJSON_AddNumberToObject(root, "contadorAforo", contadorAforo);
        cJSON_AddNumberToObject(root, "porcentajeLuz", porcentajeLuz);
        cJSON_AddNumberToObject(root, "porcentajeAire", porcentajeAire);
        char *post_data = cJSON_PrintUnformatted(root);

        int msg_id = esp_mqtt_client_publish(client, "v1/devices/me/telemetry", post_data, 0, 1, 0);
        ESP_LOGI(TAG, "Sent publish successful, msg_id=%d", msg_id);

        cJSON_Delete(root);
        free(post_data);
        vTaskDelay(pdMS_TO_TICKS(1000));  // Retraso de 500 milisegundos
    }
}

static void log_error_if_nonzero(const char *message, int error_code)
{
    if (error_code != 0) {
        ESP_LOGE(TAG, "Last error %s: 0x%x", message, error_code);
    }
}

static void mqtt_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data)
{
    ESP_LOGD(TAG, "Event dispatched from event loop base=%s, event_id=%" PRIi32 "", base, event_id);
    esp_mqtt_event_handle_t event = event_data;
    client = event->client;
    int msg_id;
    switch ((esp_mqtt_event_id_t)event_id) {
    case MQTT_EVENT_CONNECTED:
        ESP_LOGI(TAG, "MQTT_EVENT_CONNECTED");
        xTaskCreate(send_data, "send_data_task", 2048, NULL, 5, NULL);
        msg_id = esp_mqtt_client_publish(client, "/topic/qos1", "data_3", 0, 1, 0);
        ESP_LOGI(TAG, "sent publish successful, msg_id=%d", msg_id);

        msg_id = esp_mqtt_client_subscribe(client, "/topic/qos0", 0);
        ESP_LOGI(TAG, "sent subscribe successful, msg_id=%d", msg_id);

        msg_id = esp_mqtt_client_subscribe(client, "/topic/qos1", 1);
        ESP_LOGI(TAG, "sent subscribe successful, msg_id=%d", msg_id);

        msg_id = esp_mqtt_client_unsubscribe(client, "/topic/qos1");
        ESP_LOGI(TAG, "sent unsubscribe successful, msg_id=%d", msg_id);
       
        break;
    case MQTT_EVENT_DISCONNECTED:
        ESP_LOGI(TAG, "MQTT_EVENT_DISCONNECTED");
        break;

    case MQTT_EVENT_SUBSCRIBED:
        ESP_LOGI(TAG, "MQTT_EVENT_SUBSCRIBED, msg_id=%d", event->msg_id);
        msg_id = esp_mqtt_client_publish(client, "/topic/qos0", "data", 0, 0, 0);
        ESP_LOGI(TAG, "sent publish successful, msg_id=%d", msg_id);
        break;
    case MQTT_EVENT_UNSUBSCRIBED:
        ESP_LOGI(TAG, "MQTT_EVENT_UNSUBSCRIBED, msg_id=%d", event->msg_id);
        break;
    case MQTT_EVENT_PUBLISHED:
    	
        ESP_LOGI(TAG, "MQTT_EVENT_PUBLISHED, msg_id=%d", event->msg_id);
        break;
    case MQTT_EVENT_DATA:
        ESP_LOGI(TAG, "MQTT_EVENT_DATA");
        printf("TOPIC=%.*s\r\n", event->topic_len, event->topic);
        printf("DATA=%.*s\r\n", event->data_len, event->data);
        break;
    case MQTT_EVENT_ERROR:
        ESP_LOGI(TAG, "MQTT_EVENT_ERROR");
        if (event->error_handle->error_type == MQTT_ERROR_TYPE_TCP_TRANSPORT) {
            log_error_if_nonzero("reported from esp-tls", event->error_handle->esp_tls_last_esp_err);
            log_error_if_nonzero("reported from tls stack", event->error_handle->esp_tls_stack_err);
            log_error_if_nonzero("captured as transport's socket errno",  event->error_handle->esp_transport_sock_errno);
            ESP_LOGI(TAG, "Last errno string (%s)", strerror(event->error_handle->esp_transport_sock_errno));

        }
        break;
    default:
        ESP_LOGI(TAG, "Other event id:%d", event->event_id);
        break;
    }
}
static void start_mqtt_send_thingsboard(void){
	ESP_LOGI(TAG,"MQTT starting");
	 esp_mqtt_client_config_t mqtt_cfg = {
        .broker.address.uri = "mqtt://demo.thingsboard.io",
        .broker.address.port = 1883,
        .credentials.username = token, // Agrega el token como username
    };

    client = esp_mqtt_client_init(&mqtt_cfg);
    esp_mqtt_client_register_event(client, ESP_EVENT_ANY_ID, mqtt_event_handler, NULL);
    esp_mqtt_client_start(client);
    ESP_LOGI(TAG,"MQTT star");
}

/* Handler del POST */
esp_err_t message_post_handler(httpd_req_t *req)
{
    char buf[128];
    int ret;

    // Leer el cuerpo del mensaje
    ret = httpd_req_recv(req, buf, MIN(req->content_len, sizeof(buf) - 1));
    if (ret <= 0) {
        if (ret == HTTPD_SOCK_ERR_TIMEOUT) {
            httpd_resp_send_408(req);
        }
        return ESP_FAIL;
    }

    buf[ret] = '\0'; // Terminar el string recibido
    ESP_LOGI(TAG, "Mensaje recibido: %s", buf);

    // Parsear el JSON recibido
    cJSON *json = cJSON_Parse(buf);
    if (json == NULL) {
        ESP_LOGE(TAG, "Error al parsear el JSON");
        const char *resp = "Error al parsear el JSON";
        httpd_resp_send(req, resp, strlen(resp));
        return ESP_FAIL;
    }
    cJSON *entrando = cJSON_GetObjectItem(json, "entrando");
    if (!cJSON_IsString(entrando)) {
        ESP_LOGE(TAG, "El campo 'entrando' no es una cadena válida");
        const char *resp = "El campo 'entrando' no es una cadena válida";
        httpd_resp_send(req, resp, strlen(resp));
        cJSON_Delete(json);
        return ESP_FAIL;
    }

    // Procesar el valor de "entrando"
    const char *entrando_str = cJSON_GetStringValue(entrando);

    if (strcmp(entrando_str, "True") == 0) {
        contadorAforo += 1;
        ESP_LOGI(TAG, "El valor de 'entrando' es true");
    } else if (strcmp(entrando_str, "False") == 0) {
        contadorAforo -= 1;
        ESP_LOGI(TAG, "El valor de 'entrando' es false");
        if (contadorAforo < 0) {
            contadorAforo = 0;
        }
        
    } else {
        ESP_LOGE(TAG, "El valor de 'entrando' no es 'true' ni 'false'");
        const char *resp = "El valor de 'entrando' debe ser 'true' o 'false'";
        httpd_resp_send(req, resp, strlen(resp));
        cJSON_Delete(json);
        return ESP_FAIL;
    }
    const char *resp = "Todo bien";
    httpd_resp_send(req, resp, strlen(resp));
    cJSON_Delete(json);
    ESP_LOGI(TAG, "El contador de aforo es: %d", contadorAforo);
    return ESP_OK;
}

/* URI para el POST */
httpd_uri_t message_uri = {
    .uri       = "/message",
    .method    = HTTP_POST,
    .handler   = message_post_handler,
    .user_ctx  = NULL
};

/* Iniciar servidor HTTP */
httpd_handle_t start_webserver(void)
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 8080; // Cambia este valor al puerto deseado


    ESP_LOGI(TAG, "Iniciando servidor en el puerto: '%d'", config.server_port);
    httpd_handle_t server = NULL;
    if (httpd_start(&server, &config) == ESP_OK) {
        httpd_register_uri_handler(server, &message_uri);
        return server;
    }

    ESP_LOGE(TAG, "Error al iniciar el servidor!");
    return NULL;
}



void app_main(void)
{
    isConnected = false;
	esp_log_level_set("*", ESP_LOG_INFO);
    esp_log_level_set("mqtt_client", ESP_LOG_VERBOSE);
    esp_log_level_set("mqtt_example", ESP_LOG_VERBOSE);
    esp_log_level_set("transport_base", ESP_LOG_VERBOSE);
    esp_log_level_set("esp-tls", ESP_LOG_VERBOSE);
    esp_log_level_set("transport", ESP_LOG_VERBOSE);
    esp_log_level_set("outbox", ESP_LOG_VERBOSE);
    inicio_wifi();
    
    start_webserver() ;
    start_mqtt_send_thingsboard();
}
