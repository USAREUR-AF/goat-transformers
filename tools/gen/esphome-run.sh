#!/bin/bash
# Regenerate the esphome-* packs: one pack per message of the ESPHome native API that
# has a message ID (`option (id)`) and at least one field, from aioesphomeapi's api.proto.
# A pack is named for the entity type first where the message belongs to one
# (esphome-light-state-response, esphome-light-command-request,
# esphome-light-list-entities-response), so the packs of one entity type sort together.
#
# Usage: tools/gen/esphome-run.sh [--check] <checkout> <sources>
#
# With --check nothing in <checkout> is written: the runs write into a temporary copy of
# its model/, packs/ and tools/gen/names/, the copy is compared with <checkout>, every file
# that differs is listed and the exit status is 1 when there is one.
#
# Every run takes names, field numbers and types from the schema files and no comment
# (--no-comments); the notes in pack.md are this repository's own words
# (tools/gen/notes/esphome-api.md). The schema files are not kept in the repository.
#
#   <sources>/api.proto, <sources>/api_options.proto   aioesphomeapi/api.proto and
#     aioesphomeapi/api_options.proto of github.com/esphome/aioesphomeapi at tag v46.30.1,
#     commit e3447e7bf394cecb99caf8c0c969ea32bb4a91fd, each
#     https://raw.githubusercontent.com/esphome/aioesphomeapi/<commit>/aioesphomeapi/<name>
#     MIT License (LICENSE, "Copyright (c) 2018 Otto Winter").
#     google/protobuf/descriptor.proto, which api_options.proto imports for its custom
#     options, is not read: the generator skips that import, as it skips every option.
#
# Not generated: 21 messages with an ID carry nothing a pack could map: 18 have no field
# (ping, the subscribe requests and the like), and DeviceWizardResponse,
# NoiseEncryptionSetKeyRequest and ZWaveProxyFrame hold only bytes fields. The frame around a message on the TCP
# connection (preamble, length and message-type varints, or the Noise frame) is not part
# of a pack: a pack reads one message whose type is already known.
set -euo pipefail
CHECK=0
if [ "${1:-}" = "--check" ]; then
  CHECK=1
  shift
fi
if [ "$#" -ne 2 ]; then
  echo "usage: $0 [--check] <checkout> <sources>" >&2
  exit 2
fi
CHECKOUT="$(cd "$1" && pwd)"
SRC="$(cd "$2" && pwd)"
GEN="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ROOT="$CHECKOUT"
NAMES="$GEN/names"
if [ "$CHECK" = 1 ]; then
  ROOT="$TMP/checkout"
  NAMES="$ROOT/tools/gen/names"
  mkdir -p "$ROOT/tools/gen"
  cp -R "$CHECKOUT/model" "$CHECKOUT/packs" "$ROOT/"
  cp -R "$GEN/names" "$NAMES"
