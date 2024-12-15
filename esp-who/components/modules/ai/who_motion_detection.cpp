#include "who_motion_detection.hpp"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_camera.h"
#include "driver/i2s.h"
#include "dl_image.hpp"
#define SERVER_URL "http://192.168.84.46:8080/message"
#define I2S_NUM I2S_NUM_0  // Definir el puerto I2S como I2S_NUM_0
#define SAMPLE_RATE 16000   // Frecuencia de muestreo en Hz
#define I2S_READ_LEN 1024   // Longitud de lectura de cada vez
static const char *TAG = "motion_detection";

static QueueHandle_t xQueueFrameI = NULL;
static QueueHandle_t xQueueEvent = NULL;
static QueueHandle_t xQueueFrameO = NULL;
static QueueHandle_t xQueueResult = NULL;
uint32_t previous_moving_points=0; // Guardar el número de puntos en movimiento del fotograma anterior
int32_t moving_point_number;

void i2s_init() {
    // Configuración del I2S
    i2s_config_t i2s_config = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX), // Modo maestro, solo recepción
        .sample_rate = SAMPLE_RATE,            // Frecuencia de muestreo
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT, // 16 bits por muestra
        .channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT,  // Solo un canal, ya que el micrófono es mono
        .communication_format = I2S_COMM_FORMAT_I2S_MSB, // MSB
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1, // Interrupción a nivel 1
        .dma_buf_count = 8, // Número de buffers de DMA
        .dma_buf_len = I2S_READ_LEN, // Tamaño del buffer
    };

    // Configuración de pines (ajusta según tu configuración de hardware)
    i2s_pin_config_t pin_config = {
        .bck_io_num = 26, // Pin de reloj de bit (BCK)
        .ws_io_num = 25,  // Pin de selección de palabra (WS)
        .data_out_num = I2S_PIN_NO_CHANGE, // No usamos salida de datos
        .data_in_num = 22,  // Pin de entrada de datos (SD)
    };

    // Inicialización del I2S
    ESP_ERROR_CHECK(i2s_driver_install(I2S_NUM, &i2s_config, 0, NULL));
    ESP_ERROR_CHECK(i2s_set_pin(I2S_NUM, &pin_config));
}

void read_audio_data() {
    int16_t audio_buffer[I2S_READ_LEN];  // Buffer para almacenar datos de audio
    size_t bytes_read;

    // Leer los datos del micrófono
    ESP_ERROR_CHECK(i2s_read(I2S_NUM, (void *)audio_buffer, sizeof(audio_buffer), &bytes_read, portMAX_DELAY));
     audio_buffer;
    // Procesar los datos de audio (como ruido)
    /*for (int i = 0; i < bytes_read / 2; i++) {
        int16_t sample = audio_buffer[i];
        // Aquí puedes analizar la señal de ruido (por ejemplo, calcular el nivel de volumen)
        printf("Muestra de audio %d: %d\n", i, sample);
    }*/
}


static bool gEvent = true;
void send_json_message(const char *message)
{

    // Configurar el cliente HTTP
    esp_http_client_config_t config = {
        .url = SERVER_URL,
        .method = HTTP_METHOD_POST,
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);

    // Crear el JSON
    char json_data[128];
    snprintf(json_data, sizeof(json_data), "{\"entrando\": \"%s\"}", message);

    // Configurar encabezados y cuerpo de la solicitud
    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, json_data, strlen(json_data));

    // Enviar la solicitud
    esp_err_t err = esp_http_client_perform(client);

    if (err == ESP_OK)
    {
        ESP_LOGI(TAG, "Mensaje enviado exitosamente. Código de respuesta: %d", esp_http_client_get_status_code(client));
    }
    else
    {
        ESP_LOGE(TAG, "Error al enviar mensaje: %s", esp_err_to_name(err));
    }
    previous_moving_points=0;
    moving_point_number=0;
    ESP_LOGE(TAG,"%i",previous_moving_points);
    vTaskDelay(1000 / portTICK_PERIOD_MS);
    // Limpiar el cliente HTTP
    esp_http_client_cleanup(client);
    
}

static void task_process_handler(void *arg)
{
    camera_fb_t *frame1 = NULL;
    camera_fb_t *frame2 = NULL;
    camera_fb_t *frame3 = NULL;
    int16_t audiodata;
    while (true)
    {
        if (gEvent)
        {
            bool is_moved = false;
            bool is_approaching = false; // Indica si el objeto se está acercando
            if (xQueueReceive(xQueueFrameI, &(frame1), portMAX_DELAY))
            {
                if (xQueueReceive(xQueueFrameI, &(frame2), portMAX_DELAY))
                {
                    // Calcular el número de puntos en movimiento
                    moving_point_number = dl::image::get_moving_point_number(
                        (uint16_t *)frame1->buf, 
                        (uint16_t *)frame2->buf, 
                        frame1->height, 
                        frame1->width, 
                        8, 15);

                    if (moving_point_number > 50)
                    {
                        ESP_LOGE(TAG,"%i",previous_moving_points);
                        ESP_LOGI(TAG, "Something moved! Moving points: %d", moving_point_number);
                        dl::image::draw_filled_rectangle(
                            (uint16_t *)frame2->buf, 
                            frame2->height, 
                            frame2->width, 
                            0, 
                            0, 
                            20, 
                            20);

                        is_moved = true;
                        
                        // Comparar con el número de puntos del fotograma anterior
                        if (previous_moving_points > 0)
                        {
                            if (moving_point_number > previous_moving_points)
                            {
                                ESP_LOGI(TAG, "Object is approaching!");
                                read_audio_data();
                                //printf("%d",audiodata[0])
                                send_json_message("True");
                                is_approaching = true;
                            }
                            else if (moving_point_number < previous_moving_points)
                            {
                                ESP_LOGI(TAG, "Object is moving away!");
                                send_json_message("False");
                                is_approaching = false;
                            }
                            else
                            {
                                ESP_LOGI(TAG, "Object is stationary relative to the camera.");
                            }
                        }

                        // Guardar el número de puntos en movimiento para el próximo análisis
                        previous_moving_points = moving_point_number;
                    }
                }
                vTaskDelay(750 / portTICK_PERIOD_MS);
            }

            if (xQueueFrameO)
            {
                esp_camera_fb_return(frame1);
                xQueueSend(xQueueFrameO, &frame2, portMAX_DELAY);
                xQueueSend(xQueueFrameO, &frame3, portMAX_DELAY);
            }
            else
            {
                esp_camera_fb_return(frame1);
                esp_camera_fb_return(frame2);
                esp_camera_fb_return(frame3);
            }

            if (xQueueResult)
            {
                // Empaquetar ambos resultados: movimiento y dirección
                struct {
                    bool moved;
                    bool approaching;
                } result = { is_moved, is_approaching };

                xQueueSend(xQueueResult, &result, portMAX_DELAY);
            }
        }

    }
}




static void task_event_handler(void *arg)
{
    while (true)
    {
        xQueueReceive(xQueueEvent, &(gEvent), portMAX_DELAY);
    }
}


void register_motion_detection(QueueHandle_t frame_i, QueueHandle_t event,
                               QueueHandle_t result, QueueHandle_t frame_o)
{
    xQueueFrameI = frame_i;
    xQueueFrameO = frame_o;
    xQueueEvent = event;
    xQueueResult = result;
    i2s_init();
    xTaskCreatePinnedToCore(task_process_handler, TAG, 4 * 1024, NULL, 5, NULL, 1);
    if (xQueueEvent)
        xTaskCreatePinnedToCore(task_event_handler, TAG, 4 * 1024, NULL, 5, NULL, 1);
}
