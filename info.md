# Generac MobileLink/MyGenerac

[![hacs][hacsbadge]][hacs]

**Custom Generac integration component with support for generators and propane tank monitors. It will set up the following platforms.**

| Platform        | Entities created for each generator (by `entity_key`)                                                                                                                                                                                                                                                                                                                                                                         |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `binary_sensor` | `is_connected`, `is_connecting`, `has_maintenance_alert`, `show_warning`, `missed_exercise`, plus conditional `enrolled_in_vpp`, `active_vpp_event`, `subscription_dunning`                                                                                                                                                                                                                                                   |
| `button`        | `reset_service_timer`, `boost_polling`                                                                                                                                                                                                                                                                                                                                                                                        |
| `sensor`        | `status`, `run_time`, `protection_time`, `activation_date`, `last_seen`, `connection_time`, `battery_voltage`, `device_type`, `dealer_email`, `dealer_name`, `dealer_phone`, `address`, `status_text`, `status_label`, `error_code`, `serial_number`, `model_number`, `device_ssid`, `panel_id`, `signal_strength`, `hours_until_service`, plus conditional `exercise_minutes`, `outdoor_temperature`, `device_battery_level` |
| `weather`       | conditional `weather`                                                                                                                                                                                                                                                                                                                                                                                                         |
| `image`         | conditional `hero_image`                                                                                                                                                                                                                                                                                                                                                                                                      |

| Platform        | Entities created for each propane tank monitor (by `entity_key`)                                                                                                                                                                                    |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `binary_sensor` | `is_connected`, `is_connecting`, `has_maintenance_alert`, `show_warning`, plus conditional `subscription_dunning`                                                                                                                                   |
| `sensor`        | `status`, `capacity`, `fuel_level`, `remaining_fuel`, `estimated_runtime`, `fuel_type`, `orientation`, `last_reading`, `battery_level`, `address`, `device_type`, plus conditional `signal_strength`, `device_battery_level`, `outdoor_temperature` |
| `weather`       | conditional `weather`                                                                                                                                                                                                                               |
| `image`         | conditional `hero_image`                                                                                                                                                                                                                            |

Includes adaptive cloud polling (`900` s idle / `120` s active) with manual outage boost, long-term statistics, propane fuel autonomy estimates, maintenance/exercise readiness tracking with Repairs alerts, and bundled automation blueprints.

![example][exampleimg]

{% if not installed %}

## Installation

1. Click download/install in HACS and restart Home Assistant.
2. Go to **Settings → Devices & services**, click **Add Integration**, and search for `generac`.
3. Sign in with your **MyGenerac / MobileLink** email and password (code-based SMS, email, and authenticator-app 2FA are supported).
4. The integration will initialize and begin polling your devices within seconds.

{% endif %}

## Configuration is done in the UI

Open **Settings → Devices & services → Generac MobileLink → Configure** to adjust enabled platforms, polling intervals, readiness thresholds, and propane fuel burn rate.

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
