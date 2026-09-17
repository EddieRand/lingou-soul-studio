#include <Arduino.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <Adafruit_NeoPixel.h>
#include <driver/i2s.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

#include "hal/dnesp32s3_board_profile.h"
#include "hal/lingou_hal_contract.h"

#if __has_include("device_config.h")
#include "device_config.h"
#else
#define LINGOU_WIFI_SSID ""
#define LINGOU_WIFI_PASSWORD ""
#define LINGOU_SERVER_HOST ""
#define LINGOU_SERVER_PORT 8000
#define LINGOU_SERVER_USE_TLS 0
#define LINGOU_DEVICE_CREDENTIAL ""
#define LINGOU_SERVER_CA_CERT ""
#endif

using namespace lingou::boards::dnesp32s3;

constexpr i2s_port_t SPK_I2S_PORT = I2S_NUM_0;
constexpr i2s_port_t MIC_I2S_PORT = I2S_NUM_1;
constexpr int FSR_CANCEL_THRESHOLD = 1000;
constexpr int FSR_CANCEL_RELEASE_THRESHOLD = 1400;
constexpr unsigned long FSR_CANCEL_COOLDOWN_MS = 800;
constexpr unsigned long WIFI_RETRY_MS = 5000;
constexpr unsigned long LOCAL_ALERT_COOLDOWN_MS = 5000;
constexpr unsigned long AUDIO_TELEMETRY_INTERVAL_MS = 10000;
constexpr char DEVICE_PROTOCOL[] = "lingou.device.voice.v1";
constexpr char DEVICE_PATH[] = "/api/asr/device-stream";
constexpr size_t MAX_PLAYBACK_FRAME_BYTES = 4096;
constexpr size_t AUDIO_IDENTITY_BYTES = 80;
constexpr uint8_t CAPTURE_SLOT_COUNT = 12;
constexpr uint8_t PLAYBACK_SLOT_COUNT = 8;
constexpr uint8_t PLAYBACK_EVENT_CAPACITY = 24;
constexpr uint8_t SPEAKER_DMA_BUFFER_COUNT = 8;
constexpr uint8_t SPEAKER_WRITE_COMPLETE = 0;
constexpr uint8_t SPEAKER_WRITE_CANCELLED = 1;
constexpr uint8_t SPEAKER_WRITE_FAILED = 2;
constexpr TickType_t I2S_WRITE_TIMEOUT_TICKS = pdMS_TO_TICKS(15);
constexpr TickType_t PLAYBACK_ABORT_TIMEOUT_TICKS = pdMS_TO_TICKS(40);
constexpr TickType_t PLAYBACK_QUEUE_WAIT_TICKS = pdMS_TO_TICKS(20);

Adafruit_NeoPixel pixels(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);
WebSocketsClient webSocket;

enum class PlaybackSlotKind : uint8_t {
  kRemotePcm,
  kLocalTone,
};

enum class PlaybackEventStage : uint8_t {
  kDecoded,
  kStarted,
  kCompleted,
};

struct PlaybackIdentity {
  char session_id[AUDIO_IDENTITY_BYTES];
  char turn_id[AUDIO_IDENTITY_BYTES];
  char audio_id[AUDIO_IDENTITY_BYTES];
};

struct CaptureSlot {
  uint32_t sequence;
  uint32_t enqueued_at_ms;
  size_t length;
  uint8_t payload[MIC_FRAME_SAMPLES * sizeof(int16_t)];
};

struct PlaybackSlot {
  PlaybackSlotKind kind;
  uint32_t generation;
  uint32_t enqueued_at_ms;
  PlaybackIdentity identity;
  int chunk_index;
  int chunk_count;
  size_t length;
  int tone_frequency_hz;
  int tone_duration_ms;
  uint8_t payload[MAX_PLAYBACK_FRAME_BYTES];
};

struct PlaybackEvent {
  PlaybackEventStage stage;
  uint32_t generation;
  PlaybackIdentity identity;
};

struct ActiveAudioState {
  bool used;
  PlaybackIdentity identity;
  int chunk_count;
  int next_chunk_index;
};

struct AudioPipelineMetrics {
  uint32_t capture_overflows;
  uint32_t capture_dropped_frames;
  uint32_t capture_max_depth;
  uint32_t capture_max_wait_ms;
  uint32_t playback_overflows;
  uint32_t playback_dropped_frames;
  uint32_t playback_underruns;
  uint32_t playback_event_drops;
  uint32_t playback_max_depth;
  uint32_t playback_max_wait_ms;
};

CaptureSlot captureSlots[CAPTURE_SLOT_COUNT];
PlaybackSlot playbackSlots[PLAYBACK_SLOT_COUNT];
ActiveAudioState activeAudio[PLAYBACK_SLOT_COUNT];
int32_t micInput[MIC_FRAME_SAMPLES];
int16_t speakerStereo[SPEAKER_BLOCK_SAMPLES * 2];

QueueHandle_t freeCaptureSlots = nullptr;
QueueHandle_t capturedFrames = nullptr;
QueueHandle_t freePlaybackSlots = nullptr;
QueueHandle_t playbackFrames = nullptr;
QueueHandle_t playbackEvents = nullptr;
SemaphoreHandle_t speakerMutex = nullptr;
TaskHandle_t captureTaskHandle = nullptr;
TaskHandle_t playbackTaskHandle = nullptr;
portMUX_TYPE audioMetricsMux = portMUX_INITIALIZER_UNLOCKED;
AudioPipelineMetrics audioMetrics = {};

