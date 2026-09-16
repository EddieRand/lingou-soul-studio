#pragma once

// Copy to device_config.h. That file is ignored by Git.
#define LINGOU_WIFI_SSID "your-wifi-ssid"
#define LINGOU_WIFI_PASSWORD "your-wifi-password"

// Use the host and port reachable from the ESP32, not localhost.
#define LINGOU_SERVER_HOST "192.168.1.100"
#define LINGOU_SERVER_PORT 8000
#define LINGOU_SERVER_USE_TLS 0

// Returned once by scripts/provision_base.py or rotate_device_credential.py.
#define LINGOU_DEVICE_CREDENTIAL "BASE-DEVICE-001.replace-with-device-secret"

// Required when LINGOU_SERVER_USE_TLS is 1. Keep the complete PEM certificate.
#define LINGOU_SERVER_CA_CERT ""
