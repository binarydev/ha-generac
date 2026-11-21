> [!WARNING]
> This is an unofficial Generac MobileLink integration. Generac systems may change at anytime, which would break the functionality of this integration, and it should not be used for anything mission critical. If you would like an alternative for whole-home generators that allows you to drop the need to maintain a MobileLink subscription, please see the ongoing discussions [here](https://github.com/binarydev/ha-generac/issues/227) for local hardware solutions using GenMon and Raspberry Pi's. Shoutout to [Jeff Terrace](https://github.com/jterrace) for his [blog post](https://blog.jeffterrace.com/2025/10/free-from-generac-with-genmon.html) documenting how to set this up, so others can benefit from his experience!
>
> As of July 26, 2026, this integration currently support logging in with your MyGenerac/MobileLink username and password to expose your devices to Home Assistant for monitoring and automation.

# Generac MobileLink/MyGenerac Home Assistant Integration

[![hacs][hacsbadge]][hacs]

**Custom Generac integration component with support for generators and propane tank monitors. It will set up the following platforms.**

| Platform        | Entities created for each generator                                                                                                                                                                                                                                                                                                                                                                                   |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `binary_sensor` | `is_connected`, `is_connecting`, `has_maintenance_alert`, `has_warning`, `missed_exercise`, plus conditional `enrolled_in_vpp`, `active_vpp_event`, `subscription_dunning`                                                                                                                                                                                                                                            |
| `button`        | `reset_service_timer`, `boost_polling`                                                                                                                                                                                                                                                                                                                                                                                |
| `sensor`        | `status`, `run_time`, `protection_time`, `activation_date`, `last_seen`, `connection_time`, `battery_voltage`, `device_type`, `dealer_email`, `dealer_name`, `dealer_phone`, `address`, `status_text`, `status_label`, `error_code`, `serial_number`, `model_number`, `device_ssid`, `panel_id`, `signal_strength`, `hours_until_service`, optional `exercise_minutes`, `outdoor_temperature`, `device_battery_level` |

| Platform        | Entities created for each propane tank monitor                                                                                                                                                                                                   |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `binary_sensor` | `is_connected`, `is_connecting`, `has_maintenance_alert`, `has_warning`, plus conditional `subscription_dunning`                                                                                                                                 |
| `sensor`        | `status`, `capacity`, `fuel_level`, `remaining_fuel`, `estimated_runtime`, `fuel_type`, `orientation`, `last_reading_date`, `battery_level`, `address`, `device_type`, optional `signal_strength`, `device_battery_level`, `outdoor_temperature` |

![example][exampleimg]

## Installation (with HACS)

> _NOTE:_ If you've previously installed this integration, delete it first from Settings -> Integrations and delete the "Custom Repository" entry in HACS (found in HACS -> Integrations -> 3 dot menu on the top right)

Click this button to skip steps 1 and 2 below: [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=binarydev&repository=ha-generac&category=Integration)

1. On the HACS -> Integrations page, click the `Explore & Download Repositories` button
2. Search the list for `generac` and select it to open the details page
3. On the bottom right, click the `Download` button
4. Restart Home Assistant (not the quick reload option)
5. Once Home Assistant comes back online, go to Settings -> Integrations
6. Click the `Add Integration` button
7. Search the list for `generac` and select it
8. Enter your **MyGenerac** email and password (the same credentials
   you use in the MobileLink mobile app).
9. **If your account has two-factor authentication**, a second screen
   asks for the verification code sent by text (SMS), your authenticator
   app, or email. Enter the most recent code and submit. (Push-prompt or
   security-key 2FA can't be completed here — approve the login in the
   MobileLink app, or switch your Generac/ecobee account to code-based
   2FA, then retry.)
10. The integration should initialize and begin pulling your device information within seconds

## Installation (without HACS)

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
2. If you do not have a `custom_components` directory (folder) there, you need to create it.
3. In the `custom_components` directory (folder) create a new folder called `generac`.
4. Download _all_ the files from the `custom_components/generac/` directory (folder) in this repository.
5. Place the files you downloaded in the new directory (folder) you created.
6. Restart Home Assistant
7. In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "generac"
8. Enter your **MyGenerac** email and password (the same credentials
   you use in the MobileLink mobile app).
9. **If your account has two-factor authentication**, a second screen
   asks for the verification code sent by text (SMS), your authenticator
   app, or email. Enter the most recent code and submit. (Push-prompt or
   security-key 2FA can't be completed here — approve the login in the
   MobileLink app, or switch your Generac/ecobee account to code-based
   2FA, then retry.)
10. The integration should initialize and begin pulling your device information within seconds

## Configuration is done in the UI

### Options (`Configure`)

Open **Settings → Devices & services → Generac MobileLink → Configure** to adjust enabled platforms, polling intervals, readiness thresholds, and fuel autonomy calculation:

- **Estimated fuel burn rate (gal/h)** (`fuel_burn_rate`, default `2.2` gal/h LP at typical 50% load): Used by the propane monitor `Estimated Runtime Remaining` (`estimated_runtime`) sensor to convert `Remaining Fuel` (`remaining_fuel`, in gallons) into hours of generator runtime remaining (`remaining_fuel / fuel_burn_rate`).

### Adaptive Polling & Outage Boost

To stay gentle on Generac's rate-limited cloud API during normal standby while reacting quickly during exercises, outages, and warnings, polling adapts automatically between two configurable intervals (both clamped to at least `10` seconds):

- **Idle polling interval (`scan_interval`)**: Default `900` seconds (15 minutes). Used when all devices are idle/ready.
- **Active polling interval (`active_scan_interval`)**: Default `120` seconds (2 minutes), capped at `min(scan_interval, active_scan_interval)` so fast polling never slows down a shorter idle interval.

Fast polling activates automatically whenever any generator is **Running**, **Exercising**, or **Warning**, or when any device reports `isConnecting`, `showWarning`, or `isRunning`. After the fleet returns to idle, fast polling remains active for a `300`-second (5-minute) cooldown before returning to the idle interval.

You can also trigger fast polling manually (for example, from an automation triggered by a utility power-loss sensor) using either:

- **Outage Boost Poll button (`button.<device>_outage_boost_poll`)**: Created for each generator; pressing it immediately refreshes data and enables boost polling for `30` minutes.
- **`generac.boost_polling` action (service)**: Switches loaded entries into boost polling and triggers an immediate refresh. Accepts optional `duration_minutes` (`1`–`120`, default `30`) and optional `entry_id` (targets all loaded Generac entries if omitted).

### Telemetry, Long-Term Statistics & Diagnostics

- **Long-Term Statistics (LTS)**: Operational numeric sensors expose Home Assistant `state_class` (`total_increasing` on `run_time` and `protection_time`; `measurement` on `battery_voltage`, `exercise_minutes`, `outdoor_temperature`, `capacity`, `fuel_level`, `remaining_fuel`, `estimated_runtime`, `signal_strength`, `device_battery_level`, and `hours_until_service`) for history graphs and long-term recorder statistics.
- **Fault, VPP & Subscription Telemetry**: Generators expose active fault codes via `Error Code` (`error_code`), and—when present in the MobileLink payload—Virtual Power Plant status (`enrolled_in_vpp`, `active_vpp_event`) and subscription billing alerts (`subscription_dunning`).
- **Diagnostic Categorization**: Static metadata and diagnostic entities (serial/model/panel ID, device SSID/type, address, dealer contact info, activation/last-seen/connection timestamps, fuel type, tank orientation, signal strength, VPP enrollment, and subscription billing alert) are grouped under Home Assistant's **Diagnostic** entity category to keep primary dashboards uncluttered.

### Readiness Tracking, Maintenance Timer & Repairs Alerts

Each generator automatically tracks exercise activity and maintenance runtime baselines using Home Assistant storage (persisting cleanly across restarts without reloading the integration):

- **Maintenance Service Timer**:
  - `sensor.<generator>_hours_until_service` shows estimated runtime hours remaining until the configured service interval (default `100` hours, configurable via **Options** -> `service_interval_hours`; set to `0` to disable).
  - On first setup, the baseline initializes to the generator's current `run_time` to avoid false day-1 alarms.
  - After completing maintenance (oil change, filter, etc.), press **Reset Maintenance Timer** (`button.<generator>_reset_maintenance_timer`) on the device page to reset the baseline to the current run hours and clear any timer-based Repairs issue immediately.
- **Exercise Readiness Tracking**:
  - `binary_sensor.<generator>_missed_exercise` turns `on` if no `Running`/`Exercising` status or run-hour increase is observed within `exercise_interval_days` (default `16` days to cover weekly and biweekly schedules; set to `0` to disable).
- **Proactive Home Assistant Repairs Alerts**:
  - `low_battery_voltage`: raised when generator starting battery voltage drops below `low_battery_threshold` (default `12.2` V).
  - `missed_exercise`: raised when the generator exceeds `exercise_interval_days` without observed activity.
  - `maintenance_due`: raised when runtime since the last service reset reaches `service_interval_hours` or Mobile Link reports a maintenance alert.
  - `subscription_dunning`: raised when Mobile Link reports a past-due/dunning subscription status.

### Bundled Automation Blueprints

When the integration sets up, three ready-to-use automation blueprints are automatically installed to `<config>/blueprints/automation/generac/`:

1. **Generac Outage Load Shedding** (`generac_outage_load_shedding.yaml`) — Sheds high-draw entities when status transitions to `Running` (ignoring `Exercising` cycles), waits for `Ready` stabilization, and optionally restores previously active loads with a stagger delay.
2. **Generac Fault & Dealer Contact Alert** (`generac_fault_dealer_alert.yaml`) — Sends a notification populated with generator status, diagnostic `status_text`, optional `error_code`, and your preferred dealer's name and phone number on `Warning`, `Stopped`, `Communication Issue`, warning, or maintenance alerts.
3. **Generac Pre-Storm Readiness Digest** (`generac_storm_readiness_digest.yaml`) — Sends a readiness digest with status, connectivity, battery voltage, hours until service, and optional propane fuel level, remaining fuel, and estimated runtime when a weather alert or trigger entity turns `on`.

## Username + Password Authentication

This integration previously used a cookie-fishing authentication workflow. As of PR #267, it has now been replaced by a standard OAuth workflow similar to the mobile app, using your username and password, with auto-refreshing token retrieval. You no longer need to enter your cookie's string!

### Session expiry (every ~90 days)

Generac's sign-in sessions expire 90 days after you log in, no matter how often the integration uses them. You have two options:

- **Remember password** (checkbox at sign-in, reauth and reconfigure): the password is stored in Home Assistant and the integration signs in again on its own when the session expires. This doesn't work for accounts that require a verification code (SMS / email / authenticator), because the code can't be entered unattended.
- **Without it**: a Repairs warning appears about 10 days before expiry. Use **Reconfigure** on the integration to sign in again before your devices stop updating.

> [!IMPORTANT]
>
> ## Fair Warning
>
> Status Quo in summer 2026: This is an unofficial Generac integration, which requires using undocumented APIs in order to access the data of your Generac devices using your username and password. This is because Generac has changed (once again) the authentication workflow to actively block third-party access. They also originally stated that Home Assistant users were overloading their API. We have since adjusted accordingly to adapt to the new authenatication method and reduced our default polling interval from every 30 seconds to every 120 seconds, to be a "good" user of the API and cut the volume of traffic to their servers by 75%. This polling interval can also be tuned to your needs in the options panel of the HA integration once you have set it up, as seen [here](./setup_instructions/options.png).
>
> This approach implies that when Generac is going to change something in their non-public/undocumented API, it's quite likely that the integration will break instantly.
>
> **It's impossible to predict** when this will happen, but **I will try** to keep the integration up-to-date and working **as long as possible**.

<!---->

## Contributions are welcome!

If you want to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md)