bool configurationReady = false;
bool audioPipelineReady = false;
volatile bool socketConnected = false;
volatile bool serverSpeaking = false;
volatile bool playbackActive = false;
volatile bool pausedForReplacement = false;
bool networkFailureNotified = false;
bool socketFailureNotified = false;
bool fsrCancelArmed = true;
unsigned long lastWifiAttemptAt = 0;
unsigned long lastCancelAt = 0;
unsigned long lastLocalAlertAt = 0;
unsigned long lastAudioTelemetryAt = 0;
String authorizationHeader;
String sessionId;
String currentTurnId;
PlaybackIdentity pendingIdentity = {};
bool pendingAudioDescriptorValid = false;
int pendingChunkIndex = -1;
int pendingChunkCount = 0;
size_t pendingChunkLength = 0;
volatile uint32_t playbackGeneration = 1;
volatile uint32_t playbackFaultGeneration = 0;
uint32_t captureSequence = 0;

void incrementMetric(uint32_t* metric) {
  portENTER_CRITICAL(&audioMetricsMux);
  ++(*metric);
  portEXIT_CRITICAL(&audioMetricsMux);
}

void updateMaxMetric(uint32_t* metric, uint32_t value) {
  portENTER_CRITICAL(&audioMetricsMux);
  if (value > *metric) {
    *metric = value;
  }
  portEXIT_CRITICAL(&audioMetricsMux);
}

void copyIdentityField(
    char* destination,
    size_t destinationSize,
    const String& source) {
  strlcpy(destination, source.c_str(), destinationSize);
}

PlaybackIdentity makeIdentity(
    const String& session,
    const String& turn,
    const String& audio) {
  PlaybackIdentity identity = {};
  copyIdentityField(
    identity.session_id,
    sizeof(identity.session_id),
    session
  );
  copyIdentityField(identity.turn_id, sizeof(identity.turn_id), turn);
  copyIdentityField(identity.audio_id, sizeof(identity.audio_id), audio);
  return identity;
}

bool identitiesMatch(
    const PlaybackIdentity& left,
    const PlaybackIdentity& right) {
  return strcmp(left.session_id, right.session_id) == 0
    && strcmp(left.turn_id, right.turn_id) == 0
    && strcmp(left.audio_id, right.audio_id) == 0;
}

void setRing(uint8_t red, uint8_t green, uint8_t blue) {
  pixels.fill(pixels.Color(red, green, blue));
  pixels.show();
}

void showBootVersionSignal() {
  for (int index = 0; index < 3; ++index) {
    setRing(48, 0, 0);
    delay(180);
    setRing(0, 0, 0);
    delay(180);
  }
}

void setIdleOutputLow() {
  if (
    speakerMutex
    && xSemaphoreTake(speakerMutex, PLAYBACK_ABORT_TIMEOUT_TICKS) == pdTRUE
  ) {
    i2s_zero_dma_buffer(SPK_I2S_PORT);
    xSemaphoreGive(speakerMutex);
    return;
  }
  i2s_zero_dma_buffer(SPK_I2S_PORT);
}

void releasePlaybackSlot(uint8_t slotIndex) {
  if (freePlaybackSlots) {
    xQueueSend(freePlaybackSlots, &slotIndex, 0);
  }
}

bool queueLocalTone(int frequency, int durationMs) {
  if (!audioPipelineReady || !freePlaybackSlots || !playbackFrames) {
    return false;
  }
  uint8_t slotIndex = 0;
  if (xQueueReceive(freePlaybackSlots, &slotIndex, 0) != pdTRUE) {
    incrementMetric(&audioMetrics.playback_overflows);
    incrementMetric(&audioMetrics.playback_dropped_frames);
    return false;
  }
  PlaybackSlot& slot = playbackSlots[slotIndex];
  slot = {};
  slot.kind = PlaybackSlotKind::kLocalTone;
  slot.generation = playbackGeneration;
  slot.enqueued_at_ms = millis();
  slot.tone_frequency_hz = frequency;
  slot.tone_duration_ms = durationMs;
  if (xQueueSend(playbackFrames, &slotIndex, 0) != pdTRUE) {
    releasePlaybackSlot(slotIndex);
    incrementMetric(&audioMetrics.playback_overflows);
    incrementMetric(&audioMetrics.playback_dropped_frames);
    return false;
  }
  updateMaxMetric(
    &audioMetrics.playback_max_depth,
    uxQueueMessagesWaiting(playbackFrames)
  );
  return true;
}

void localServiceAlert() {
  const unsigned long now = millis();
  if (
    lastLocalAlertAt != 0
    && now - lastLocalAlertAt < LOCAL_ALERT_COOLDOWN_MS
  ) {
    return;
  }
  lastLocalAlertAt = now;
  setRing(48, 8, 0);
  queueLocalTone(330, 120);
  queueLocalTone(220, 180);
}

bool hasRuntimeConfiguration() {
  return strlen(LINGOU_WIFI_SSID) > 0
    && strlen(LINGOU_SERVER_HOST) > 0
    && strlen(LINGOU_DEVICE_CREDENTIAL) > 0;
}

