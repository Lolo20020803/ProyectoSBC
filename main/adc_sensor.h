/*
 * adc_sensor.h
 *
 *  Created on: 11 dic 2024
 *      Author: user2
 */

#ifndef MAIN_ADC_SENSOR_H_
#define MAIN_ADC_SENSOR_H_

#include "driver/adc.h"
#include "esp_adc_cal.h"

#define DEFAULT_VREF        1100        // Valor de referencia por defecto en mV
#define NO_OF_SAMPLES       64          // Promediar sobre 64 muestras
#define CALIBRATION_FACTOR  0.01        // Factor de calibración para estimar concentración de CO2

#define PHOTORESISTOR_ADC_CHANNEL ADC1_CHANNEL_6  // Pin GPIO34 para fotorresistencia
#define MQ135_ADC_CHANNEL         ADC1_CHANNEL_7  // Otro canal ADC para el MQ135

void init_adc(void);
uint32_t read_adc_voltage(adc1_channel_t channel);
float print_light_percentage();
float print_mq135_data();

#endif /* MAIN_ADC_SENSOR_H_ */
