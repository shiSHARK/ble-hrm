# BLE Heart Rate Monitor (`ble_hrm`)

A local-push, event-driven Home Assistant custom integration for standard Bluetooth SIG Heart Rate Monitors (Service UUID `0x180D`). 

Unlike traditional Bluetooth integrations that rely on fixed polling loops, this integration is built natively around Home Assistant's event-driven Bluetooth framework. It is engineered specifically to maintain rock-solid active GATT streaming over remote **Bluetooth Proxies** (such as ESP32, ESP32-C6, etc.) without dropping connection sockets or freezing background threads.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
![Type](https://img.shields.io/badge/Type-Local__Push-green?style=for-the-badge)

---

## Features

* **True `local_push` Architecture:** Zero polling intervals. The integration stays completely idle until a Bluetooth proxy intercepts a transmission packet, instantly piping real-time updates to your dashboard.
* **Proxy-Network Resilient:** Seamlessly coordinates with Home Assistant Core's `async_register_callback` to track your strap across multiple room proxies dynamically.
* **Smart Offline Handling:** Leveraging `async_track_unavailable`, the integration detects when you take the strap off or when the device enters its hardware deep-sleep state, cleanly transitioning entity states to `unavailable` without corrupting historical database metrics or dropping Python tracebacks.
* **Automatic Discovery:** Automatically captures any standard connectable BLE heart rate monitor (Garmin, Polar, Wahoo, etc.) currently broadcasting its pairing beacon.
* **Exposed Diagnostics:** Exposes a high-precision **Heart Rate (bpm)** sensor and a diagnostic **Battery (%)** sensor.

---

## Installation

### Method 1: HACS (Recommended)

1. Ensure **HACS** is installed and running in your Home Assistant instance.
2. Go to **HACS** > **Integrations**.
3. Click the **three vertical dots** in the top right-hand corner and select **Custom repositories**.
4. Repository URL: `https://github.com/shiSHARK/ble-hrm`
5. Category: `Integration`
6. Click **Add**.
7. Find the newly appeared **BLE Heart Rate Monitor** card, click **Download**, and choose the latest version.
8. **Restart Home Assistant** to load the custom component files.

### Method 2: Manual Installation

1. Download the latest source code zip file from the repository releases.
2. Extract the archive and copy the `custom_components/ble_hrm` directory into your Home Assistant `/config/custom_components/` directory.
3. Your final folder structure must look like this:
   ```text
   config/
   └── custom_components/
       └── ble_hrm/
           ├── __init__.py
           ├── config_flow.py
           ├── const.py
           ├── manifest.json
           └── sensor.py