#pragma once

#include <Arduino.h>
#include <freertos/FreeRTOS.h>

#include "dnesp32s3_board_profile.h"

#ifndef LINGOU_ENABLE_ESP_SR_AFE
#define LINGOU_ENABLE_ESP_SR_AFE 0
#endif

#ifndef LINGOU_AEC_REFERENCE_DELAY_MS
#define LINGOU_AEC_REFERENCE_DELAY_MS 60
#endif

#ifndef LINGOU_MIC_DIGITAL_GAIN_Q8
#define LINGOU_MIC_DIGITAL_GAIN_Q8 256
#endif

#ifndef LINGOU_MIC_CLIP_LIMIT
#define LINGOU_MIC_CLIP_LIMIT 30000
#endif

#ifndef LINGOU_NS_MODE
#define LINGOU_NS_MODE 1
#endif

#ifndef LINGOU_AGC_GAIN_DB
#define LINGOU_AGC_GAIN_DB 9
#endif

#ifndef LINGOU_AGC_TARGET_DBFS
#define LINGOU_AGC_TARGET_DBFS 3
#endif

#if LINGOU_ENABLE_ESP_SR_AFE
#include <esp_aec.h>
#include <esp_agc.h>
#include <esp_heap_caps.h>
#include <esp_ns.h>
#include <freertos/semphr.h>
#endif

namespace lingou::hal {

inline constexpr char ACOUSTIC_PROFILE_VERSION[] =
    "esp-sr-2.4.6-fd-lowcost-v1";
inline constexpr int ACOUSTIC_SAMPLE_RATE_HZ = 16000;
inline constexpr int ACOUSTIC_OUTPUT_FRAME_SAMPLES = 320;
inline constexpr int AEC_MAX_FRAME_SAMPLES = 512;
inline constexpr int WEBRTC_FRAME_SAMPLES = 160;
inline constexpr size_t REFERENCE_RING_SAMPLES = 4096;
inline constexpr size_t PROCESSED_RING_SAMPLES = 2048;

struct AcousticFrontendConfig {
  const char* profile_version;
  bool enabled;
  bool aec_enabled;
  bool ns_enabled;
  bool agc_enabled;
  int aec_filter_length;
  int reference_delay_ms;
  int microphone_gain_q8;
  int clip_limit;
  int ns_mode;
  int agc_gain_db;
  int agc_target_dbfs;
};

struct AcousticFrontendMetrics {
  uint32_t input_frames;
  uint32_t output_frames;
  uint32_t aec_blocks;
  uint32_t clipped_samples;
  uint32_t reference_overflow_samples;
  uint32_t reference_underflow_samples;
  uint32_t processed_overflow_samples;
  uint32_t processing_failures;
  uint32_t reference_max_depth;
  int aec_frame_samples;
  bool enabled;
  bool active;
};

inline AcousticFrontendConfig BuildAcousticFrontendConfig() {
  const bool enabled = LINGOU_ENABLE_ESP_SR_AFE != 0;
  return {
    .profile_version = ACOUSTIC_PROFILE_VERSION,
    .enabled = enabled,
    .aec_enabled = true,
    .ns_enabled = true,
    .agc_enabled = true,
    .aec_filter_length = 4,
    .reference_delay_ms = LINGOU_AEC_REFERENCE_DELAY_MS,
    .microphone_gain_q8 = enabled ? LINGOU_MIC_DIGITAL_GAIN_Q8 : 512,
    .clip_limit = enabled ? LINGOU_MIC_CLIP_LIMIT : 32767,
    .ns_mode = LINGOU_NS_MODE,
    .agc_gain_db = LINGOU_AGC_GAIN_DB,
    .agc_target_dbfs = LINGOU_AGC_TARGET_DBFS,
  };
}

class EspSrAcousticFrontend {
 public:
  EspSrAcousticFrontend() = default;

