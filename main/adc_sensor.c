#include "adc_sensor.h"
#include "esp_system.h"
#include "stdio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/adc.h"
#include "esp_adc_cal.h"
#include <stdlib.h>

// Función para inicializar el ADC
void init_adc() {
    adc1_config_width(ADC_WIDTH_BIT_12); // Configura ADC a 12 bits
    adc1_config_channel_atten(PHOTORESISTOR_ADC_CHANNEL, ADC_ATTEN_DB_6);  // Atenuación de 6dB para la fotorresistencia
    adc1_config_channel_atten(MQ135_ADC_CHANNEL, ADC_ATTEN_DB_12);           // Atenuación de 6dB para el MQ135
}

// Función para leer el voltaje de un canal ADC
uint32_t read_adc_voltage(adc1_channel_t channel) {
    esp_adc_cal_characteristics_t *adc_chars = calloc(1, sizeof(esp_adc_cal_characteristics_t));
    esp_adc_cal_characterize(ADC_UNIT_1, ADC_ATTEN_DB_6, ADC_WIDTH_BIT_12, DEFAULT_VREF, adc_chars);

    uint32_t adc_reading = 0;
    for (int i = 0; i < NO_OF_SAMPLES; i++) {
        adc_reading += adc1_get_raw(channel);
    }
    adc_reading /= NO_OF_SAMPLES;

    uint32_t voltage = esp_adc_cal_raw_to_voltage(adc_reading, adc_chars);
    free(adc_chars);
    return voltage;
}

// Función para mostrar el porcentaje de luz de la fotorresistencia
float print_light_percentage() {
    uint32_t photoresistor_voltage = read_adc_voltage(PHOTORESISTOR_ADC_CHANNEL);
    printf("Voltaje de la fotorresistencia: %u mV\n", (unsigned int)photoresistor_voltage);
    float light_percentage = (float)photoresistor_voltage / 1866 * 100;
    printf("Porcentaje de luz: %.2f%%\n", light_percentage);
    return light_percentage;
}

// Función para mostrar los datos del sensor MQ135
float print_mq135_data() {
    int mq135_raw_value = adc1_get_raw(MQ135_ADC_CHANNEL);
    printf("Valor analógico del sensor MQ135: %d\n", mq135_raw_value);

    float mq135_voltage = mq135_raw_value * (3.3 / 4095.0);
    printf("Voltaje en el MQ135: %.2f V\n", mq135_voltage);

    float ppm_CO2 = mq135_raw_value * CALIBRATION_FACTOR;
    printf("Concentración aproximada de CO2: %.2f ppm\n", ppm_CO2);

    if (mq135_raw_value == 4095) {
        printf("Advertencia: El valor del ADC para el MQ135 está al máximo (4095), verifica la conexión y el sensor.\n");
    }
    return ppm_CO2;
}
