#pragma once

#include <stddef.h>
#include <stdint.h>

namespace lingou::hal {

struct AudioFormat {
  uint32_t sample_rate_hz;
  uint8_t channels;
  uint8_t sample_width_bytes;
  uint16_t frame_duration_ms;
  size_t max_frame_bytes;
};

struct AudioFrame {
  const uint8_t* data;
  size_t length;
  uint32_t sequence;
  uint64_t monotonic_ms;
};

enum class IndicatorState : uint8_t {
  kBooting,
  kProvisioning,
  kOffline,
  kConnecting,
  kListening,
  kThinking,
  kSpeaking,
  kInterrupted,
  kError,
};

enum class InputEventKind : uint8_t {
  kLightTouch,
  kHeavyPress,
  kDoubleTap,
  kButtonPress,
  kFactoryResetHold,
};

struct InputEvent {
  InputEventKind kind;
  uint64_t monotonic_ms;
  int32_t raw_value;
};

enum class NetworkState : uint8_t {
  kOffline,
  kConnecting,
  kOnline,
  kDegraded,
};

struct NetworkSnapshot {
  NetworkState state;
  int32_t rssi_dbm;
  uint32_t reconnect_attempts;
};

struct ResourceSnapshot {
  uint64_t monotonic_ms;
  size_t free_heap_bytes;
  size_t minimum_free_heap_bytes;
  size_t free_psram_bytes;
};

class LifecyclePort {
 public:
  virtual ~LifecyclePort() = default;
  virtual bool Start() = 0;
  virtual void Stop() = 0;
};

class MicrophonePort : public LifecyclePort {
 public:
  virtual AudioFormat Format() const = 0;
  virtual bool ReadFrame(AudioFrame* frame, uint32_t timeout_ms) = 0;
  virtual size_t DiscardBufferedFrames() = 0;
};

class SpeakerPort : public LifecyclePort {
 public:
  virtual AudioFormat Format() const = 0;
  virtual bool WriteFrame(const AudioFrame& frame, uint32_t timeout_ms) = 0;
  virtual void Abort() = 0;
};

class IndicatorPort : public LifecyclePort {
 public:
  virtual void SetState(IndicatorState state) = 0;
};

class InputPort : public LifecyclePort {
 public:
  virtual bool NextEvent(InputEvent* event, uint32_t timeout_ms) = 0;
};

class NetworkPort : public LifecyclePort {
 public:
  virtual bool Connect() = 0;
  virtual void Disconnect() = 0;
  virtual NetworkSnapshot Snapshot() const = 0;
};

class ClockPort {
 public:
  virtual ~ClockPort() = default;
  virtual uint64_t MonotonicMs() const = 0;
};

class SecureStoragePort : public LifecyclePort {
 public:
  virtual bool ReadSecret(
      const char* key,
      uint8_t* output,
      size_t output_size,
      size_t* actual_size) = 0;
  virtual bool WriteSecret(
      const char* key,
      const uint8_t* value,
      size_t value_size) = 0;
  virtual bool DeleteSecret(const char* key) = 0;
};

class ResourceMonitorPort : public LifecyclePort {
 public:
  virtual ResourceSnapshot Snapshot() const = 0;
};

struct DeviceHAL {
  MicrophonePort* microphone;
  SpeakerPort* speaker;
  IndicatorPort* indicator;
  InputPort* inputs;
  NetworkPort* network;
  ClockPort* clock;
  SecureStoragePort* secure_storage;
  ResourceMonitorPort* resources;
};

}  // namespace lingou::hal