  bool Start(const AcousticFrontendConfig& config) {
    config_ = config;
    failure_reason_ = config.enabled ? "not_initialized" : "disabled";
    if (!validateConfig()) {
      failure_reason_ = "invalid_config";
      return false;
    }
    if (!config.enabled) {
      return true;
    }
#if !LINGOU_ENABLE_ESP_SR_AFE
    failure_reason_ = "not_compiled";
    return false;
#else
    if (heap_caps_get_total_size(MALLOC_CAP_SPIRAM) == 0) {
      failure_reason_ = "psram_required";
      return false;
    }
    process_mutex_ = xSemaphoreCreateMutex();
    if (!process_mutex_) {
      failure_reason_ = "process_mutex_allocation_failed";
      return false;
    }

    aec_config_t aecConfig = {
      .mic_num = 1,
      .ref_num = 1,
      .out_num = 1,
      .filter_length = config.aec_filter_length,
      .sample_rate = ACOUSTIC_SAMPLE_RATE_HZ,
      .caps = MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT,
      .mode = AEC_MODE_FD_LOW_COST,
      .nlp_level = AEC_NLP_LEVEL_AGGR,
    };
    aec_handle_ = aec_create_from_config(&aecConfig);
    if (!aec_handle_) {
      failure_reason_ = "aec_initialization_failed";
      Stop();
      return false;
    }
    aec_frame_samples_ = aec_get_chunksize(aec_handle_);
    if (
      aec_frame_samples_ <= 0
      || aec_frame_samples_ > AEC_MAX_FRAME_SAMPLES
    ) {
      failure_reason_ = "unsupported_aec_frame_size";
      Stop();
      return false;
    }
    if (config.ns_enabled) {
      ns_handle_ = ns_pro_create(
        10,
        config.ns_mode,
        ACOUSTIC_SAMPLE_RATE_HZ
      );
      if (!ns_handle_) {
        failure_reason_ = "ns_initialization_failed";
        Stop();
        return false;
      }
    }
    if (config.agc_enabled) {
      agc_handle_ = esp_agc_open(
        AGC_MODE_2,
        ACOUSTIC_SAMPLE_RATE_HZ
      );
      if (!agc_handle_) {
        failure_reason_ = "agc_initialization_failed";
        Stop();
        return false;
      }
      set_agc_config(
        agc_handle_,
        config.agc_gain_db,
        1,
        config.agc_target_dbfs
      );
    }
    active_ = true;
    failure_reason_ = "none";
    resetState(0);
    return true;
#endif
  }

  void Stop() {
    active_ = false;
#if LINGOU_ENABLE_ESP_SR_AFE
    if (agc_handle_) {
      esp_agc_close(agc_handle_);
      agc_handle_ = nullptr;
    }
    if (ns_handle_) {
      ns_destroy(ns_handle_);
      ns_handle_ = nullptr;
    }
    if (aec_handle_) {
      aec_destroy(aec_handle_);
      aec_handle_ = nullptr;
    }
    if (process_mutex_) {
      vSemaphoreDelete(process_mutex_);
      process_mutex_ = nullptr;
    }
    aec_frame_samples_ = 0;
#endif
  }

  bool Active() const {
    return active_;
  }

  const char* ProfileVersion() const {
    return config_.profile_version;
  }

  const char* FailureReason() const {
    return failure_reason_;
  }

  void BeginPlayback(uint32_t generation) {
#if LINGOU_ENABLE_ESP_SR_AFE
    if (!active_) {
      return;
    }
    portENTER_CRITICAL(&reference_mux_);
    reference_generation_ = generation;
    playback_reference_active_ = true;
    reference_delay_pending_ = true;
    reference_head_ = 0;
    reference_tail_ = 0;
    reference_count_ = 0;
    resample_count_ = 0;
    portEXIT_CRITICAL(&reference_mux_);
#else
    (void)generation;
#endif
  }

  void EndPlayback(uint32_t generation) {
#if LINGOU_ENABLE_ESP_SR_AFE
    if (!active_) {
      return;
    }
    portENTER_CRITICAL(&reference_mux_);
    if (generation == reference_generation_) {
      playback_reference_active_ = false;
      reference_delay_pending_ = false;
    }
    portEXIT_CRITICAL(&reference_mux_);
#else
    (void)generation;
#endif
  }

  void Reset(uint32_t generation) {
#if LINGOU_ENABLE_ESP_SR_AFE
    portENTER_CRITICAL(&reference_mux_);
    reference_generation_ = generation;
    playback_reference_active_ = false;
    reference_delay_pending_ = false;
    reference_head_ = 0;
    reference_tail_ = 0;
    reference_count_ = 0;
    resample_count_ = 0;
    portEXIT_CRITICAL(&reference_mux_);

    if (
      process_mutex_
      && xSemaphoreTake(process_mutex_, pdMS_TO_TICKS(20)) == pdTRUE
    ) {
      resetProcessBuffers();
      xSemaphoreGive(process_mutex_);
    } else {
      process_reset_pending_ = true;
    }
#else
    (void)generation;
#endif
  }