void setupSpeakerI2S() {
  i2s_config_t config = {
    .mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = SPEAKER_SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_MSB,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = SPEAKER_DMA_BUFFER_COUNT,
    .dma_buf_len = SPEAKER_BLOCK_SAMPLES,
    .use_apll = true,
    .tx_desc_auto_clear = true,
    .fixed_mclk = 0,
  };
  i2s_pin_config_t pins = {
    .bck_io_num = SPK_BCLK_PIN,
    .ws_io_num = SPK_LRC_PIN,
    .data_out_num = SPK_DOUT_PIN,
    .data_in_num = I2S_PIN_NO_CHANGE,
  };
  i2s_driver_install(SPK_I2S_PORT, &config, 0, nullptr);
  i2s_set_pin(SPK_I2S_PORT, &pins);
  setIdleOutputLow();
}

void setupMicrophoneI2S() {
  i2s_config_t config = {
    .mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = MIC_SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = MIC_FRAME_SAMPLES,
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0,
  };
  i2s_pin_config_t pins = {
    .bck_io_num = MIC_BCLK_PIN,
    .ws_io_num = MIC_WS_PIN,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = MIC_DIN_PIN,
  };
  i2s_driver_install(MIC_I2S_PORT, &config, 0, nullptr);
  i2s_set_pin(MIC_I2S_PORT, &pins);
  i2s_zero_dma_buffer(MIC_I2S_PORT);
}

void sendPlaybackReceipt(
    const PlaybackIdentity& identity,
    const char* stage,
    const char* error = nullptr) {
  if (
    !socketConnected
    || !identity.session_id[0]
    || !identity.turn_id[0]
    || !identity.audio_id[0]
  ) {
    return;
  }
  JsonDocument document;
  document["type"] = "audio_playback";
  document["stage"] = stage;
  document["session_id"] = identity.session_id;
  document["turn_id"] = identity.turn_id;
  document["audio_id"] = identity.audio_id;
  document["client_time_ms"] = millis();
  if (error) {
    document["error"] = error;
  }
  String output;
  serializeJson(document, output);
  webSocket.sendTXT(output);
}

ActiveAudioState* findActiveAudio(const PlaybackIdentity& identity) {
  for (ActiveAudioState& state : activeAudio) {
    if (state.used && identitiesMatch(state.identity, identity)) {
      return &state;
    }
  }
  return nullptr;
}

bool trackAudioChunk(
    const PlaybackIdentity& identity,
    int chunkIndex,
    int chunkCount) {
  ActiveAudioState* state = findActiveAudio(identity);
  if (!state) {
    if (chunkIndex != 0) {
      return false;
    }
    for (ActiveAudioState& candidate : activeAudio) {
      if (!candidate.used) {
        candidate.used = true;
        candidate.identity = identity;
        candidate.chunk_count = chunkCount;
        candidate.next_chunk_index = 1;
        return true;
      }
    }
    return false;
  }
  if (
    state->chunk_count != chunkCount
    || state->next_chunk_index != chunkIndex
  ) {
    return false;
  }
  ++state->next_chunk_index;
  return true;
}

void removeActiveAudio(const PlaybackIdentity& identity) {
  ActiveAudioState* state = findActiveAudio(identity);
  if (state) {
    *state = {};
  }
}

bool hasActiveAudio() {
  for (const ActiveAudioState& state : activeAudio) {
    if (state.used) {
      return true;
    }
  }
  return false;
}

void clearActiveAudio() {
  for (ActiveAudioState& state : activeAudio) {
    state = {};
  }
}

void releaseCaptureSlot(uint8_t slotIndex) {
  if (freeCaptureSlots) {
    xQueueSend(freeCaptureSlots, &slotIndex, 0);
  }
}

void clearCapturedFrames() {
  if (!capturedFrames) {
    return;
  }
  uint8_t slotIndex = 0;
  while (xQueueReceive(capturedFrames, &slotIndex, 0) == pdTRUE) {
    releaseCaptureSlot(slotIndex);
  }
}

void clearPlaybackFrames() {
  if (!playbackFrames) {
    return;
  }
  uint8_t slotIndex = 0;
  while (xQueueReceive(playbackFrames, &slotIndex, 0) == pdTRUE) {
    releasePlaybackSlot(slotIndex);
    incrementMetric(&audioMetrics.playback_dropped_frames);
  }
}

void resetPendingAudioDescriptor() {
  pendingIdentity = {};
  pendingAudioDescriptorValid = false;
  pendingChunkIndex = -1;
  pendingChunkCount = 0;
  pendingChunkLength = 0;
}

void stopRemotePlayback(
    bool reportFailure,
    const char* failureReason = "device_interrupted") {
  ++playbackGeneration;
  playbackFaultGeneration = 0;
  playbackActive = false;
  clearPlaybackFrames();
  setIdleOutputLow();
  serverSpeaking = false;
  resetPendingAudioDescriptor();
  currentTurnId = "";
  setRing(18, 0, 18);
  if (reportFailure) {
    for (const ActiveAudioState& state : activeAudio) {
      if (state.used) {
        sendPlaybackReceipt(
          state.identity,
          "playback_failed",
          failureReason
        );
      }
    }
  }
  clearActiveAudio();
}

void requestTurnCancellation() {
  if (!socketConnected || !serverSpeaking) {
    return;
  }
  stopRemotePlayback(true, "device_interrupted");
  JsonDocument document;
  document["type"] = "cancel_turn";
  document["session_id"] = sessionId;
  String output;
  serializeJson(document, output);
  webSocket.sendTXT(output);
  setRing(0, 24, 24);
}

bool queuePlaybackEvent(
    const PlaybackSlot& slot,
    PlaybackEventStage stage) {
  PlaybackEvent event = {
    .stage = stage,
    .generation = slot.generation,
    .identity = slot.identity,
  };
  if (xQueueSend(playbackEvents, &event, pdMS_TO_TICKS(5)) == pdTRUE) {
    return true;
  }
  incrementMetric(&audioMetrics.playback_event_drops);
  playbackFaultGeneration = slot.generation;
  return false;
}

