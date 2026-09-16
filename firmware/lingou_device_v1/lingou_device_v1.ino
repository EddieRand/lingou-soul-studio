#include <Arduino.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <Adafruit_NeoPixel.h>
#include <driver/i2s.h>

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

// DNESP32S3 verified wiring. Do not change without changing the physical base.
constexpr gpio_num_t LED_PIN = GPIO_NUM_18;
constexpr int LED_COUNT = 24;
constexpr gpio_num_t FSR_PIN = GPIO_NUM_16;
constexpr gpio_num_t MIC_BCLK_PIN = GPIO_NUM_5;
constexpr gpio_num_t MIC_WS_PIN = GPIO_NUM_7;
constexpr gpio_num_t MIC_DIN_PIN = GPIO_NUM_4;
constexpr gpio_num_t SPK_BCLK_PIN = GPIO_NUM_6;
constexpr gpio_num_t SPK_LRC_PIN = GPIO_NUM_15;
constexpr gpio_num_t SPK_DOUT_PIN = GPIO_NUM_17;

constexpr i2s_port_t SPK_I2S_PORT = I2S_NUM_0;
constexpr i2s_port_t MIC_I2S_PORT = I2S_NUM_1;
constexpr int MIC_SAMPLE_RATE = 16000;
constexpr int SPEAKER_SAMPLE_RATE = 24000;
constexpr int MIC_FRAME_SAMPLES = 320;  // 20 ms at 16 kHz.
constexpr int SPEAKER_BLOCK_SAMPLES = 256;
constexpr int FSR_CANCEL_THRESHOLD = 1000;
constexpr int FSR_CANCEL_RELEASE_THRESHOLD = 1400;
constexpr unsigned long FSR_CANCEL_COOLDOWN_MS = 800;
constexpr unsigned long WIFI_RETRY_MS = 5000;
constexpr unsigned long LOCAL_ALERT_COOLDOWN_MS = 5000;
constexpr char DEVICE_PROTOCOL[] = "lingou.device.voice.v1";
constexpr char DEVICE_PATH[] = "/api/asr/device-stream";

Adafruit_NeoPixel pixels(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);
WebSocketsClient webSocket;

int32_t micInput[MIC_FRAME_SAMPLES];
int16_t micPcm[MIC_FRAME_SAMPLES];
int16_t speakerStereo[SPEAKER_BLOCK_SAMPLES * 2];

bool configurationReady = false;
bool socketConnected = false;
bool serverSpeaking = false;
bool pausedForReplacement = false;
bool audioStartedForCurrentId = false;
bool networkFailureNotified = false;
bool socketFailureNotified = false;
bool fsrCancelArmed = true;
unsigned long lastWifiAttemptAt = 0;
unsigned long lastCancelAt = 0;
unsigned long lastLocalAlertAt = 0;
String authorizationHeader;
String sessionId;
String pendingAudioId;
String pendingTurnId;
int pendingChunkIndex = -1;
int pendingChunkCount = 0;

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
  i2s_zero_dma_buffer(SPK_I2S_PORT);
}