  void PushPlayback24k(
      const int16_t* samples,
      size_t sampleCount,
      uint32_t generation) {
#if LINGOU_ENABLE_ESP_SR_AFE
    if (!active_ || !samples || sampleCount == 0) {
      return;
    }
    int16_t downsampled[192];
    size_t downsampledCount = 0;
    portENTER_CRITICAL(&reference_mux_);
    if (
      !playback_reference_active_
      || generation != reference_generation_
    ) {
      portEXIT_CRITICAL(&reference_mux_);
      return;
    }
    if (reference_delay_pending_) {
      const size_t delaySamples = min(
        static_cast<size_t>(
          config_.reference_delay_ms
          * ACOUSTIC_SAMPLE_RATE_HZ
          / 1000
        ),
        REFERENCE_RING_SAMPLES - 1
      );
      for (size_t index = 0; index < delaySamples; ++index) {
        reference_ring_[reference_tail_] = 0;
        reference_tail_ = (
          reference_tail_ + 1
        ) % REFERENCE_RING_SAMPLES;
        ++reference_count_;
      }
      reference_delay_pending_ = false;
    }
    for (size_t index = 0; index < sampleCount; ++index) {
      resample_triplet_[resample_count_++] = samples[index];
      if (resample_count_ == 3) {
        if (downsampledCount + 2 <= 192) {
          downsampled[downsampledCount++] = resample_triplet_[0];
          downsampled[downsampledCount++] = static_cast<int16_t>(
            (
              static_cast<int32_t>(resample_triplet_[1])
              + static_cast<int32_t>(resample_triplet_[2])
            ) / 2
          );
        }
        resample_count_ = 0;
      }
    }
    uint32_t overflowSamples = 0;
    for (size_t index = 0; index < downsampledCount; ++index) {
      if (reference_count_ == REFERENCE_RING_SAMPLES) {
        reference_head_ = (
          reference_head_ + 1
        ) % REFERENCE_RING_SAMPLES;
        --reference_count_;
        ++overflowSamples;
      }
      reference_ring_[reference_tail_] = downsampled[index];
      reference_tail_ = (
        reference_tail_ + 1
      ) % REFERENCE_RING_SAMPLES;
      ++reference_count_;
    }
    const uint32_t referenceDepth = reference_count_;
    portEXIT_CRITICAL(&reference_mux_);
    addMetric(
      &metrics_.reference_overflow_samples,
      overflowSamples
    );
    updateMaxMetric(
      &metrics_.reference_max_depth,
      referenceDepth
    );
#else
    (void)samples;
    (void)sampleCount;
    (void)generation;
#endif
  }

  size_t ProcessMicrophone16k(
      const int16_t* input,
      size_t sampleCount,
      int16_t* output,
      size_t outputCapacity) {
    if (
      !input
      || !output
      || sampleCount != ACOUSTIC_OUTPUT_FRAME_SAMPLES
      || outputCapacity < ACOUSTIC_OUTPUT_FRAME_SAMPLES
    ) {
      addMetric(&metrics_.processing_failures, 1);
      return 0;
    }
    addMetric(&metrics_.input_frames, 1);
    applyGainAndClip(input, microphone_work_, sampleCount);
#if LINGOU_ENABLE_ESP_SR_AFE
    if (active_) {
      if (
        xSemaphoreTake(process_mutex_, pdMS_TO_TICKS(20)) != pdTRUE
      ) {
        addMetric(&metrics_.processing_failures, 1);
        return 0;
      }
      if (process_reset_pending_) {
        resetProcessBuffers();
        process_reset_pending_ = false;
      }
      readReference(reference_work_, sampleCount);
      for (size_t index = 0; index < sampleCount; ++index) {
        aec_mic_[aec_input_count_] = microphone_work_[index];
        aec_reference_[aec_input_count_] = reference_work_[index];
        ++aec_input_count_;
        if (aec_input_count_ == static_cast<size_t>(aec_frame_samples_)) {
          processAecBlock();
          aec_input_count_ = 0;
        }
      }
      size_t produced = 0;
      if (processed_count_ >= ACOUSTIC_OUTPUT_FRAME_SAMPLES) {
        for (
          size_t index = 0;
          index < ACOUSTIC_OUTPUT_FRAME_SAMPLES;
          ++index
        ) {
          output[index] = processed_ring_[processed_head_];
          processed_head_ = (
            processed_head_ + 1
          ) % PROCESSED_RING_SAMPLES;
          --processed_count_;
        }
        produced = ACOUSTIC_OUTPUT_FRAME_SAMPLES;
      }
      xSemaphoreGive(process_mutex_);
      if (produced) {
        addMetric(&metrics_.output_frames, 1);
      }
      return produced;
    }
#endif
    memcpy(output, microphone_work_, sampleCount * sizeof(int16_t));
    addMetric(&metrics_.output_frames, 1);
    return sampleCount;
  }