fi
(cd "$SRC" && sha256sum --quiet -c -) <<'SUMS'
f09b0b6ae7ac51ad2189946c67595f320bec96c29b841624a3dfec5150d384bf  api.proto
7a2e0a76abc5f8da60e170b2f217f6b91cc3ddfae18b7c3cd60ab198c99e43e5  api_options.proto
SUMS
TAG=v46.30.1
COMMIT=e3447e7bf394cecb99caf8c0c969ea32bb4a91fd
# <message>:<pack name without the esphome- prefix>
PACKS=(
  HelloRequest:hello-request
  HelloResponse:hello-response
  AuthenticationRequest:authentication-request
  AuthenticationResponse:authentication-response
  DisconnectRequest:disconnect-request
  DeviceInfoResponse:device-info-response
  DeviceCapabilitiesResponse:device-capabilities-response
  WizardInputSetRequest:wizard-input-set-request
  CrashReportResponse:crash-report-response
  ListEntitiesBinarySensorResponse:binary-sensor-list-entities-response
  BinarySensorStateResponse:binary-sensor-state-response
  ListEntitiesCoverResponse:cover-list-entities-response
  CoverStateResponse:cover-state-response
  CoverCommandRequest:cover-command-request
  ListEntitiesFanResponse:fan-list-entities-response
  FanStateResponse:fan-state-response
  FanCommandRequest:fan-command-request
  ListEntitiesLightResponse:light-list-entities-response
  LightStateResponse:light-state-response
  LightCommandRequest:light-command-request
  ListEntitiesSensorResponse:sensor-list-entities-response
  SensorStateResponse:sensor-state-response
  ListEntitiesSwitchResponse:switch-list-entities-response
  SwitchStateResponse:switch-state-response
  SwitchCommandRequest:switch-command-request
  ListEntitiesTextSensorResponse:text-sensor-list-entities-response
  TextSensorStateResponse:text-sensor-state-response
  SubscribeLogsRequest:subscribe-logs-request
  SubscribeLogsResponse:subscribe-logs-response
  NoiseEncryptionSetKeyResponse:noise-encryption-set-key-response
  HomeassistantActionRequest:homeassistant-action-request
  HomeassistantActionResponse:homeassistant-action-response
  SubscribeHomeAssistantStateResponse:subscribe-home-assistant-state-response
  HomeAssistantStateResponse:home-assistant-state-response
  GetTimeResponse:get-time-response
  ListEntitiesServicesResponse:services-list-entities-response
  ExecuteServiceRequest:execute-service-request
  ExecuteServiceResponse:execute-service-response
  ListEntitiesCameraResponse:camera-list-entities-response
  CameraImageResponse:camera-image-response
  CameraImageRequest:camera-image-request
  ListEntitiesClimateResponse:climate-list-entities-response
  ClimateStateResponse:climate-state-response
  ClimateCommandRequest:climate-command-request
  ListEntitiesWaterHeaterResponse:water-heater-list-entities-response
  WaterHeaterStateResponse:water-heater-state-response
  WaterHeaterCommandRequest:water-heater-command-request
  ListEntitiesNumberResponse:number-list-entities-response
  NumberStateResponse:number-state-response
  NumberCommandRequest:number-command-request
  ListEntitiesSelectResponse:select-list-entities-response
  SelectStateResponse:select-state-response
  SelectCommandRequest:select-command-request
  ListEntitiesSirenResponse:siren-list-entities-response
  SirenStateResponse:siren-state-response
  SirenCommandRequest:siren-command-request
  ListEntitiesLockResponse:lock-list-entities-response
  LockStateResponse:lock-state-response
  LockCommandRequest:lock-command-request
  ListEntitiesButtonResponse:button-list-entities-response
  ButtonCommandRequest:button-command-request
  ListEntitiesMediaPlayerResponse:media-player-list-entities-response
  MediaPlayerStateResponse:media-player-state-response
  MediaPlayerCommandRequest:media-player-command-request
  SubscribeBluetoothLEAdvertisementsRequest:subscribe-bluetooth-le-advertisements-request
  BluetoothLEAdvertisementResponse:bluetooth-le-advertisement-response
  BluetoothLERawAdvertisementsResponse:bluetooth-le-raw-advertisements-response
  BluetoothDeviceRequest:bluetooth-device-request
  BluetoothDeviceConnectionResponse:bluetooth-device-connection-response
  BluetoothGATTGetServicesRequest:bluetooth-gatt-get-services-request
  BluetoothGATTGetServicesResponse:bluetooth-gatt-get-services-response
  BluetoothGATTGetServicesDoneResponse:bluetooth-gatt-get-services-done-response
  BluetoothGATTReadRequest:bluetooth-gatt-read-request
  BluetoothGATTReadResponse:bluetooth-gatt-read-response
  BluetoothGATTWriteRequest:bluetooth-gatt-write-request
  BluetoothGATTReadDescriptorRequest:bluetooth-gatt-read-descriptor-request
  BluetoothGATTWriteDescriptorRequest:bluetooth-gatt-write-descriptor-request
  BluetoothGATTNotifyRequest:bluetooth-gatt-notify-request
  BluetoothGATTNotifyDataResponse:bluetooth-gatt-notify-data-response
  BluetoothConnectionsFreeResponse:bluetooth-connections-free-response
  BluetoothGATTErrorResponse:bluetooth-gatt-error-response
  BluetoothGATTWriteResponse:bluetooth-gatt-write-response
  BluetoothGATTNotifyResponse:bluetooth-gatt-notify-response
  BluetoothDevicePairingResponse:bluetooth-device-pairing-response
  BluetoothDeviceUnpairingResponse:bluetooth-device-unpairing-response
  BluetoothDeviceClearCacheResponse:bluetooth-device-clear-cache-response
  BluetoothScannerStateResponse:bluetooth-scanner-state-response
  BluetoothScannerSetModeRequest:bluetooth-scanner-set-mode-request
  SubscribeVoiceAssistantRequest:subscribe-voice-assistant-request
  VoiceAssistantRequest:voice-assistant-request
  VoiceAssistantResponse:voice-assistant-response
  VoiceAssistantEventResponse:voice-assistant-event-response
  VoiceAssistantAudio:voice-assistant-audio
  VoiceAssistantTimerEventResponse:voice-assistant-timer-event-response
  VoiceAssistantAnnounceRequest:voice-assistant-announce-request
  VoiceAssistantAnnounceFinished:voice-assistant-announce-finished
  VoiceAssistantConfigurationRequest:voice-assistant-configuration-request
  VoiceAssistantConfigurationResponse:voice-assistant-configuration-response
  VoiceAssistantSetConfiguration:voice-assistant-set-configuration
  ListEntitiesAlarmControlPanelResponse:alarm-control-panel-list-entities-response
  AlarmControlPanelStateResponse:alarm-control-panel-state-response
  AlarmControlPanelCommandRequest:alarm-control-panel-command-request
  ListEntitiesTextResponse:text-list-entities-response
  TextStateResponse:text-state-response
  TextCommandRequest:text-command-request
  ListEntitiesDateResponse:date-list-entities-response
  DateStateResponse:date-state-response
  DateCommandRequest:date-command-request
  ListEntitiesTimeResponse:time-list-entities-response
  TimeStateResponse:time-state-response
  TimeCommandRequest:time-command-request
  ListEntitiesEventResponse:event-list-entities-response
  EventResponse:event-response
  ListEntitiesValveResponse:valve-list-entities-response
  ValveStateResponse:valve-state-response
  ValveCommandRequest:valve-command-request
  ListEntitiesDateTimeResponse:date-time-list-entities-response
  DateTimeStateResponse:date-time-state-response
  DateTimeCommandRequest:date-time-command-request
  ListEntitiesUpdateResponse:update-list-entities-response
  UpdateStateResponse:update-state-response
  UpdateCommandRequest:update-command-request
  ZWaveProxyRequest:z-wave-proxy-request
  ZWaveProxyRequestResponse:z-wave-proxy-request-response
  ListEntitiesInfraredResponse:infrared-list-entities-response
  InfraredRFTransmitRawTimingsRequest:infrared-rf-transmit-raw-timings-request
  InfraredRFReceiveEvent:infrared-rf-receive-event
  InfraredRFTransmitCompleteResponse:infrared-rf-transmit-complete-response
  ListEntitiesRadioFrequencyResponse:radio-frequency-list-entities-response
  SerialProxyConfigureRequest:serial-proxy-configure-request
  SerialProxyDataReceived:serial-proxy-data-received
  SerialProxyWriteRequest:serial-proxy-write-request
  SerialProxySetModemPinsRequest:serial-proxy-set-modem-pins-request
  SerialProxyGetModemPinsRequest:serial-proxy-get-modem-pins-request
  SerialProxyGetModemPinsResponse:serial-proxy-get-modem-pins-response
  SerialProxyRequest:serial-proxy-request
  SerialProxyRequestResponse:serial-proxy-request-response
  SerialProxySetModeRequest:serial-proxy-set-mode-request
  SerialProxyIdentity:serial-proxy-identity
  BluetoothSetConnectionParamsRequest:bluetooth-set-connection-params-request
  BluetoothSetConnectionParamsResponse:bluetooth-set-connection-params-response
  SendspinPairingTokenResponse:sendspin-pairing-token-response
  GetYamlResponse:get-yaml-response
)
for p in "${PACKS[@]}"; do
  msg="${p%%:*}"
  name="${p#*:}"
  python3 -I "$GEN/proto2pack.py" --out "$ROOT" --no-comments --pack-version 0.1.0 \
    --proto "$SRC/api.proto" "$SRC/api_options.proto" \
    --envelope "$msg" --format "esphome-$name" --module "esphome${name//-/}" \
    --source "ESPHome native API, aioesphomeapi api.proto and api_options.proto: github.com/esphome/aioesphomeapi tag $TAG, commit $COMMIT; envelope $msg; field numbers, names and types only" \
    --source "LICENSE at that commit: MIT License, Copyright (c) 2018 Otto Winter" \
    --names-file "$NAMES/esphome-$name.json" \
    --notes-file "$GEN/notes/esphome-api.md" > /dev/null
done

if [ "$CHECK" = 1 ]; then
  DIFFERS=0
  diff -rq "$CHECKOUT/model" "$ROOT/model" >&2 || DIFFERS=1
  diff -rq "$CHECKOUT/packs" "$ROOT/packs" >&2 || DIFFERS=1
  diff -rq "$GEN/names" "$NAMES" >&2 || DIFFERS=1
  if [ "$DIFFERS" = 1 ]; then
    echo "esphome-run: --check: the files above are not what the generator writes" >&2
    exit 1
  fi
  echo "esphome-run: --check: ok, model/, packs/ and tools/gen/names/ are what the generator writes" >&2
fi