uint8_t writeStereoSamples(
    const int16_t* mono,
    size_t sampleCount,
    uint32_t generation) {
  for (size_t index = 0; index < sampleCount; ++index) {
    speakerStereo[index * 2] = mono[index];
    speakerStereo[index * 2 + 1] = mono[index];
  }
  size_t writtenTotal = 0;
  const size_t totalBytes = sampleCount * 2 * sizeof(int16_t);
  while (writtenTotal < totalBytes) {
    if (generation != playbackGeneration) {
      return SPEAKER_WRITE_CANCELLED;
    }
    if (
      xSemaphoreTake(speakerMutex, PLAYBACK_ABORT_TIMEOUT_TICKS) != pdTRUE
    ) {
      return generation == playbackGeneration
        ? SPEAKER_WRITE_FAILED
        : SPEAKER_WRITE_CANCELLED;
    }
    if (generation != playbackGeneration) {
      xSemaphoreGive(speakerMutex);
      return SPEAKER_WRITE_CANCELLED;
    }
    size_t written = 0;
    const esp_err_t error = i2s_write(
      SPK_I2S_PORT,
      reinterpret_cast<uint8_t*>(speakerStereo) + writtenTotal,
      totalBytes - writtenTotal,
      &written,
      I2S_WRITE_TIMEOUT_TICKS
    );
    xSemaphoreGive(speakerMutex);
    if (error != ESP_OK || written == 0) {
      return SPEAKER_WRITE_FAILED;
    }
    writtenTotal += written;
  }
  return SPEAKER_WRITE_COMPLETE;
}

uint8_t flushSpeakerWithSilence(uint32_t generation) {
  int16_t silence[SPEAKER_BLOCK_SAMPLES] = {};
  for (uint8_t index = 0; index < SPEAKER_DMA_BUFFER_COUNT; ++index) {
    const uint8_t result = writeStereoSamples(
      silence,
      SPEAKER_BLOCK_SAMPLES,
      generation
    );
    if (result != SPEAKER_WRITE_COMPLETE) {
      return result;
    }
  }
  return SPEAKER_WRITE_COMPLETE;
}

uint8_t playRemoteSlot(const PlaybackSlot& slot) {
  const int16_t* mono = reinterpret_cast<const int16_t*>(slot.payload);
  const size_t monoSamples = slot.length / sizeof(int16_t);
  size_t offset = 0;
  bool started = false;
  playbackActive = true;
  while (offset < monoSamples) {
    const size_t count = min(
      static_cast<size_t>(SPEAKER_BLOCK_SAMPLES),
      monoSamples - offset
    );
    const uint8_t result = writeStereoSamples(
      mono + offset,
      count,
      slot.generation
    );
    if (result != SPEAKER_WRITE_COMPLETE) {
      return result;
    }
    if (!started && slot.chunk_index == 0) {
      if (
        !queuePlaybackEvent(slot, PlaybackEventStage::kDecoded)
        || !queuePlaybackEvent(slot, PlaybackEventStage::kStarted)
      ) {
        return SPEAKER_WRITE_FAILED;
      }
      started = true;
    }
    offset += count;
  }

  if (slot.chunk_index == slot.chunk_count - 1) {
    const uint8_t flushResult = flushSpeakerWithSilence(slot.generation);
    if (flushResult != SPEAKER_WRITE_COMPLETE) {
      return flushResult;
    }
    playbackActive = false;
    if (!queuePlaybackEvent(slot, PlaybackEventStage::kCompleted)) {
      return SPEAKER_WRITE_FAILED;
    }
  }
  return SPEAKER_WRITE_COMPLETE;
}

uint8_t playLocalToneSlot(const PlaybackSlot& slot) {
  const int totalSamples = (
    SPEAKER_SAMPLE_RATE * slot.tone_duration_ms / 1000
  );
  float phase = 0.0f;
  const float phaseStep = (
    2.0f * PI * slot.tone_frequency_hz / SPEAKER_SAMPLE_RATE
  );
  for (int offset = 0; offset < totalSamples; offset += SPEAKER_BLOCK_SAMPLES) {
    const size_t count = min(
      static_cast<size_t>(SPEAKER_BLOCK_SAMPLES),
      static_cast<size_t>(totalSamples - offset)
    );
    int16_t mono[SPEAKER_BLOCK_SAMPLES];
    for (size_t index = 0; index < count; ++index) {
      mono[index] = static_cast<int16_t>(sinf(phase) * 7000.0f);
      phase += phaseStep;
    }
    const uint8_t result = writeStereoSamples(
      mono,
      count,
      slot.generation
    );
    if (result != SPEAKER_WRITE_COMPLETE) {
      return result;
    }
  }
  const uint8_t flushResult = flushSpeakerWithSilence(slot.generation);
  if (flushResult != SPEAKER_WRITE_COMPLETE) {
    return flushResult;
  }
  setIdleOutputLow();
  return SPEAKER_WRITE_COMPLETE;
}

