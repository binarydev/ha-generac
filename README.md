# generac

[![hacs][hacsbadge]][hacs]

**Custom Generac integration component with support for generators and propane tank monitors. It will set up the following platforms.**

| Platform        | Entities created for each generator                                                                                                                                                                                                                                               |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `binary_sensor` | `is_connected`, `is_connecting`, `has_maintenance_alert`, `has_warning`                                                                                                                                                                                                           |
| `sensor`        | `status`, `run_time`, `protection_time`, `activation_date`, `last_seen`, `connection_time`, `battery_voltage`, `device_type`, `dealer_email`, `dealer_name`, `dealer_phone`, `address`, `status_text`, `status_label`, `serial_number`, `model_number`, `device_ssid`, `panel_id` |

| Platform        | Entities created for each propane tank monitor                                                                                 |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `binary_sensor` | `is_connected`, `is_connecting`, `has_maintenance_alert`, `has_warning`                                                        |
| `sensor`        | `status`, `capacity`, `fuel_level`, `fuel_type`, `orientation`, `last_reading_date`, `battery_level`, `address`, `device_type` |

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
8. Enter the credentials you use to login for https://app.mobilelinkgen.com/ and submit the form. As an alternative, if username/password do not work for you, follow the instructions below for Cookie-based authentication.
9. The integration should initialize and begin pulling your device information within seconds

## Installation (without HACS)

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
2. If you do not have a `custom_components` directory (folder) there, you need to create it.
3. In the `custom_components` directory (folder) create a new folder called `generac`.
4. Download _all_ the files from the `custom_components/generac/` directory (folder) in this repository.
5. Place the files you downloaded in the new directory (folder) you created.
6. Restart Home Assistant
7. In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "generac"

## Configuration is done in the UI

## Cookie-based Authentication

Using Username+Password to login is currently broken, due to Generac blocking automated scripts from logging in on the MobileLink app via a Captcha. Instead, the recommended method of authentication is to manually login and retrieve your session cookie. This requires you to do the following:

1. Log into https://app.mobilelinkgen.com/ until you reach the main dashboard with your devices.
2. Open the web-browser Developer Tools aka "devtools" (e.g. in Chrome, right-click the page and hit the Inspect option).
3. Go to the Network tab in the devtools panel and refresh your browser.
4. The Network tab will now have a long list of things it just loaded, but the one you care about is named "dashboard" and should be the first or one of the first items in the list, as seen [here](./setup_instructions/network-tab.png). Select it.
5. Select the "dashboard" item in the list, and it will open a panel to the right-hand side that shows you more details, which looks like [this](./setup_instructions/network-tab-dashboard.jpg).
6. Scroll down in that right-hand panel until you find a field named Cookie, which has a LARGE block of text (it will likely start with the letters "incap_ses", like [this](./setup_instructions/cookie.png)). That large block of text is what you want.
7. Double click the large block of text to select it all.
8. Copy-paste it into the "Session Cookie" field for the Generac setup UI in Home Assistant.
9. Hit submit and enjoy your integration!

> [!IMPORTANT]
>
> ## Unusual Integration Setup
>
> Status Quo in summer 2025: This integration requires an unusual setup process to be able to access the data of your Generac devices. This is because Generac has changed (once again) the original authentication workflow to actively block third-party access. They state that Home Assistant users were overloading their API. We have since adjusted accordingly to adapt to the new authenatication method and reduced our default polling interval from every 30 seconds to every 120 seconds, to be a "good" user of the API and cut the volume of traffic to their servers by 75%. This polling interval can also be tuned to your needs in the options panel of the HA integration once you have set it up, as seen [here](./setup_instructions/options.png).
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
