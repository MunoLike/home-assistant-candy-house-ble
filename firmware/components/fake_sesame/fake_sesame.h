#pragma once

#include "esphome/components/esp32_ble/ble.h"
#include "esphome/core/automation.h"
#include "esphome/core/component.h"

#include <array>
#include <cstdint>
#include <optional>
#include <span>
#include <string>
#include <vector>

#ifdef USE_ESP32

#include <esp_gap_ble_api.h>
#include <esp_gatts_api.h>
#include <mbedtls/ccm.h>

namespace esphome::fake_sesame {

class FakeSesame : public Component,
#ifndef FAKE_SESAME_BLE_CALLBACK_API
                   public esp32_ble::GAPEventHandler,
                   public esp32_ble::GATTsEventHandler,
                   public esp32_ble::BLEStatusEventHandler,
#endif
                   public Parented<esp32_ble::ESP32BLE> {
 public:
  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override;

  void set_device_id(const std::array<uint8_t, 16> &device_id) { this->device_id_ = device_id; }
  void set_secret_key(const std::array<uint8_t, 16> &secret_key) { this->secret_key_ = secret_key; }
  Trigger<std::string> *get_lock_trigger() { return &this->lock_trigger_; }
  Trigger<std::string> *get_unlock_trigger() { return &this->unlock_trigger_; }

  void gap_event_handler(esp_gap_ble_cb_event_t event, esp_ble_gap_cb_param_t *param)
#ifndef FAKE_SESAME_BLE_CALLBACK_API
      override
#endif
      ;
  void gatts_event_handler(esp_gatts_cb_event_t event, esp_gatt_if_t gatts_if,
                           esp_ble_gatts_cb_param_t *param)
#ifndef FAKE_SESAME_BLE_CALLBACK_API
      override
#endif
      ;
  void ble_before_disabled_event_handler()
#ifndef FAKE_SESAME_BLE_CALLBACK_API
      override
#endif
      ;

 protected:
  enum class SetupState : uint8_t {
    WAIT_BLE,
    REGISTERING,
    CREATING_SERVICE,
    ADDING_WRITE_CHARACTERISTIC,
    ADDING_NOTIFY_CHARACTERISTIC,
    ADDING_CCCD,
    STARTING_SERVICE,
    SETTING_ADDRESS,
    CONFIGURING_ADVERTISEMENT,
    READY,
  };

  static constexpr size_t MAX_FRAME_SIZE = 256;
  static constexpr uint16_t INVALID_HANDLE = 0xFFFF;

  void create_service_();
  void add_write_characteristic_();
  void add_notify_characteristic_();
  void add_cccd_();
  void maybe_finish_attributes_();
  void configure_identity_();
  void configure_advertisement_();
  void start_advertising_();
  void reset_session_();
  void close_session_(const char *reason);
  void handle_cccd_write_(const esp_ble_gatts_cb_param_t::gatts_write_evt_param &write);
  void handle_command_write_(std::span<const uint8_t> packet);
  bool feed_segment_(std::span<const uint8_t> packet, uint8_t &segment_type,
                     std::vector<uint8_t> &payload);
  void begin_authenticated_session_();
  void send_initial_();
  void send_mech_setting_();
  void send_mech_status_();
  bool encrypt_(std::span<const uint8_t> plaintext, std::vector<uint8_t> &ciphertext);
  bool decrypt_(std::span<const uint8_t> ciphertext, std::vector<uint8_t> &plaintext);
  bool notify_(uint8_t segment_type, std::span<const uint8_t> payload);
  bool cmac_(std::span<const uint8_t> key, std::span<const uint8_t> input,
             std::span<uint8_t> output);
  static std::optional<std::string> remote_id_from_history_tag_(std::span<const uint8_t> history_tag);
  const char *setup_state_name_() const;
  static bool constant_time_equal_(std::span<const uint8_t> left, std::span<const uint8_t> right);

  std::array<uint8_t, 16> device_id_{};
  std::array<uint8_t, 16> secret_key_{};
  std::array<uint8_t, 16> session_key_{};
  std::array<uint8_t, 4> challenge_{};
  std::array<uint8_t, 6> random_address_{};
  std::array<uint8_t, 30> advertisement_{};

  std::vector<uint8_t> receive_buffer_{};
  uint64_t tx_counter_{0};
  uint64_t rx_counter_{0};

  esp_gatt_if_t gatts_if_{ESP_GATT_IF_NONE};
  uint16_t service_handle_{INVALID_HANDLE};
  uint16_t write_handle_{INVALID_HANDLE};
  uint16_t notify_handle_{INVALID_HANDLE};
  uint16_t cccd_handle_{INVALID_HANDLE};
  uint16_t connection_id_{INVALID_HANDLE};

  SetupState setup_state_{SetupState::WAIT_BLE};
  bool connected_{false};
  bool subscribed_{false};
  bool authenticated_{false};
  bool advertisement_configured_{false};
  bool advertising_started_{false};
  bool locked_{true};

  Trigger<std::string> lock_trigger_{};
  Trigger<std::string> unlock_trigger_{};
};

}  // namespace esphome::fake_sesame

#endif