void captureAudioTask(void*) {
  size_t accumulatedBytes = 0;
  for (;;) {
    size_t bytesRead = 0;
    const esp_err_t error = i2s_read(
      MIC_I2S_PORT,
      reinterpret_cast<uint8_t*>(micInput) + accumulatedBytes,
      sizeof(micInput) - accumulatedBytes,
      &bytesRead,
      pdMS_TO_TICKS(25)
    );
    if (
      error != ESP_OK
      || !socketConnected
      || serverSpeaking
      || pausedForReplacement
    ) {
      accumulatedBytes = 0;
      continue;
    }
    accumulatedBytes += bytesRead;
    if (accumulatedBytes < sizeof(micInput)) {
      continue;
    }
    accumulatedBytes = 0;

    uint8_t slotIndex = 0;
    if (xQueueReceive(freeCaptureSlots, &slotIndex, 0) != pdTRUE) {
      if (xQueueReceive(capturedFrames, &slotIndex, 0) != pdTRUE) {
        incrementMetric(&audioMetrics.capture_dropped_frames);
        continue;
      }
      incrementMetric(&audioMetrics.capture_overflows);
      incrementMetric(&audioMetrics.capture_dropped_frames);
    }

    CaptureSlot& slot = captureSlots[slotIndex];
    int16_t* output = reinterpret_cast<int16_t*>(slot.payload);
    for (size_t index = 0; index < MIC_FRAME_SAMPLES; ++index) {
      int32_t value = micInput[index] >> 13;
      value *= 2;
      value = constrain(value, -32768, 32767);
      output[index] = static_cast<int16_t>(value);
    }
    slot.sequence = ++captureSequence;
    slot.enqueued_at_ms = millis();
    slot.length = sizeof(slot.payload);
    if (xQueueSend(capturedFrames, &slotIndex, 0) != pdTRUE) {
      releaseCaptureSlot(slotIndex);
      incrementMetric(&audioMetrics.capture_overflows);
      incrementMetric(&audioMetrics.capture_dropped_frames);
      continue;
    }
    updateMaxMetric(
      &audioMetrics.capture_max_depth,
      uxQueueMessagesWaiting(capturedFrames)
    );
  }
}

void playbackAudioTask(void*) {
  bool underrunReported = false;
  for (;;) {
    uint8_t slotIndex = 0;
    if (
      xQueueReceive(
        playbackFrames,
        &slotIndex,
        PLAYBACK_QUEUE_WAIT_TICKS
      ) != pdTRUE
    ) {
      if (playbackActive && serverSpeaking && !underrunReported) {
        incrementMetric(&audioMetrics.playback_underruns);
        underrunReported = true;
      }
      continue;
    }
    underrunReported = false;
    PlaybackSlot& slot = playbackSlots[slotIndex];
    updateMaxMetric(
      &audioMetrics.playback_max_wait_ms,
      millis() - slot.enqueued_at_ms
    );

    uint8_t result = SPEAKER_WRITE_CANCELLED;
    if (slot.generation == playbackGeneration) {
      result = slot.kind == PlaybackSlotKind::kRemotePcm
        ? playRemoteSlot(slot)
        : playLocalToneSlot(slot);
    }
    if (
      result == SPEAKER_WRITE_FAILED
      && slot.kind == PlaybackSlotKind::kRemotePcm
    ) {
      playbackFaultGeneration = slot.generation;
    }
    releasePlaybackSlot(slotIndex);
  }
}

bool setupAudioPipeline() {
  freeCaptureSlots = xQueueCreate(CAPTURE_SLOT_COUNT, sizeof(uint8_t));
  capturedFrames = xQueueCreate(CAPTURE_SLOT_COUNT, sizeof(uint8_t));
  freePlaybackSlots = xQueueCreate(PLAYBACK_SLOT_COUNT, sizeof(uint8_t));
  playbackFrames = xQueueCreate(PLAYBACK_SLOT_COUNT, sizeof(uint8_t));
  playbackEvents = xQueueCreate(
    PLAYBACK_EVENT_CAPACITY,
    sizeof(PlaybackEvent)
  );
  speakerMutex = xSemaphoreCreateMutex();
  if (
    !freeCaptureSlots
    || !capturedFrames
    || !freePlaybackSlots
    || !playbackFrames
    || !playbackEvents
    || !speakerMutex
  ) {
    return false;
  }
  for (uint8_t index = 0; index < CAPTURE_SLOT_COUNT; ++index) {
    xQueueSend(freeCaptureSlots, &index, 0);
  }
  for (uint8_t index = 0; index < PLAYBACK_SLOT_COUNT; ++index) {
    xQueueSend(freePlaybackSlots, &index, 0);
  }

  audioPipelineReady = true;
  const BaseType_t captureCreated = xTaskCreatePinnedToCore(
    captureAudioTask,
    "lingou_capture",
    4096,
    nullptr,
    7,
    &captureTaskHandle,
    1
  );
  const BaseType_t playbackCreated = xTaskCreatePinnedToCore(
    playbackAudioTask,
    "lingou_playback",
    4096,
    nullptr,
    7,
    &playbackTaskHandle,
    1
  );
  if (captureCreated != pdPASS || playbackCreated != pdPASS) {
    audioPipelineReady = false;
    if (captureTaskHandle) {
      vTaskDelete(captureTaskHandle);
      captureTaskHandle = nullptr;
    }
    if (playbackTaskHandle) {
      vTaskDelete(playbackTaskHandle);
      playbackTaskHandle = nullptr;
    }
    return false;
  }
  return true;
}