## Credits

This project was generated from [@oncleben31](https://github.com/oncleben31)'s [Home Assistant Custom Component Cookiecutter](https://github.com/oncleben31/cookiecutter-homeassistant-custom-component) template.

Code template was mainly taken from [@Ludeeus](https://github.com/ludeeus)'s [integration_blueprint][integration_blueprint] template

Forked from the original implementation created by [@bentekkie](https://github.com/bentekkie/ha-generac)

---

[integration_blueprint]: https://github.com/custom-components/integration_blueprint
[black]: https://github.com/psf/black
[black-shield]: https://img.shields.io/badge/code%20style-black-000000.svg?style=for-the-badge
[buymecoffee]: https://www.buymeacoffee.com/binarydev
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/y/binarydev/ha-generac.svg?style=for-the-badge
[commits]: https://github.com/binarydev/ha-generac/commits/main
[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[discord]: https://discord.gg/Qa5fW2R
[discord-shield]: https://img.shields.io/discord/330944238910963714.svg?style=for-the-badge
[exampleimg]: example.png
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen.svg?style=for-the-badge
[forum]: https://community.home-assistant.io/
[license-shield]: https://img.shields.io/github/license/binarydev/ha-generac.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-%40binarydev-blue.svg?style=for-the-badge
[pre-commit]: https://github.com/pre-commit/pre-commit
[pre-commit-shield]: https://img.shields.io/badge/pre--commit-enabled-brightgreen?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/binarydev/ha-generac.svg?style=for-the-badge
[releases]: https://github.com/binarydev/ha-generac/releases
[user_profile]: https://github.com/binarydev
