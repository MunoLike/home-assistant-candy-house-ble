#include "fake_sesame.h"

#ifdef USE_ESP32

#include "esphome/core/log.h"

#include <algorithm>
#include <array>
#include <ctime>
#include <cstring>

#include <esp_random.h>
#include <mbedtls/cipher.h>
#include <mbedtls/cmac.h>

// Bluedroid deliberately keeps its handle-range API out of ESP-IDF's public
// include path.  The function is nevertheless part of libbt and is what the
// stack itself uses to restore stable service handles.  Keep the small ABI
// mirror local, and fail compilation if the IDF layout ever changes.
struct BluedroidUuid {
  uint16_t len;
  union {
    uint16_t uuid16;
    uint32_t uuid32;
    uint8_t uuid128[16];
  } value;
};

struct BluedroidHandleRange {
  BluedroidUuid app_uuid;
  BluedroidUuid service_uuid;
  uint16_t service_instance;
  uint16_t start_handle;
  uint16_t end_handle;
  bool is_primary;
};

static_assert(sizeof(BluedroidUuid) == 20);
static_assert(sizeof(BluedroidHandleRange) == 48);

extern "C" bool GATTS_AddHandleRange(BluedroidHandleRange *handle_range);

namespace esphome::fake_sesame {

static const char *const TAG = "fake_sesame";

static constexpr uint16_t APP_ID = 0x5345;
static constexpr uint16_t SERVICE_UUID = 0xFD81;
static constexpr uint16_t CCCD_UUID = 0x2902;
// CANDY HOUSE remotes address the SESAME characteristic values by their
// firmware-defined ATT handles instead of discovering them.  Bluedroid starts
// application services at handle 40, while a physical SESAME exposes write,
// notify and CCCD at 13, 15 and 16.  Reserving 11-18 makes the ordinary
// service/characteristic creation sequence produce those three exact handles.
static constexpr uint16_t SERVICE_START_HANDLE = 11;
static constexpr uint16_t SERVICE_END_HANDLE = 18;
static constexpr uint8_t SEGMENT_PLAIN = 1;
static constexpr uint8_t SEGMENT_CIPHER = 2;
static constexpr uint8_t OP_RESPONSE = 7;
static constexpr uint8_t OP_PUBLISH = 8;
static constexpr uint8_t ITEM_LOGIN = 2;
static constexpr uint8_t ITEM_VERSION_TAG = 5;
#ifndef FAKE_SESAME_VERSION
#define FAKE_SESAME_VERSION "unknown"
#endif
static constexpr uint8_t ITEM_TIME = 8;
static constexpr uint8_t ITEM_INITIAL = 14;
static constexpr uint8_t ITEM_MECH_SETTING = 80;
static constexpr uint8_t ITEM_MECH_STATUS = 81;
static constexpr uint8_t ITEM_LOCK = 82;
static constexpr uint8_t ITEM_UNLOCK = 83;
static constexpr uint16_t HISTORY_SOURCE_REMOTE = 11;
static constexpr size_t REMOTE_HISTORY_TAG_SIZE = 22;

// ESP-IDF stores 128-bit GATT UUIDs least-significant byte first.
static constexpr std::array<uint8_t, 16> WRITE_UUID{
    0x3E, 0x99, 0x76, 0xC6, 0xB4, 0xDB, 0xD3, 0xB6,
    0x56, 0x98, 0xAE, 0xA5, 0x02, 0x00, 0x86, 0x16,
};
static constexpr std::array<uint8_t, 16> NOTIFY_UUID{
    0x3E, 0x99, 0x76, 0xC6, 0xB4, 0xDB, 0xD3, 0xB6,
    0x56, 0x98, 0xAE, 0xA5, 0x03, 0x00, 0x86, 0x16,
};

void FakeSesame::setup() {
  this->receive_buffer_.reserve(MAX_FRAME_SIZE);
  this->set_interval("fake_sesame_status", 30000, [this]() {
    ESP_LOGI(TAG, "BLE state=%s, advertising=%s, connected=%s, authenticated=%s", this->setup_state_name_(),
             YESNO(this->advertising_started_), YESNO(this->connected_), YESNO(this->authenticated_));
  });
}

void FakeSesame::loop() {
  if (this->setup_state_ != SetupState::WAIT_BLE || !this->parent_->is_active())
    return;
  esp_err_t err = esp_ble_gatts_app_register(APP_ID);
  if (err != ESP_OK) {
    ESP_LOGE(TAG, "Unable to register dedicated GATT server: %s", esp_err_to_name(err));
    this->mark_failed();
    return;
  }
  this->setup_state_ = SetupState::REGISTERING;
}

void FakeSesame::dump_config() {
  ESP_LOGCONFIG(TAG, "Fake SESAME event bridge:");
  ESP_LOGCONFIG(TAG, "  Dedicated BLE peripheral: yes");
  ESP_LOGCONFIG(TAG, "  Remote provisioning: disabled");
  ESP_LOGCONFIG(TAG, "  State: %s", this->setup_state_ == SetupState::READY ? "ready" : "initializing");
}

float FakeSesame::get_setup_priority() const { return setup_priority::AFTER_BLUETOOTH + 20; }

void FakeSesame::create_service_() {
  esp_gatt_srvc_id_t service_id{};
  service_id.is_primary = true;
  service_id.id.inst_id = 0;
  service_id.id.uuid.len = ESP_UUID_LEN_16;
  service_id.id.uuid.uuid.uuid16 = SERVICE_UUID;
  esp_err_t err = esp_ble_gatts_create_service(this->gatts_if_, &service_id, 8);
  if (err != ESP_OK) {
    ESP_LOGE(TAG, "Unable to create SESAME service: %s", esp_err_to_name(err));
    this->mark_failed();
    return;
  }
  this->setup_state_ = SetupState::CREATING_SERVICE;
}

void FakeSesame::add_write_characteristic_() {
  esp_attr_control_t control{};
  control.auto_rsp = ESP_GATT_RSP_BY_APP;

  esp_bt_uuid_t write_uuid{};
  write_uuid.len = ESP_UUID_LEN_128;
  memcpy(write_uuid.uuid.uuid128, WRITE_UUID.data(), WRITE_UUID.size());
  esp_err_t err = esp_ble_gatts_add_char(this->service_handle_, &write_uuid, ESP_GATT_PERM_WRITE,
                                         ESP_GATT_CHAR_PROP_BIT_WRITE | ESP_GATT_CHAR_PROP_BIT_WRITE_NR,
                                         nullptr, &control);
  if (err != ESP_OK) {
    ESP_LOGE(TAG, "Unable to add SESAME write characteristic: %s", esp_err_to_name(err));
    this->mark_failed();
    return;
  }
  this->setup_state_ = SetupState::ADDING_WRITE_CHARACTERISTIC;
}

void FakeSesame::add_notify_characteristic_() {
  esp_attr_control_t control{};
  control.auto_rsp = ESP_GATT_RSP_BY_APP;
  esp_bt_uuid_t notify_uuid{};
  notify_uuid.len = ESP_UUID_LEN_128;
  memcpy(notify_uuid.uuid.uuid128, NOTIFY_UUID.data(), NOTIFY_UUID.size());
  esp_err_t err = esp_ble_gatts_add_char(this->service_handle_, &notify_uuid, ESP_GATT_PERM_READ,
                                         ESP_GATT_CHAR_PROP_BIT_NOTIFY, nullptr, &control);
  if (err != ESP_OK) {
    ESP_LOGE(TAG, "Unable to add SESAME notify characteristic: %s", esp_err_to_name(err));
    this->mark_failed();
    return;
  }
  this->setup_state_ = SetupState::ADDING_NOTIFY_CHARACTERISTIC;
}

void FakeSesame::add_cccd_() {
  esp_bt_uuid_t descriptor_uuid{};
  descriptor_uuid.len = ESP_UUID_LEN_16;
  descriptor_uuid.uuid.uuid16 = CCCD_UUID;
  esp_attr_control_t control{};
  control.auto_rsp = ESP_GATT_RSP_BY_APP;
  esp_err_t err = esp_ble_gatts_add_char_descr(this->service_handle_, &descriptor_uuid,
                                                ESP_GATT_PERM_READ | ESP_GATT_PERM_WRITE, nullptr, &control);
  if (err != ESP_OK) {
    ESP_LOGE(TAG, "Unable to add SESAME notification descriptor: %s", esp_err_to_name(err));
    this->mark_failed();
    return;
  }
  this->setup_state_ = SetupState::ADDING_CCCD;
}

void FakeSesame::maybe_finish_attributes_() {
  if (this->write_handle_ == INVALID_HANDLE || this->notify_handle_ == INVALID_HANDLE ||
      this->cccd_handle_ == INVALID_HANDLE || this->setup_state_ != SetupState::ADDING_CCCD)
    return;
  ESP_LOGI(TAG, "SESAME GATT handles: service=%u write=%u notify=%u cccd=%u", this->service_handle_,
           this->write_handle_, this->notify_handle_, this->cccd_handle_);
  esp_err_t err = esp_ble_gatts_start_service(this->service_handle_);
  if (err != ESP_OK) {
    ESP_LOGE(TAG, "Unable to start SESAME service: %s", esp_err_to_name(err));
    this->mark_failed();
    return;
  }
  this->setup_state_ = SetupState::STARTING_SERVICE;
}

void FakeSesame::configure_identity_() {
  std::array<uint8_t, 16> token{};
  const std::array<uint8_t, 5> candy{'c', 'a', 'n', 'd', 'y'};
  if (!this->cmac_(this->device_id_, candy, token)) {
    this->mark_failed();
    return;
  }
  // CANDY HOUSE derives a controller-order address from token[0:6] and sets
  // the static-random bits in byte 5. esp_bd_addr_t uses displayed/network
  // byte order, so reverse those six bytes before passing them to ESP-IDF.
  std::reverse_copy(token.begin(), token.begin() + this->random_address_.size(), this->random_address_.begin());
  this->random_address_[0] = (this->random_address_[0] & 0x3F) | 0xC0;

  this->setup_state_ = SetupState::SETTING_ADDRESS;
  esp_err_t err = esp_ble_gap_set_rand_addr(this->random_address_.data());
  if (err != ESP_OK) {
    ESP_LOGE(TAG, "Unable to set fake-device BLE address: %s", esp_err_to_name(err));
    this->mark_failed();
    return;
  }
#ifdef FAKE_SESAME_BLE_CALLBACK_API
  // ESPHome 2026.7 no longer forwards ESP_GAP_BLE_SET_STATIC_RAND_ADDR_EVT
  // to registered GAP callbacks. Give the controller command time to settle,
  // then continue without waiting for an event that this component cannot see.
  this->set_timeout("fake_sesame_address", 75, [this]() {
    if (this->setup_state_ == SetupState::SETTING_ADDRESS && this->parent_->is_active())
      this->configure_advertisement_();
  });
#endif
}

void FakeSesame::configure_advertisement_() {
  const std::array<uint8_t, 10> prefix{2, 1, 6, 0x16, 0xFF, 0x5A, 0x05, 5, 0, 1};
  std::copy(prefix.begin(), prefix.end(), this->advertisement_.begin());
  std::copy(this->device_id_.begin(), this->device_id_.end(), this->advertisement_.begin() + prefix.size());
  const std::array<uint8_t, 4> suffix{3, 3, 0x81, 0xFD};
  std::copy(suffix.begin(), suffix.end(), this->advertisement_.end() - suffix.size());

  esp_err_t err = esp_ble_gap_config_adv_data_raw(this->advertisement_.data(), this->advertisement_.size());
  if (err != ESP_OK) {
    ESP_LOGE(TAG, "Unable to configure SESAME advertisement: %s", esp_err_to_name(err));
    this->mark_failed();
    return;
  }
  this->setup_state_ = SetupState::CONFIGURING_ADVERTISEMENT;
}

void FakeSesame::start_advertising_() {
  if (!this->advertisement_configured_ || this->connected_)
    return;
  this->advertising_started_ = false;
  esp_ble_adv_params_t params{};
  params.adv_int_min = 0x20;
  params.adv_int_max = 0x40;
  params.adv_type = ADV_TYPE_IND;
  params.own_addr_type = BLE_ADDR_TYPE_RANDOM;
  params.channel_map = ADV_CHNL_ALL;
  params.adv_filter_policy = ADV_FILTER_ALLOW_SCAN_ANY_CON_ANY;
  esp_err_t err = esp_ble_gap_start_advertising(&params);
  if (err != ESP_OK)
    ESP_LOGW(TAG, "Unable to start SESAME advertisement: %s", esp_err_to_name(err));
}

void FakeSesame::reset_session_() {
  this->cancel_timeout("fake_sesame_login");
  this->cancel_timeout("fake_sesame_initial");
  this->cancel_timeout("fake_sesame_initial_retry_1");
  this->cancel_timeout("fake_sesame_initial_retry_2");
  this->cancel_timeout("fake_sesame_mech_setting");
  this->cancel_timeout("fake_sesame_mech_status");
  this->subscribed_ = false;
  this->authenticated_ = false;
  this->tx_counter_ = 0;
  this->rx_counter_ = 0;
  this->receive_buffer_.clear();
  this->challenge_.fill(0);
  this->session_key_.fill(0);
}

void FakeSesame::close_session_(const char *reason) {
  ESP_LOGW(TAG, "Closing invalid Remote session: %s", reason);
  this->reset_session_();
  if (this->connected_)
    esp_ble_gatts_close(this->gatts_if_, this->connection_id_);
}

void FakeSesame::handle_cccd_write_(const esp_ble_gatts_cb_param_t::gatts_write_evt_param &write) {
  if (write.need_rsp)
    esp_ble_gatts_send_response(this->gatts_if_, write.conn_id, write.trans_id, ESP_GATT_OK, nullptr);
  if (write.len != 2 || write.value[0] != 1 || write.value[1] != 0) {
    this->subscribed_ = false;
    return;
  }
  this->reset_session_();
  this->subscribed_ = true;
  ESP_LOGI(TAG, "Remote enabled SESAME notifications");
  this->begin_authenticated_session_();
  this->set_timeout("fake_sesame_login", 15000, [this]() {
    if (this->connected_ && !this->authenticated_)
      this->close_session_("login timeout");
  });
  this->set_timeout("fake_sesame_initial", 150, [this]() { this->send_initial_(); });
  this->set_timeout("fake_sesame_initial_retry_1", 750, [this]() { this->send_initial_(); });
  this->set_timeout("fake_sesame_initial_retry_2", 2000, [this]() { this->send_initial_(); });
}

void FakeSesame::begin_authenticated_session_() {
  esp_fill_random(this->challenge_.data(), this->challenge_.size());
  if (!this->cmac_(this->secret_key_, this->challenge_, this->session_key_))
    this->close_session_("session derivation failed");
}

void FakeSesame::send_initial_() {
  if (!this->connected_ || !this->subscribed_ || this->authenticated_)
    return;
  std::array<uint8_t, 6> payload{OP_PUBLISH, ITEM_INITIAL, 0, 0, 0, 0};
  std::copy(this->challenge_.begin(), this->challenge_.end(), payload.begin() + 2);
  ESP_LOGI(TAG, "Sending SESAME initial notification");
  if (!this->notify_(SEGMENT_PLAIN, payload))
    this->close_session_("initial notification failed");
}

void FakeSesame::send_mech_status_() {
  if (!this->connected_ || !this->subscribed_ || !this->authenticated_)
    return;
  // A plausible stationary SESAME 5 mechanism state: 6.0 V, no active
  // target, position zero, stopped, and either in or out of lock range.
  std::array<uint8_t, 9> payload{
      OP_PUBLISH, ITEM_MECH_STATUS, 0x70, 0x17, 0x00, 0x80, 0x00, 0x00,
      static_cast<uint8_t>(0x10 | (this->locked_ ? 0x02 : 0x00)),
  };
  std::vector<uint8_t> ciphertext;
  if (!this->encrypt_(payload, ciphertext) || !this->notify_(SEGMENT_CIPHER, ciphertext))
    this->close_session_("mechanism status notification failed");
}

void FakeSesame::send_mech_setting_() {
  if (!this->connected_ || !this->subscribed_ || !this->authenticated_)
    return;
  // Lock position 0, unlock position 256, and auto-lock disabled. Publishing
  // this before the logged-in mechanism state satisfies the official app's
  // non-null settings assumption without exposing a writable fake setting.
  const std::array<uint8_t, 8> payload{
      OP_PUBLISH, ITEM_MECH_SETTING, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00,
  };
  std::vector<uint8_t> ciphertext;
  if (!this->encrypt_(payload, ciphertext) || !this->notify_(SEGMENT_CIPHER, ciphertext))
    this->close_session_("mechanism setting notification failed");
}

bool FakeSesame::feed_segment_(std::span<const uint8_t> packet, uint8_t &segment_type,
                               std::vector<uint8_t> &payload) {
  if (packet.empty()) {
    this->close_session_("empty segment");
    return false;
  }
  const uint8_t header = packet[0];
  const bool is_start = (header & 1) != 0;
  segment_type = header >> 1;
  if (is_start) {
    this->receive_buffer_.assign(packet.begin() + 1, packet.end());
  } else if (this->receive_buffer_.empty()) {
    this->close_session_("orphan continuation");
    return false;
  } else {
    this->receive_buffer_.insert(this->receive_buffer_.end(), packet.begin() + 1, packet.end());
  }
  if (this->receive_buffer_.size() > MAX_FRAME_SIZE) {
    this->close_session_("oversized frame");
    return false;
  }
  if (segment_type == 0)
    return false;
  if (segment_type != SEGMENT_PLAIN && segment_type != SEGMENT_CIPHER) {
    this->close_session_("unsupported segment type");
    return false;
  }
  payload = std::move(this->receive_buffer_);
  this->receive_buffer_.clear();
  return true;
}

void FakeSesame::handle_command_write_(std::span<const uint8_t> packet) {
  uint8_t segment_type = 0;
  std::vector<uint8_t> payload;
  if (!this->feed_segment_(packet, segment_type, payload))
    return;

  if (!this->authenticated_) {
    if (segment_type != SEGMENT_PLAIN || payload.size() != 5 || payload[0] != ITEM_LOGIN ||
        !constant_time_equal_(std::span<const uint8_t>(payload).subspan(1, 4),
                              std::span<const uint8_t>(this->session_key_).first(4))) {
      this->close_session_("authentication failed");
      return;
    }
    this->authenticated_ = true;
    this->cancel_timeout("fake_sesame_login");
    this->cancel_timeout("fake_sesame_initial");
    this->cancel_timeout("fake_sesame_initial_retry_1");
    this->cancel_timeout("fake_sesame_initial_retry_2");
    ESP_LOGI(TAG, "Remote authenticated");
    uint32_t now = static_cast<uint32_t>(std::max<std::time_t>(0, std::time(nullptr)));
    std::array<uint8_t, 7> response{
        OP_RESPONSE, ITEM_LOGIN, 0, static_cast<uint8_t>(now), static_cast<uint8_t>(now >> 8),
        static_cast<uint8_t>(now >> 16), static_cast<uint8_t>(now >> 24)};
    std::vector<uint8_t> ciphertext;
    if (!this->encrypt_(response, ciphertext) || !this->notify_(SEGMENT_CIPHER, ciphertext))
      this->close_session_("login response failed");
    else {
      this->set_timeout("fake_sesame_mech_setting", 75, [this]() { this->send_mech_setting_(); });
      this->set_timeout("fake_sesame_mech_status", 150, [this]() { this->send_mech_status_(); });
    }
    return;
  }

  if (segment_type != SEGMENT_CIPHER) {
    this->close_session_("plaintext command");
    return;
  }
  std::vector<uint8_t> plaintext;
  if (!this->decrypt_(payload, plaintext) || plaintext.empty()) {
    this->close_session_("command authentication failed");
    return;
  }
  const uint8_t item = plaintext[0];
  if (item == ITEM_VERSION_TAG && plaintext.size() != 1) {
    this->close_session_("invalid version command");
    return;
  }
  if (item == ITEM_TIME && plaintext.size() != 5) {
    this->close_session_("invalid time command");
    return;
  }
  if (item != ITEM_VERSION_TAG && item != ITEM_TIME && item != ITEM_LOCK && item != ITEM_UNLOCK) {
    ESP_LOGW(TAG, "Unsupported authenticated command item=%u, payload_length=%u", item,
             static_cast<unsigned>(plaintext.size() - 1));
    this->close_session_("unsupported command");
    return;
  }

  std::vector<uint8_t> response{OP_RESPONSE, item, 0};
  if (item == ITEM_VERSION_TAG) {
    static constexpr char VERSION[] = "fake-" FAKE_SESAME_VERSION;
    response.insert(response.end(), VERSION, VERSION + sizeof(VERSION) - 1);
  }
  std::vector<uint8_t> ciphertext;
  if (!this->encrypt_(response, ciphertext) || !this->notify_(SEGMENT_CIPHER, ciphertext)) {
    this->close_session_("command response failed");
    return;
  }
  if (item == ITEM_VERSION_TAG || item == ITEM_TIME)
    return;
  this->locked_ = item == ITEM_LOCK;
  auto remote_id = remote_id_from_history_tag_(std::span<const uint8_t>(plaintext).subspan(1));
  if (remote_id.has_value()) {
    ESP_LOGD(TAG, "Authenticated Remote command item=%u remote_id_suffix=%s", item,
             remote_id->substr(remote_id->size() - 8).c_str());
    if (item == ITEM_LOCK)
      this->lock_trigger_.trigger(*remote_id);
    else
      this->unlock_trigger_.trigger(*remote_id);
  } else {
    ESP_LOGD(TAG, "Authenticated non-Remote command item=%u history_tag_length=%u", item,
             static_cast<unsigned>(plaintext.size() - 1));
  }
  this->set_timeout("fake_sesame_mech_status", 40, [this]() { this->send_mech_status_(); });
}

std::optional<std::string> FakeSesame::remote_id_from_history_tag_(std::span<const uint8_t> history_tag) {
  if (history_tag.size() != REMOTE_HISTORY_TAG_SIZE)
    return std::nullopt;
  const uint16_t source = static_cast<uint16_t>(history_tag[0]) << 8 | history_tag[1];
  if (source != HISTORY_SOURCE_REMOTE)
    return std::nullopt;
  // Remote/Nano history tags are source (2 B), stable device UUID (16 B),
  // and a per-press suffix (4 B). The suffix must never become HA identity.
  return format_hex(history_tag.data() + 2, 16);
}

bool FakeSesame::encrypt_(std::span<const uint8_t> plaintext, std::vector<uint8_t> &ciphertext) {
  std::array<uint8_t, 13> nonce{};
  for (size_t index = 0; index < 8; index++)
    nonce[index] = static_cast<uint8_t>(this->tx_counter_ >> (8 * index));
  std::copy(this->challenge_.begin(), this->challenge_.end(), nonce.begin() + 9);
  const uint8_t aad = 0;
  ciphertext.resize(plaintext.size() + 4);
  mbedtls_ccm_context context;
  mbedtls_ccm_init(&context);
  int result = mbedtls_ccm_setkey(&context, MBEDTLS_CIPHER_ID_AES, this->session_key_.data(), 128);
  if (result == 0) {
    result = mbedtls_ccm_encrypt_and_tag(&context, plaintext.size(), nonce.data(), nonce.size(), &aad, 1,
                                         plaintext.data(), ciphertext.data(), ciphertext.data() + plaintext.size(), 4);
  }
  mbedtls_ccm_free(&context);
  if (result != 0)
    return false;
  this->tx_counter_++;
  return true;
}

bool FakeSesame::decrypt_(std::span<const uint8_t> ciphertext, std::vector<uint8_t> &plaintext) {
  if (ciphertext.size() < 4)
    return false;
  std::array<uint8_t, 13> nonce{};
  for (size_t index = 0; index < 8; index++)
    nonce[index] = static_cast<uint8_t>(this->rx_counter_ >> (8 * index));
  std::copy(this->challenge_.begin(), this->challenge_.end(), nonce.begin() + 9);
  const uint8_t aad = 0;
  plaintext.resize(ciphertext.size() - 4);
  mbedtls_ccm_context context;
  mbedtls_ccm_init(&context);
  int result = mbedtls_ccm_setkey(&context, MBEDTLS_CIPHER_ID_AES, this->session_key_.data(), 128);
  if (result == 0) {
    result = mbedtls_ccm_auth_decrypt(&context, plaintext.size(), nonce.data(), nonce.size(), &aad, 1,
                                      ciphertext.data(), plaintext.data(), ciphertext.data() + plaintext.size(), 4);
  }
  mbedtls_ccm_free(&context);
  if (result != 0)
    return false;
  this->rx_counter_++;
  return true;
}

bool FakeSesame::notify_(uint8_t segment_type, std::span<const uint8_t> payload) {
  if (!this->connected_ || !this->subscribed_ || payload.empty() || payload.size() > 19)
    return false;
  std::array<uint8_t, 20> packet{};
  packet[0] = static_cast<uint8_t>((segment_type << 1) | 1);
  std::copy(payload.begin(), payload.end(), packet.begin() + 1);
  esp_err_t err = esp_ble_gatts_send_indicate(this->gatts_if_, this->connection_id_, this->notify_handle_,
                                               payload.size() + 1, packet.data(), false);
  return err == ESP_OK;
}

bool FakeSesame::cmac_(std::span<const uint8_t> key, std::span<const uint8_t> input,
                       std::span<uint8_t> output) {
  if (key.size() != 16 || output.size() < 16)
    return false;
  const mbedtls_cipher_info_t *cipher = mbedtls_cipher_info_from_type(MBEDTLS_CIPHER_AES_128_ECB);
  if (cipher == nullptr)
    return false;
  return mbedtls_cipher_cmac(cipher, key.data(), 128, input.data(), input.size(), output.data()) == 0;
}

bool FakeSesame::constant_time_equal_(std::span<const uint8_t> left, std::span<const uint8_t> right) {
  if (left.size() != right.size())
    return false;
  uint8_t difference = 0;
  for (size_t index = 0; index < left.size(); index++)
    difference |= left[index] ^ right[index];
  return difference == 0;
}

const char *FakeSesame::setup_state_name_() const {
  switch (this->setup_state_) {
    case SetupState::WAIT_BLE:
      return "wait_ble";
    case SetupState::REGISTERING:
      return "registering";
    case SetupState::CREATING_SERVICE:
      return "creating_service";
    case SetupState::ADDING_WRITE_CHARACTERISTIC:
      return "adding_write";
    case SetupState::ADDING_NOTIFY_CHARACTERISTIC:
      return "adding_notify";
    case SetupState::ADDING_CCCD:
      return "adding_cccd";
    case SetupState::STARTING_SERVICE:
      return "starting_service";
    case SetupState::SETTING_ADDRESS:
      return "setting_address";
    case SetupState::CONFIGURING_ADVERTISEMENT:
      return "configuring_advertisement";
    case SetupState::READY:
      return "ready";
  }
  return "unknown";
}

void FakeSesame::gap_event_handler(esp_gap_ble_cb_event_t event, esp_ble_gap_cb_param_t *param) {
  switch (event) {
    case ESP_GAP_BLE_SET_STATIC_RAND_ADDR_EVT:
      if (this->setup_state_ == SetupState::SETTING_ADDRESS) {
        if (param->set_rand_addr_cmpl.status == ESP_BT_STATUS_SUCCESS) {
          this->configure_advertisement_();
        } else {
          ESP_LOGE(TAG, "Unable to apply fake-device BLE address");
          this->mark_failed();
        }
      }
      break;
    case ESP_GAP_BLE_ADV_DATA_RAW_SET_COMPLETE_EVT:
      if (this->setup_state_ == SetupState::CONFIGURING_ADVERTISEMENT &&
          param->adv_data_raw_cmpl.status == ESP_BT_STATUS_SUCCESS) {
        this->advertisement_configured_ = true;
        this->setup_state_ = SetupState::READY;
        this->start_advertising_();
      } else if (this->setup_state_ == SetupState::CONFIGURING_ADVERTISEMENT) {
        ESP_LOGE(TAG, "Unable to apply SESAME advertisement data");
        this->mark_failed();
      }
      break;
    case ESP_GAP_BLE_ADV_START_COMPLETE_EVT:
      if (param->adv_start_cmpl.status == ESP_BT_STATUS_SUCCESS) {
        this->advertising_started_ = true;
        ESP_LOGI(TAG, "SESAME advertisement started");
      } else {
        this->advertising_started_ = false;
        ESP_LOGE(TAG, "Unable to start SESAME advertisement (callback status %d)", param->adv_start_cmpl.status);
      }
      break;
    case ESP_GAP_BLE_ADV_STOP_COMPLETE_EVT:
      this->advertising_started_ = false;
      break;
    default:
      break;
  }
}

void FakeSesame::gatts_event_handler(esp_gatts_cb_event_t event, esp_gatt_if_t gatts_if,
                                     esp_ble_gatts_cb_param_t *param) {
  if (event == ESP_GATTS_REG_EVT && param->reg.app_id == APP_ID) {
    if (param->reg.status != ESP_GATT_OK) {
      this->mark_failed();
      return;
    }
    this->gatts_if_ = gatts_if;
    BluedroidHandleRange handle_range{};
    handle_range.app_uuid.len = ESP_UUID_LEN_16;
    handle_range.app_uuid.value.uuid16 = APP_ID;
    handle_range.service_uuid.len = ESP_UUID_LEN_16;
    handle_range.service_uuid.value.uuid16 = SERVICE_UUID;
    handle_range.service_instance = 0;
    handle_range.start_handle = SERVICE_START_HANDLE;
    handle_range.end_handle = SERVICE_END_HANDLE;
    handle_range.is_primary = true;
    if (!GATTS_AddHandleRange(&handle_range)) {
      ESP_LOGE(TAG, "Unable to reserve SESAME-compatible GATT handles");
      this->mark_failed();
      return;
    }
    this->create_service_();
    return;
  }
  if (this->gatts_if_ == ESP_GATT_IF_NONE || (gatts_if != this->gatts_if_ && gatts_if != ESP_GATT_IF_NONE))
    return;

  switch (event) {
    case ESP_GATTS_CREATE_EVT:
      if (param->create.status == ESP_GATT_OK && param->create.service_id.id.uuid.len == ESP_UUID_LEN_16 &&
          param->create.service_id.id.uuid.uuid.uuid16 == SERVICE_UUID) {
        this->service_handle_ = param->create.service_handle;
        this->add_write_characteristic_();
      } else if (this->setup_state_ == SetupState::CREATING_SERVICE) {
        ESP_LOGE(TAG, "Unable to create SESAME service (callback status %d)", param->create.status);
        this->mark_failed();
      }
      break;
    case ESP_GATTS_ADD_CHAR_EVT:
      if (param->add_char.service_handle != this->service_handle_)
        break;
      if (param->add_char.status != ESP_GATT_OK) {
        ESP_LOGE(TAG, "Unable to add SESAME characteristic (callback status %d)", param->add_char.status);
        this->mark_failed();
        break;
      }
      if (param->add_char.char_uuid.len == ESP_UUID_LEN_128 &&
          memcmp(param->add_char.char_uuid.uuid.uuid128, WRITE_UUID.data(), WRITE_UUID.size()) == 0) {
        this->write_handle_ = param->add_char.attr_handle;
        this->add_notify_characteristic_();
      } else if (param->add_char.char_uuid.len == ESP_UUID_LEN_128 &&
                 memcmp(param->add_char.char_uuid.uuid.uuid128, NOTIFY_UUID.data(), NOTIFY_UUID.size()) == 0) {
        this->notify_handle_ = param->add_char.attr_handle;
        this->add_cccd_();
      }
      break;
    case ESP_GATTS_ADD_CHAR_DESCR_EVT:
      if (param->add_char_descr.service_handle == this->service_handle_ &&
          param->add_char_descr.status == ESP_GATT_OK && param->add_char_descr.descr_uuid.len == ESP_UUID_LEN_16 &&
          param->add_char_descr.descr_uuid.uuid.uuid16 == CCCD_UUID) {
        this->cccd_handle_ = param->add_char_descr.attr_handle;
        this->maybe_finish_attributes_();
      } else if (param->add_char_descr.service_handle == this->service_handle_) {
        ESP_LOGE(TAG, "Unable to add SESAME descriptor (callback status %d)", param->add_char_descr.status);
        this->mark_failed();
      }
      break;
    case ESP_GATTS_START_EVT:
      if (param->start.service_handle == this->service_handle_ && param->start.status == ESP_GATT_OK)
        this->configure_identity_();
      else if (param->start.service_handle == this->service_handle_) {
        ESP_LOGE(TAG, "Unable to start SESAME service (callback status %d)", param->start.status);
        this->mark_failed();
      }
      break;
    case ESP_GATTS_CONNECT_EVT:
      if (this->connected_) {
        esp_ble_gatts_close(this->gatts_if_, param->connect.conn_id);
        break;
      }
      this->advertising_started_ = false;
      this->connected_ = true;
      this->connection_id_ = param->connect.conn_id;
      this->reset_session_();
      ESP_LOGI(TAG, "Remote connected from %02X:%02X:%02X:%02X:%02X:%02X (conn_id=%u)",
               param->connect.remote_bda[0], param->connect.remote_bda[1], param->connect.remote_bda[2],
               param->connect.remote_bda[3], param->connect.remote_bda[4], param->connect.remote_bda[5],
               param->connect.conn_id);
      this->set_timeout("fake_sesame_login", 10000, [this]() {
        if (this->connected_ && !this->authenticated_)
          this->close_session_("login timeout");
      });
      break;
    case ESP_GATTS_DISCONNECT_EVT:
      if (param->disconnect.conn_id == this->connection_id_) {
        this->connected_ = false;
        this->connection_id_ = INVALID_HANDLE;
        this->reset_session_();
        this->start_advertising_();
      }
      break;
    case ESP_GATTS_READ_EVT: {
      ESP_LOGI(TAG, "Remote GATT read handle=%u", param->read.handle);
      esp_gatt_rsp_t response{};
      response.attr_value.handle = param->read.handle;
      if (param->read.handle == this->cccd_handle_) {
        response.attr_value.len = 2;
        response.attr_value.value[0] = this->subscribed_ ? 1 : 0;
        response.attr_value.value[1] = 0;
        esp_ble_gatts_send_response(this->gatts_if_, param->read.conn_id, param->read.trans_id,
                                    ESP_GATT_OK, &response);
      } else if (param->read.handle == this->notify_handle_) {
        response.attr_value.len = 0;
        esp_ble_gatts_send_response(this->gatts_if_, param->read.conn_id, param->read.trans_id,
                                    ESP_GATT_OK, &response);
      } else {
        esp_ble_gatts_send_response(this->gatts_if_, param->read.conn_id, param->read.trans_id,
                                    ESP_GATT_READ_NOT_PERMIT, nullptr);
      }
      break;
    }
    case ESP_GATTS_WRITE_EVT:
      ESP_LOGI(TAG, "Remote GATT write handle=%u length=%u response=%s", param->write.handle,
               param->write.len, YESNO(param->write.need_rsp));
      if (param->write.handle == this->cccd_handle_)
        this->handle_cccd_write_(param->write);
      else if (param->write.handle == this->write_handle_)
        this->handle_command_write_(std::span<const uint8_t>(param->write.value, param->write.len));
      break;
    default:
      break;
  }
}

void FakeSesame::ble_before_disabled_event_handler() {
  this->cancel_timeout("fake_sesame_address");
  this->connected_ = false;
  this->advertisement_configured_ = false;
  this->advertising_started_ = false;
  this->reset_session_();
  this->setup_state_ = SetupState::WAIT_BLE;
  this->gatts_if_ = ESP_GATT_IF_NONE;
  this->service_handle_ = INVALID_HANDLE;
  this->write_handle_ = INVALID_HANDLE;
  this->notify_handle_ = INVALID_HANDLE;
  this->cccd_handle_ = INVALID_HANDLE;
}

}  // namespace esphome::fake_sesame

#endif