bool enqueueRemotePcm(const uint8_t* payload, size_t length) {
  const PlaybackIdentity identity = pendingIdentity;
  const int chunkIndex = pendingChunkIndex;
  const int chunkCount = pendingChunkCount;
  const size_t declaredLength = pendingChunkLength;
  resetPendingAudioDescriptor();

  const bool frameValid = (
    payload
    && length >= sizeof(int16_t)
    && length <= MAX_PLAYBACK_FRAME_BYTES
    && (length % sizeof(int16_t)) == 0
    && length == declaredLength
  );
  if (!frameValid || !trackAudioChunk(identity, chunkIndex, chunkCount)) {
    if (!findActiveAudio(identity)) {
      sendPlaybackReceipt(
        identity,
        "playback_failed",
        "invalid_pcm_frame"
      );
    }
    stopRemotePlayback(true, "invalid_pcm_frame");
    return false;
  }

  uint8_t slotIndex = 0;
  if (xQueueReceive(freePlaybackSlots, &slotIndex, 0) != pdTRUE) {
    incrementMetric(&audioMetrics.playback_overflows);
    incrementMetric(&audioMetrics.playback_dropped_frames);
    stopRemotePlayback(true, "playback_queue_overflow");
    return false;
  }
  PlaybackSlot& slot = playbackSlots[slotIndex];
  slot.kind = PlaybackSlotKind::kRemotePcm;
  slot.generation = playbackGeneration;
  slot.enqueued_at_ms = millis();
  slot.identity = identity;
  slot.chunk_index = chunkIndex;
  slot.chunk_count = chunkCount;
  slot.length = length;
  memcpy(slot.payload, payload, length);
  if (xQueueSend(playbackFrames, &slotIndex, 0) != pdTRUE) {
    releasePlaybackSlot(slotIndex);
    incrementMetric(&audioMetrics.playback_overflows);
    incrementMetric(&audioMetrics.playback_dropped_frames);
    stopRemotePlayback(true, "playback_queue_overflow");
    return false;
  }
  updateMaxMetric(
    &audioMetrics.playback_max_depth,
    uxQueueMessagesWaiting(playbackFrames)
  );
  return true;
}

void processPlaybackEvents() {
  if (
    playbackFaultGeneration != 0
    && playbackFaultGeneration == playbackGeneration
  ) {
    stopRemotePlayback(true, "i2s_playback_failed");
    return;
  }
  PlaybackEvent event;
  while (xQueueReceive(playbackEvents, &event, 0) == pdTRUE) {
    if (event.generation != playbackGeneration) {
      continue;
    }
    ActiveAudioState* state = findActiveAudio(event.identity);
    if (!state) {
      continue;
    }
    switch (event.stage) {
      case PlaybackEventStage::kDecoded:
        sendPlaybackReceipt(event.identity, "decoded");
        break;
      case PlaybackEventStage::kStarted:
        sendPlaybackReceipt(event.identity, "playback_started");
        break;
      case PlaybackEventStage::kCompleted:
        sendPlaybackReceipt(event.identity, "playback_completed");
        removeActiveAudio(event.identity);
        if (!hasActiveAudio() && uxQueueMessagesWaiting(playbackFrames) == 0) {
          serverSpeaking = false;
          setRing(18, 0, 18);
        }
        break;
    }
  }
}

void streamQueuedMicrophoneFrames() {
  if (!socketConnected || serverSpeaking || pausedForReplacement) {
    clearCapturedFrames();
    return;
  }
  for (uint8_t sent = 0; sent < 4; ++sent) {
    uint8_t slotIndex = 0;
    if (xQueueReceive(capturedFrames, &slotIndex, 0) != pdTRUE) {
      return;
    }
    CaptureSlot& slot = captureSlots[slotIndex];
    updateMaxMetric(
      &audioMetrics.capture_max_wait_ms,
      millis() - slot.enqueued_at_ms
    );
    if (!webSocket.sendBIN(slot.payload, slot.length)) {
      incrementMetric(&audioMetrics.capture_dropped_frames);
    }
    releaseCaptureSlot(slotIndex);
  }
}

void printAudioTelemetry() {
  const unsigned long now = millis();
  if (now - lastAudioTelemetryAt < AUDIO_TELEMETRY_INTERVAL_MS) {
    return;
  }
  lastAudioTelemetryAt = now;
  AudioPipelineMetrics snapshot;
  portENTER_CRITICAL(&audioMetricsMux);
  snapshot = audioMetrics;
  portEXIT_CRITICAL(&audioMetricsMux);
  Serial.printf(
    "AUDIO_PIPELINE capture_depth=%u capture_overflow=%lu "
    "capture_drop=%lu capture_max_depth=%lu capture_max_wait_ms=%lu "
    "playback_depth=%u playback_overflow=%lu playback_drop=%lu "
    "playback_underrun=%lu playback_event_drop=%lu "
    "playback_max_depth=%lu playback_max_wait_ms=%lu\n",
    capturedFrames ? uxQueueMessagesWaiting(capturedFrames) : 0,
    static_cast<unsigned long>(snapshot.capture_overflows),
    static_cast<unsigned long>(snapshot.capture_dropped_frames),
    static_cast<unsigned long>(snapshot.capture_max_depth),
    static_cast<unsigned long>(snapshot.capture_max_wait_ms),
    playbackFrames ? uxQueueMessagesWaiting(playbackFrames) : 0,
    static_cast<unsigned long>(snapshot.playback_overflows),
    static_cast<unsigned long>(snapshot.playback_dropped_frames),
    static_cast<unsigned long>(snapshot.playback_underruns),
    static_cast<unsigned long>(snapshot.playback_event_drops),
    static_cast<unsigned long>(snapshot.playback_max_depth),
    static_cast<unsigned long>(snapshot.playback_max_wait_ms)
  );
}