void playLocalTone(int frequency, int durationMs) {
  const int totalSamples = SPEAKER_SAMPLE_RATE * durationMs / 1000;
  float phase = 0.0f;
  const float phaseStep = 2.0f * PI * frequency / SPEAKER_SAMPLE_RATE;
  for (int offset = 0; offset < totalSamples; offset += SPEAKER_BLOCK_SAMPLES) {
    const int count = min(SPEAKER_BLOCK_SAMPLES, totalSamples - offset);
    for (int index = 0; index < count; ++index) {
      const int16_t value = static_cast<int16_t>(sinf(phase) * 7000.0f);
      speakerStereo[index * 2] = value;
      speakerStereo[index * 2 + 1] = value;
      phase += phaseStep;
    }
    size_t written = 0;
    i2s_write(
      SPK_I2S_PORT,
      speakerStereo,
      count * 2 * sizeof(int16_t),
      &written,
      portMAX_DELAY
    );
  }
  setIdleOutputLow();
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
  playLocalTone(330, 120);
  delay(80);
  playLocalTone(220, 180);
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
    .dma_buf_count = 8,
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

void sendPlaybackReceipt(const char* stage, const char* error = nullptr) {
  if (!socketConnected || !sessionId.length() || !pendingAudioId.length()) {
    return;
  }
  JsonDocument document;
  document["type"] = "audio_playback";
  document["stage"] = stage;
  document["session_id"] = sessionId;
  document["turn_id"] = pendingTurnId;
  document["audio_id"] = pendingAudioId;
  document["client_time_ms"] = millis();
  if (error) {
    document["error"] = error;
  }
  String output;
  serializeJson(document, output);
  webSocket.sendTXT(output);
}

void stopRemotePlayback(bool reportFailure) {
  if (reportFailure && pendingAudioId.length()) {
    sendPlaybackReceipt("playback_failed", "device_interrupted");
  }
  setIdleOutputLow();
  serverSpeaking = false;
  audioStartedForCurrentId = false;
  pendingAudioId = "";
  pendingTurnId = "";
  pendingChunkIndex = -1;
  pendingChunkCount = 0;
  setRing(18, 0, 18);
}

void requestTurnCancellation() {
  if (!socketConnected || !serverSpeaking) {
    return;
  }
  stopRemotePlayback(true);
  JsonDocument document;
  document["type"] = "cancel_turn";
  document["session_id"] = sessionId;
  String output;
  serializeJson(document, output);
  webSocket.sendTXT(output);
  setRing(0, 24, 24);
}

void playPcmChunk(const uint8_t* payload, size_t length) {
  if (!payload || length < sizeof(int16_t) || (length % sizeof(int16_t)) != 0) {
    sendPlaybackReceipt("playback_failed", "invalid_pcm_frame");
    stopRemotePlayback(false);
    return;
  }

  if (!audioStartedForCurrentId) {
    audioStartedForCurrentId = true;
    sendPlaybackReceipt("decoded");
    sendPlaybackReceipt("playback_started");
  }

  const int16_t* mono = reinterpret_cast<const int16_t*>(payload);
  size_t monoSamples = length / sizeof(int16_t);
  size_t offset = 0;
  while (offset < monoSamples && serverSpeaking) {
    const size_t count = min(
      static_cast<size_t>(SPEAKER_BLOCK_SAMPLES),
      monoSamples - offset
    );
    for (size_t index = 0; index < count; ++index) {
      const int16_t value = mono[offset + index];
      speakerStereo[index * 2] = value;
      speakerStereo[index * 2 + 1] = value;
    }
    size_t written = 0;
    i2s_write(
      SPK_I2S_PORT,
      speakerStereo,
      count * 2 * sizeof(int16_t),
      &written,
      portMAX_DELAY
    );
    offset += count;
  }

  if (
    serverSpeaking
    && pendingChunkCount > 0
    && pendingChunkIndex == pendingChunkCount - 1
  ) {
    sendPlaybackReceipt("playback_completed");
    setIdleOutputLow();
    audioStartedForCurrentId = false;
    pendingAudioId = "";
    pendingTurnId = "";
    pendingChunkIndex = -1;
    pendingChunkCount = 0;
  }
}

void handleServerText(uint8_t* payload, size_t length) {
  JsonDocument document;
  const DeserializationError error = deserializeJson(document, payload, length);
  if (error) {
    return;
  }

  const String type = document["type"] | "";
  if (document["session_id"].is<const char*>()) {
    sessionId = document["session_id"].as<String>();
  }

  if (type == "status") {
    setRing(18, 0, 18);
    return;
  }
  if (type == "speaking") {
    const String status = document["status"] | "";
    serverSpeaking = status == "start";
    setRing(serverSpeaking ? 18 : 18, 0, serverSpeaking ? 40 : 18);
    if (!serverSpeaking) {
      setIdleOutputLow();
    }
    return;
  }
  if (type == "audio_chunk") {
    pendingAudioId = document["audio_id"].as<String>();
    pendingTurnId = document["turn_id"].as<String>();
    pendingChunkIndex = document["chunk_index"] | -1;
    pendingChunkCount = document["chunk_count"] | 0;
    serverSpeaking = true;
    return;
  }
  if (type == "stop_audio" || type == "turn_cancelled") {
    stopRemotePlayback(false);
    return;
  }
  if (type == "audio_output" && String(document["stage"] | "") == "failed") {
    stopRemotePlayback(false);
    localServiceAlert();
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
      socketConnected = true;
      socketFailureNotified = false;
      setRing(18, 0, 18);
      Serial.println("DEVICE_VOICE_CONNECTED");
      break;
    case WStype_DISCONNECTED:
      socketConnected = false;
      stopRemotePlayback(false);
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
      if (pendingAudioId.length()) {
        playPcmChunk(payload, length);
      }
      break;
    case WStype_ERROR:
      socketConnected = false;
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

void streamMicrophoneFrame() {
  size_t bytesRead = 0;
  i2s_read(
    MIC_I2S_PORT,
    micInput,
    sizeof(micInput),
    &bytesRead,
    pdMS_TO_TICKS(25)
  );
  const size_t samples = bytesRead / sizeof(int32_t);
  if (!socketConnected || serverSpeaking || samples == 0) {
    return;
  }

  for (size_t index = 0; index < samples; ++index) {
    int32_t value = micInput[index] >> 13;
    value *= 2;
    value = constrain(value, -32768, 32767);
    micPcm[index] = static_cast<int16_t>(value);
  }
  webSocket.sendBIN(
    reinterpret_cast<uint8_t*>(micPcm),
    samples * sizeof(int16_t)
  );
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
  showBootVersionSignal();

  Serial.println("LINGOU_DEVICE_FIRMWARE=lingou-device-v1");
  Serial.println("PINS=LED18,FSR16,MIC5/7/4,SPK6/15/17");
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
  if (!configurationReady) {
    delay(100);
    return;
  }

  connectWiFi();
  if (WiFi.status() != WL_CONNECTED) {
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
  checkPhysicalCancellation();
  streamMicrophoneFrame();
}