  AcousticFrontendMetrics Snapshot() {
    AcousticFrontendMetrics snapshot;
    portENTER_CRITICAL(&metrics_mux_);
    snapshot = metrics_;
    portEXIT_CRITICAL(&metrics_mux_);
#if LINGOU_ENABLE_ESP_SR_AFE
    snapshot.aec_frame_samples = aec_frame_samples_;
#else
    snapshot.aec_frame_samples = 0;
#endif
    snapshot.enabled = config_.enabled;
    snapshot.active = active_;
    return snapshot;
  }

 private:
  bool validateConfig() const {
    return (
      config_.profile_version
      && config_.profile_version[0]
      && config_.aec_enabled
      && config_.aec_filter_length > 0
      && config_.reference_delay_ms >= 0
      && config_.reference_delay_ms <= 200
      && config_.microphone_gain_q8 > 0
      && config_.microphone_gain_q8 <= 1024
      && config_.clip_limit >= 1000
      && config_.clip_limit <= 32767
      && config_.ns_mode >= 0
      && config_.ns_mode <= 2
      && config_.agc_gain_db >= 0
      && config_.agc_gain_db <= 30
      && config_.agc_target_dbfs >= 0
      && config_.agc_target_dbfs <= 31
    );
  }

#if LINGOU_ENABLE_ESP_SR_AFE
  void resetState(uint32_t generation) {
    reference_generation_ = generation;
    playback_reference_active_ = false;
    reference_delay_pending_ = false;
    reference_head_ = 0;
    reference_tail_ = 0;
    reference_count_ = 0;
    resample_count_ = 0;
    resetProcessBuffers();
  }

  void resetProcessBuffers() {
    aec_input_count_ = 0;
    post_process_count_ = 0;
    processed_head_ = 0;
    processed_tail_ = 0;
    processed_count_ = 0;
  }
#endif

  void applyGainAndClip(
      const int16_t* input,
      int16_t* output,
      size_t sampleCount) {
    uint32_t clipped = 0;
    for (size_t index = 0; index < sampleCount; ++index) {
      int32_t value = (
        static_cast<int32_t>(input[index])
        * config_.microphone_gain_q8
      ) / 256;
      if (value > config_.clip_limit) {
        value = config_.clip_limit;
        ++clipped;
      } else if (value < -config_.clip_limit) {
        value = -config_.clip_limit;
        ++clipped;
      }
      output[index] = static_cast<int16_t>(value);
    }
    addMetric(&metrics_.clipped_samples, clipped);
  }

#if LINGOU_ENABLE_ESP_SR_AFE
  void readReference(int16_t* output, size_t sampleCount) {
    uint32_t underflowSamples = 0;
    portENTER_CRITICAL(&reference_mux_);
    for (size_t index = 0; index < sampleCount; ++index) {
      if (reference_count_) {
        output[index] = reference_ring_[reference_head_];
        reference_head_ = (
          reference_head_ + 1
        ) % REFERENCE_RING_SAMPLES;
        --reference_count_;
      } else {
        output[index] = 0;
        if (
          playback_reference_active_
          && !reference_delay_pending_
        ) {
          ++underflowSamples;
        }
      }
    }
    portEXIT_CRITICAL(&reference_mux_);
    addMetric(
      &metrics_.reference_underflow_samples,
      underflowSamples
    );
  }

