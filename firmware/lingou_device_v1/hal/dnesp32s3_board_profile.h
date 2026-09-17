#pragma once

#include <driver/gpio.h>

#include "lingou_hal_contract.h"

namespace lingou::boards::dnesp32s3 {

inline constexpr gpio_num_t LED_PIN = GPIO_NUM_18;
inline constexpr int LED_COUNT = 24;
inline constexpr gpio_num_t FSR_PIN = GPIO_NUM_16;
inline constexpr gpio_num_t MIC_BCLK_PIN = GPIO_NUM_5;
inline constexpr gpio_num_t MIC_WS_PIN = GPIO_NUM_7;
inline constexpr gpio_num_t MIC_DIN_PIN = GPIO_NUM_4;
inline constexpr gpio_num_t SPK_BCLK_PIN = GPIO_NUM_6;
inline constexpr gpio_num_t SPK_LRC_PIN = GPIO_NUM_15;
inline constexpr gpio_num_t SPK_DOUT_PIN = GPIO_NUM_17;

inline constexpr int MIC_SAMPLE_RATE = 16000;
inline constexpr int SPEAKER_SAMPLE_RATE = 24000;
inline constexpr int MIC_FRAME_SAMPLES = 320;
inline constexpr int SPEAKER_BLOCK_SAMPLES = 256;

inline constexpr hal::AudioFormat MICROPHONE_FORMAT = {
    .sample_rate_hz = MIC_SAMPLE_RATE,
    .channels = 1,
    .sample_width_bytes = 2,
    .frame_duration_ms = 20,
    .max_frame_bytes = MIC_FRAME_SAMPLES * 2,
};

inline constexpr hal::AudioFormat SPEAKER_FORMAT = {
    .sample_rate_hz = SPEAKER_SAMPLE_RATE,
    .channels = 1,
    .sample_width_bytes = 2,
    .frame_duration_ms = 0,
    .max_frame_bytes = 4096,
};

inline constexpr bool VALIDATED_AEC = false;

static_assert(MICROPHONE_FORMAT.max_frame_bytes == 640);
static_assert(SPEAKER_FORMAT.max_frame_bytes == 4096);

}  // namespace lingou::boards::dnesp32s3