bool hasActiveTurn(const String& messageSession, const String& turnId) {
  if (!messageSession.length() || !turnId.length()) {
    return false;
  }
  for (const ActiveAudioState& state : activeAudio) {
    if (
      state.used
      && messageSession == state.identity.session_id
      && turnId == state.identity.turn_id
    ) {
      return true;
    }
  }
  return (
    pendingAudioDescriptorValid
    && messageSession == pendingIdentity.session_id
    && turnId == pendingIdentity.turn_id
  );
}

void handleServerText(uint8_t* payload, size_t length) {
  JsonDocument document;
  const DeserializationError error = deserializeJson(document, payload, length);
  if (error) {
    return;
  }

  const String type = document["type"] | "";
  const String messageSession = document["session_id"] | "";
  if (!sessionId.length() && messageSession.length()) {
    sessionId = messageSession;
  }
  if (
    sessionId.length()
    && messageSession.length()
    && messageSession != sessionId
  ) {
    return;
  }

  if (type == "status") {
    setRing(18, 0, 18);
    return;
  }
  if (type == "speaking") {
    const String status = document["status"] | "";
    const String turnId = document["turn_id"] | "";
    if (status == "start") {
      if (
        currentTurnId.length()
        && turnId.length()
        && turnId != currentTurnId
      ) {
        stopRemotePlayback(false);
      }
      if (turnId.length()) {
        currentTurnId = turnId;
      }
      serverSpeaking = true;
      clearCapturedFrames();
    } else if (
      (!turnId.length() || turnId == currentTurnId)
      && !hasActiveAudio()
    ) {
      serverSpeaking = false;
      currentTurnId = "";
    }
    setRing(serverSpeaking ? 18 : 18, 0, serverSpeaking ? 40 : 18);
    return;
  }
  if (type == "audio_chunk") {
    const String turnId = document["turn_id"] | "";
    const String audioId = document["audio_id"] | "";
    const int chunkIndex = document["chunk_index"] | -1;
    const int chunkCount = document["chunk_count"] | 0;
    const int chunkLength = document["chunk_byte_length"] | 0;
    const bool identityValid = (
      messageSession.length()
      && turnId.length()
      && audioId.length()
      && messageSession.length() < AUDIO_IDENTITY_BYTES
      && turnId.length() < AUDIO_IDENTITY_BYTES
      && audioId.length() < AUDIO_IDENTITY_BYTES
    );
    if (currentTurnId.length() && turnId != currentTurnId) {
      return;
    }
    if (pendingAudioDescriptorValid) {
      if (!findActiveAudio(pendingIdentity)) {
        sendPlaybackReceipt(
          pendingIdentity,
          "playback_failed",
          "missing_binary_frame"
        );
      }
      stopRemotePlayback(true, "missing_binary_frame");
      return;
    }
    const bool descriptorValid = (
      identityValid
      && chunkIndex >= 0
    );
    const bool mediaValid = (
      chunkCount > 0
      && chunkIndex < chunkCount
      && chunkLength >= static_cast<int>(sizeof(int16_t))
      && chunkLength <= static_cast<int>(MAX_PLAYBACK_FRAME_BYTES)
      && chunkLength % sizeof(int16_t) == 0
      && String(document["audio_format"] | "") == "pcm"
      && (document["sample_rate"] | 0) == SPEAKER_SAMPLE_RATE
      && (document["channels"] | 0) == 1
      && String(document["sample_format"] | "") == "s16le"
    );
    if (!descriptorValid || !mediaValid) {
      if (identityValid) {
        const PlaybackIdentity invalidIdentity = makeIdentity(
          messageSession,
          turnId,
          audioId
        );
        if (!findActiveAudio(invalidIdentity)) {
          sendPlaybackReceipt(
            invalidIdentity,
            "playback_failed",
            "invalid_audio_descriptor"
          );
        }
      }
      stopRemotePlayback(true, "invalid_audio_descriptor");
      return;
    }
    pendingIdentity = makeIdentity(messageSession, turnId, audioId);
    pendingAudioDescriptorValid = true;
    pendingChunkIndex = document["chunk_index"] | -1;
    pendingChunkCount = document["chunk_count"] | 0;
    pendingChunkLength = chunkLength;
    currentTurnId = turnId;
    serverSpeaking = true;
    clearCapturedFrames();
    return;
  }
  if (type == "stop_audio" || type == "turn_cancelled") {
    const String turnId = document["turn_id"] | "";
    if (
      !turnId.length()
      || turnId == currentTurnId
      || hasActiveTurn(messageSession, turnId)
    ) {
      stopRemotePlayback(false);
    }
    return;
  }
  if (type == "audio_output" && String(document["stage"] | "") == "failed") {
    const String turnId = document["turn_id"] | "";
    if (
      !turnId.length()
      || turnId == currentTurnId
      || hasActiveTurn(messageSession, turnId)
    ) {
      stopRemotePlayback(false);
      localServiceAlert();
    }
    return;
  }
  if (type == "session_replaced") {
    pausedForReplacement = true;
    stopRemotePlayback(false);
    setRing(48, 16, 0);
    webSocket.disconnect();
    return;
  }
  if (type == "error") {
    stopRemotePlayback(false);
    localServiceAlert();
  }
}

void webSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      stopRemotePlayback(false);
      sessionId = "";
      clearCapturedFrames();
      socketConnected = true;
      socketFailureNotified = false;
      setRing(18, 0, 18);
      Serial.println("DEVICE_VOICE_CONNECTED");
      break;
    case WStype_DISCONNECTED:
      socketConnected = false;
      stopRemotePlayback(false);
      sessionId = "";
      clearCapturedFrames();
      setRing(48, 8, 0);
      Serial.println("DEVICE_VOICE_DISCONNECTED");
      if (!pausedForReplacement && !socketFailureNotified) {
        socketFailureNotified = true;
        localServiceAlert();
      }
      break;
    case WStype_TEXT:
      handleServerText(payload, length);
      break;
    case WStype_BIN:
      if (pendingAudioDescriptorValid) {
        enqueueRemotePcm(payload, length);
      } else {
        incrementMetric(&audioMetrics.playback_dropped_frames);
      }
      break;
    case WStype_ERROR:
      socketConnected = false;
      stopRemotePlayback(false);
      sessionId = "";
      clearCapturedFrames();
      if (!socketFailureNotified) {
        socketFailureNotified = true;
        localServiceAlert();
      }
      break;
    default:
      break;
  }
}

void connectWiFi() {
  if (!configurationReady || WiFi.status() == WL_CONNECTED) {
    return;
  }
  const unsigned long now = millis();
  if (now - lastWifiAttemptAt < WIFI_RETRY_MS) {
    return;
  }
  lastWifiAttemptAt = now;
  WiFi.mode(WIFI_STA);
  WiFi.begin(LINGOU_WIFI_SSID, LINGOU_WIFI_PASSWORD);
}

void connectVoiceSocket() {
  authorizationHeader = "Authorization: Device ";
  authorizationHeader += LINGOU_DEVICE_CREDENTIAL;
  authorizationHeader += "\r\n";
  webSocket.setExtraHeaders(authorizationHeader.c_str());
  webSocket.onEvent(webSocketEvent);
  webSocket.setReconnectInterval(3000);
  webSocket.enableHeartbeat(15000, 3000, 2);

  if (LINGOU_SERVER_USE_TLS) {
    if (strlen(LINGOU_SERVER_CA_CERT) == 0) {
      Serial.println("DEVICE_CONFIG_ERROR=TLS_CA_REQUIRED");
      configurationReady = false;
      return;
    }
    webSocket.beginSslWithCA(
      LINGOU_SERVER_HOST,
      LINGOU_SERVER_PORT,
      DEVICE_PATH,
      LINGOU_SERVER_CA_CERT,
      DEVICE_PROTOCOL
    );
  } else {
    webSocket.begin(
      LINGOU_SERVER_HOST,
      LINGOU_SERVER_PORT,
      DEVICE_PATH,
      DEVICE_PROTOCOL
    );
  }
}

void checkPhysicalCancellation() {
  const int pressure = analogRead(FSR_PIN);
  const unsigned long now = millis();
  if (pressure >= FSR_CANCEL_RELEASE_THRESHOLD) {
    fsrCancelArmed = true;
  }
  if (!fsrCancelArmed) {
    return;
  }
  if (
    pausedForReplacement
    && pressure <= FSR_CANCEL_THRESHOLD
    && now - lastCancelAt >= FSR_CANCEL_COOLDOWN_MS
  ) {
    fsrCancelArmed = false;
    lastCancelAt = now;
    pausedForReplacement = false;
    connectVoiceSocket();
    return;
  }
  if (
    serverSpeaking
    && pressure <= FSR_CANCEL_THRESHOLD
    && now - lastCancelAt >= FSR_CANCEL_COOLDOWN_MS
  ) {
    fsrCancelArmed = false;
    lastCancelAt = now;
    requestTurnCancellation();
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  pixels.begin();
  pixels.setBrightness(50);
  pinMode(FSR_PIN, INPUT);

  setupSpeakerI2S();
  setupMicrophoneI2S();
  audioPipelineReady = setupAudioPipeline();
  showBootVersionSignal();

  Serial.println("LINGOU_DEVICE_FIRMWARE=lingou-device-v1");
  Serial.println("PINS=LED18,FSR16,MIC5/7/4,SPK6/15/17");
  Serial.printf(
    "AUDIO_PIPELINE_CONFIG=capture:%u,playback:%u,abort_ms:40\n",
    CAPTURE_SLOT_COUNT,
    PLAYBACK_SLOT_COUNT
  );
  if (!audioPipelineReady) {
    Serial.println("DEVICE_CONFIG_ERROR=AUDIO_PIPELINE_INIT_FAILED");
    setRing(48, 0, 0);
    return;
  }
  configurationReady = hasRuntimeConfiguration();
  if (!configurationReady) {
    Serial.println("DEVICE_CONFIG_ERROR=MISSING_DEVICE_CONFIG");
    setRing(48, 0, 0);
    localServiceAlert();
    return;
  }

  connectWiFi();
  connectVoiceSocket();
}

void loop() {
  printAudioTelemetry();
  if (!configurationReady) {
    delay(100);
    return;
  }

  connectWiFi();
  if (WiFi.status() != WL_CONNECTED) {
    if (socketConnected || serverSpeaking) {
      stopRemotePlayback(false);
      sessionId = "";
      clearCapturedFrames();
    }
    socketConnected = false;
    setRing(48, 8, 0);
    if (!networkFailureNotified) {
      networkFailureNotified = true;
      localServiceAlert();
    }
    delay(20);
    return;
  }
  networkFailureNotified = false;

  if (pausedForReplacement) {
    checkPhysicalCancellation();
    delay(20);
    return;
  }

  webSocket.loop();
  processPlaybackEvents();
  checkPhysicalCancellation();
  streamQueuedMicrophoneFrames();
}