  void processAecBlock() {
    aec_process(
      aec_handle_,
      aec_mic_,
      aec_reference_,
      aec_output_
    );
    addMetric(&metrics_.aec_blocks, 1);
    for (int index = 0; index < aec_frame_samples_; ++index) {
      post_process_[post_process_count_++] = aec_output_[index];
      if (post_process_count_ == WEBRTC_FRAME_SAMPLES) {
        const int16_t* stage = post_process_;
        if (config_.ns_enabled) {
          ns_process(ns_handle_, post_process_, ns_output_);
          stage = ns_output_;
        }
        if (config_.agc_enabled) {
          const int result = esp_agc_process(
            agc_handle_,
            const_cast<int16_t*>(stage),
            agc_output_,
            WEBRTC_FRAME_SAMPLES,
            ACOUSTIC_SAMPLE_RATE_HZ
          );
          if (result == ESP_AGC_SUCCESS) {
            stage = agc_output_;
          } else {
            addMetric(&metrics_.processing_failures, 1);
          }
        }
        pushProcessed(stage, WEBRTC_FRAME_SAMPLES);
        post_process_count_ = 0;
      }
    }
  }

  void pushProcessed(const int16_t* samples, size_t sampleCount) {
    uint32_t overflowSamples = 0;
    for (size_t index = 0; index < sampleCount; ++index) {
      if (processed_count_ == PROCESSED_RING_SAMPLES) {
        processed_head_ = (
          processed_head_ + 1
        ) % PROCESSED_RING_SAMPLES;
        --processed_count_;
        ++overflowSamples;
      }
      processed_ring_[processed_tail_] = samples[index];
      processed_tail_ = (
        processed_tail_ + 1
      ) % PROCESSED_RING_SAMPLES;
      ++processed_count_;
    }
    addMetric(
      &metrics_.processed_overflow_samples,
      overflowSamples
    );
  }
#endif

  void addMetric(uint32_t* metric, uint32_t value) {
    if (!value) {
      return;
    }
    portENTER_CRITICAL(&metrics_mux_);
    *metric += value;
    portEXIT_CRITICAL(&metrics_mux_);
  }

  void updateMaxMetric(uint32_t* metric, uint32_t value) {
    portENTER_CRITICAL(&metrics_mux_);
    if (value > *metric) {
      *metric = value;
    }
    portEXIT_CRITICAL(&metrics_mux_);
  }

  AcousticFrontendConfig config_ = BuildAcousticFrontendConfig();
  AcousticFrontendMetrics metrics_ = {};
  const char* failure_reason_ = "not_started";
  bool active_ = false;
  int16_t microphone_work_[ACOUSTIC_OUTPUT_FRAME_SAMPLES] = {};
#if LINGOU_ENABLE_ESP_SR_AFE
  volatile bool process_reset_pending_ = false;
  uint32_t reference_generation_ = 0;
  bool playback_reference_active_ = false;
  bool reference_delay_pending_ = false;
  size_t reference_head_ = 0;
  size_t reference_tail_ = 0;
  size_t reference_count_ = 0;
  int16_t reference_ring_[REFERENCE_RING_SAMPLES] = {};
  int16_t resample_triplet_[3] = {};
  uint8_t resample_count_ = 0;
  int16_t reference_work_[ACOUSTIC_OUTPUT_FRAME_SAMPLES] = {};
  alignas(16) int16_t aec_mic_[AEC_MAX_FRAME_SAMPLES] = {};
  alignas(16) int16_t aec_reference_[AEC_MAX_FRAME_SAMPLES] = {};
  alignas(16) int16_t aec_output_[AEC_MAX_FRAME_SAMPLES] = {};
  int aec_frame_samples_ = 0;
  size_t aec_input_count_ = 0;
  int16_t post_process_[WEBRTC_FRAME_SAMPLES] = {};
  int16_t ns_output_[WEBRTC_FRAME_SAMPLES] = {};
  int16_t agc_output_[WEBRTC_FRAME_SAMPLES] = {};
  size_t post_process_count_ = 0;
  int16_t processed_ring_[PROCESSED_RING_SAMPLES] = {};
  size_t processed_head_ = 0;
  size_t processed_tail_ = 0;
  size_t processed_count_ = 0;
  aec_handle_t* aec_handle_ = nullptr;
  ns_handle_t ns_handle_ = nullptr;
  void* agc_handle_ = nullptr;
  SemaphoreHandle_t process_mutex_ = nullptr;
  portMUX_TYPE reference_mux_ = portMUX_INITIALIZER_UNLOCKED;
#endif
  portMUX_TYPE metrics_mux_ = portMUX_INITIALIZER_UNLOCKED;
};

}  // namespace lingou::hal
