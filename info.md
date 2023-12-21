# generac

[![hacs][hacsbadge]][hacs]

**This component will set up the following platforms.**

| Platform        | Entities created for each generator                                                                           |
| --------------- | ------------------------------------------------------------------------------------------------------------- |
| `binary_sensor` | `is_connected`, `is_connecting`, `has_maintenance_alert`, `has_warning`                                       |
| `sensor`        | `status`, `run_time`, `protection_time`, `activation_date`, `last_seen`, `connection_time`, `battery_voltage` |

![example][exampleimg]

{% if not installed %}

## Installation

1. Click install.
1. In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "generac".

{% endif %}

## Configuration is done in the UI

<!---->

## Credits

This project was generated from [@oncleben31](https://github.com/oncleben31)'s [Home Assistant Custom Component Cookiecutter](https://github.com/oncleben31/cookiecutter-homeassistant-custom-component) template.

Code template was mainly taken from [@Ludeeus](https://github.com/ludeeus)'s [integration_blueprint][integration_blueprint] template

Forked from the original implementation created by [@bentekkie](https://github.com/bentekkie/ha-generac)

---

[integration_blueprint]: https://github.com/custom-components/integration_blueprint
[buymecoffee]: https://www.buymeacoffee.com/ludeeus
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[commits-shield]: https://img.shields.io/github/commit-activity/y/bentekkie/ha-generac.svg?style=for-the-badge
[commits]: https://github.com/binarydev/ha-generac/commits/main
[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[discord]: https://discord.gg/Qa5fW2R
[discord-shield]: https://img.shields.io/discord/330944238910963714.svg?style=for-the-badge
[exampleimg]: example.png
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen.svg?style=for-the-badge
[forum]: https://community.home-assistant.io/
[license]: https://github.com/binarydev/ha-generac/blob/main/LICENSE
[license-shield]: https://img.shields.io/github/license/bentekkie/ha-generac.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-%40bentekkie-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/bentekkie/ha-generac.svg?style=for-the-badge
[releases]: https://github.com/binarydev/ha-generac/releases
[user_profile]: https://github.com/binarydev
