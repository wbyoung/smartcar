# Smartcar Integration for Home Assistant

[![HACS](https://img.shields.io/badge/default-grey?logo=homeassistantcommunitystore&logoColor=white)][hacs-repo]
[![HACS installs](https://img.shields.io/github/downloads/wbyoung/smartcar/latest/total?label=installs&color=blue)][hacs-repo]
[![Version](https://img.shields.io/github/v/release/wbyoung/smartcar)][releases]
![Downloads](https://img.shields.io/github/downloads/wbyoung/smartcar/total)
![Build](https://img.shields.io/github/actions/workflow/status/wbyoung/smartcar/pytest.yml)
[![Github Sponsors](https://img.shields.io/badge/GitHub%20Sponsors-grey?&logo=GitHub-Sponsors&logoColor=EA4AAA)][gh-sponsors]

Connect your compatible vehicle to Home Assistant using the [Smartcar API](https://smartcar.com/).

This integration provides various sensors and controls for vehicles linked through the Smartcar platform, allowing you to monitor and interact with your car directly within Home Assistant.

**Note:** This integration relies on the Smartcar service. Availability of specific features depends on your vehicle's make, model, year, your Smartcar account plan (especially signal/sensor availability and API rate limits), and the permissions granted during authentication.

<img src="images/device_page.png" alt="Example Device Page Screenshot" width="600"/>

_Example showing entities for a Volkswagen ID.4_

## Prerequisites

1.  **Compatible Vehicle:** Your car must be [compatible with Smartcar](https://smartcar.com/product/compatible-vehicles) and the API must also be [supported in your country](https://smartcar.com/global).
2.  **Smartcar Developer Account:** You need a free developer account from Smartcar.
    - Go to [developer.smartcar.com](https://developer.smartcar.com/) and sign up.
    - Log in to your Developer Dashboard.
3.  **Ensure a Smartcar Application exists:**
    - In the dashboard, go to "Applications" and ensure an application was automatically created for you.
    - Rename your application if you want to (e.g., "Home Assistant Connect").

## Installation

### HACS

Installation through [HACS][hacs] is the preferred installation method.

[![Open the Smartcar integration in HACS][hacs-badge]][hacs-open]

1. Click the button above or go to HACS &rarr; Integrations &rarr; search for
   "Smartcar" &rarr; select it.
1. Press _DOWNLOAD_.
1. Select the version (it will auto select the latest) &rarr; press _DOWNLOAD_.
1. Restart Home Assistant then continue to [the setup section](#setup).

### Manual Download

1. Go to the [release page][releases] and download the `smartcar.zip` attached
   to the latest release.
1. Unpack the zip file and move `custom_components/smartcar` to the following
   directory of your Home Assistant configuration: `/config/custom_components/`.
1. Restart Home Assistant then continue to [the setup section](#setup).

## Setup

Configuration is done via the Home Assistant UI after installation.

1. Navigate to "Settings" &rarr; "Devices & Services"
1. Click "+ Add Integration"
1. Search for and select &rarr; "Smartcar"

Or you can use the My Home Assistant Button below.

[![Add Integration](https://my.home-assistant.io/badges/config_flow_start.svg)][config-flow-start]

Follow the instructions to configure the integration.

### Configuration Flow

Initially, you will have the option to enable [webhooks](#webhooks). If desired, follow the instructions to enter the required data. Once the configuration is complete, you can complete the required [webhook setup steps](#webhooks).

#### Authorization Data Entry

1. Choose a name for your credentials and enter the **Client ID** and **Client Secret** which can be found in the [Smartcar dashboard][smartcar-dashboard] under _Configuration_ &rarr; _API credentials_.
1. **Crucially, set the "Redirect URIs"** in the Smartcar settings for your application. You need to add **exactly** the URI your Home Assistant instance uses for OAuth callbacks.
   - Most users will simply use the **My Home Assistant** URI: `https://my.home-assistant.io/redirect/oauth`
     > Note: This is not a placeholder. It is the URI that must be used unless you’ve disabled or removed the `default_config:` line from your configuration and disabled the [My Home Assistant Integration](https://www.home-assistant.io/integrations/my/).
   - Add **only** the correct URI for your setup.
1. Continue to the next step.
1. Enter your _Application ID_ which can be found in the [Smartcar dashboard][smartcar-dashboard] under _Configuration_ &rarr; _Application details_.
1. If you plan to use webhooks, also enter your _Application management token_ which can be found in the [Smartcar dashboard][smartcar-dashboard] under _Configuration_ &rarr; _API credentials_.
1. Select the **Permissions** you want Home Assistant to be able to access. To enable all entities in this integration, select all relevant permissions:
   - Get total distance traveled
   - Get the vehicle's location
   - Get EV/PHEV battery level, capacity & current range
   - Get details on whether the car is plugged in and charging
   - Get details on whether doors, windows & more are enabled
   - Get engine oil health
   - Get tire pressure details
   - Get fuel tank level
   - Control charging (start/stop & target charge)
   - Lock or unlock vehicle

   \* _Functionality for all permissions depends on car support_

1. Continue to the [next section](#authorization-via-smartcar-connect) which explains the steps to authorize your vehicle via [Smartcar connect](https://smartcar.com/docs/connect/what-is-connect).

#### Authorization via Smartcar Connect

1. You will be redirected to the Smartcar website (or a new tab will open).
1. Log in using the credentials for your **vehicle's connected services account** (e.g., your Volkswagen ID, FordPass account, Tesla account), **NOT** your Smartcar developer account credentials.
1. Review the permissions requested by Home Assistant (these should match the scopes you selected when creating the Smartcar application).
1. **Grant access** to allow Home Assistant to connect to your vehicle(s) via Smartcar.
1. You should be redirected back to Home Assistant.

#### Setup Complete

If successful, the integration will be added, and Home Assistant will create devices and entities for your connected vehicle(s). From here:

- Enable entities you want to access after understanding [the impact on rate limits](#rate-limits--polling) if you're using polling.
- Consider creating a [customized polling setup](#customized-polling) via automations.

### Webhooks

**Important:** In order for webhooks to update entities, your Home Assistant instance must be accessible from the internet, either via Home Assistant Cloud or another method, and you must provide a valid Home Assistant URL in your [network settings](https://my.home-assistant.io/redirect/network/). See the [Remote Access documentation][ha-remote-access] for more information.

**Signal & Sensor Availability:** Please remember that sensor availability is based on which [signals](https://smartcar.com/docs/api-reference/signals/schema) are available, some of which are only available for **[paying Smartcar customers](https://smartcar.com/pricing#pricing)**.

These steps are for setting up a webhook in [Smartcar's dashboard][smartcar-dashboard]. Before starting, make sure you have completed all of the steps to [create an active configuration](#configuration-flow) in Home Assistant and have the webhook URL.

The webhooks configuration is broken down into several steps:

1. [Create Webhook](#create-webhook)
1. [Subscribe Vehicle](#subscribe-vehicle)
1. [Validate Webhook](#validate-webhook)

#### Create Webhook

1. From the [Smartcar dashboard][smartcar-dashboard], go to _Integrations_ & click on _Create integration_
1. Select _Webhook_
1. Choose which triggers to enable, i.e. use _Only show signals included in my plan_ then expand all signals and enable all of them
1. Click _Next_
1. Choose what data to include, i.e. use _Only show signals included in my plan_ then expand all signals and enable all of them
1. Click _Next_
1. Name the webhook, i.e. _Home Assistant_
1. Enter the callback URI (which is the URL that is displayed during setup)
1. Choose a setting for _Vehicle subscription_ that works for your plan (i.e. with the free plan, you'll want to add a vehicle in a later step)
1. Click _Next_
1. Review your settings and press _Next_
1. Press _Add webhook only_ (because verification will fail without a vehicle subscription)

#### Subscribe Vehicle

1. From the [Smartcar dashboard][smartcar-dashboard], go to _Vehicles_
1. Navigate to your vehicle
1. Choose _Webhooks_ at the top of the page
1. Press _Subscribe to webhook_
1. Select your webhook and press _Subscribe_

#### Validate Webhook

1. From the [Smartcar dashboard][smartcar-dashboard], go to _Integrations_
1. Navigate to your webhook by clicking on the name of it in the list view
1. In the ellipsis menu in the top right choose _Verify_
1. Press _Verify this webhook_
1. Ensure a popup appears indicating that the webhook was successfully verified

## FAQ's and Troubleshooting

See the [FAQ](FAQ.md) for more help with various topics.

## Entities

Several entities are created for for each connected vehicle (subject to vehicle compatibility and granted permissions) across the _device tracker_, _sensor_, _binary sensor_, _number_, _switch_, and _lock_ platforms:

- [`device_tracker.<make_model>_location`](#device_trackermake_model_location)
- [`sensor.<make_model>_battery_capacity`](#sensormake_model_battery_capacity)
- [`sensor.<make_model>_battery`](#sensormake_model_battery)
- [`sensor.<make_model>_charge_rate`](#numbermake_model_charge_rate)
- [`sensor.<make_model>_energy_added`](#numbermake_model_energy_added)
- [`sensor.<make_model>_time_to_complete`](#numbermake_model_time_to_complete)
- [`sensor.<make_model>_low_voltage_battery`](#sensormake_model_low_voltage_battery)
- [`sensor.<make_model>_charging_status`](#sensormake_model_charging_status)
- [`sensor.<make_model>_engine_oil_life`](#sensormake_model_engine_oil_life)
- [`sensor.<make_model>_fuel`](#sensormake_model_fuel)
- [`sensor.<make_model>_fuel_percent`](#sensormake_model_fuel_percent)
- [`sensor.<make_model>_fuel_range`](#sensormake_model_fuel_range)
- [`sensor.<make_model>_odometer`](#sensormake_model_odometer)
- [`sensor.<make_model>_range`](#sensormake_model_range)
- [`sensor.<make_model>_gear_state`](#sensormake_model_gear_state)
- [`sensor.<make_model>_tire_pressure_back_left`](#sensormake_model_tire_pressure_back_left)
- [`sensor.<make_model>_tire_pressure_back_right`](#sensormake_model_tire_pressure_back_right)
- [`sensor.<make_model>_tire_pressure_front_left`](#sensormake_model_tire_pressure_front_left)
- [`sensor.<make_model>_tire_pressure_front_right`](#sensormake_model_tire_pressure_front_right)
- [`sensor.<make_model>_charging_voltage`](#sensormake_model_charging_voltage)
- [`sensor.<make_model>_charging_current`](#sensormake_model_charging_current)
- [`sensor.<make_model>_charging_power`](#sensormake_model_charging_power)
- [`sensor.<make_model>_charging_time_remaining`](#sensormake_model_charging_time_remaining)
- [`sensor.<make_model>_charging_current_max`](#sensormake_model_charging_current_max)
- [`sensor.<make_model>_firmware_version`](#sensormake_model_firmware_version)
- [`binary_sensor.<make_model>_charging_cable_plugged_in`](#binary_sensormake_model_charging_cable_plugged_in)
- [`binary_sensor.<make_model>_battery_heater_active`](#binary_sensormake_model_battery_heater_active)
- [`binary_sensor.<make_model>_front_trunk`](#binary_sensormake_model_front_trunk)
- [`binary_sensor.<make_model>_front_trunk_lock`](#binary_sensormake_model_front_trunk_lock)
- [`binary_sensor.<make_model>_rear_trunk`](#binary_sensormake_model_rear_trunk)
- [`binary_sensor.<make_model>_rear_trunk_lock`](#binary_sensormake_model_rear_trunk_lock)
- [`binary_sensor.<make_model>_sunroof`](#binary_sensormake_model_sunroof)
- [`binary_sensor.<make_model>_engine_cover`](#binary_sensormake_model_engine_cover)
- [`binary_sensor.<make_model>_door_back_left`](#binary_sensormake_model_door_back_left)
- [`binary_sensor.<make_model>_door_back_left_lock`](#binary_sensormake_model_door_back_left_lock)
- [`binary_sensor.<make_model>_door_back_right`](#binary_sensormake_model_door_back_right)
- [`binary_sensor.<make_model>_door_back_right_lock`](#binary_sensormake_model_door_back_right_lock)
- [`binary_sensor.<make_model>_door_front_left`](#binary_sensormake_model_door_front_left)
- [`binary_sensor.<make_model>_door_front_left_lock`](#binary_sensormake_model_door_front_left_lock)
- [`binary_sensor.<make_model>_door_front_right`](#binary_sensormake_model_door_front_right)
- [`binary_sensor.<make_model>_door_front_right_lock`](#binary_sensormake_model_door_front_right_lock)
- [`binary_sensor.<make_model>_window_back_left`](#binary_sensormake_model_window_back_left)
- [`binary_sensor.<make_model>_window_back_right`](#binary_sensormake_model_window_back_right)
- [`binary_sensor.<make_model>_window_front_left`](#binary_sensormake_model_window_front_left)
- [`binary_sensor.<make_model>_window_front_right`](#binary_sensormake_model_window_front_right)
- [`binary_sensor.<make_model>_online`](#binary_sensormake_model_online)
- [`binary_sensor.<make_model>_asleep`](#binary_sensormake_model_asleep)
- [`binary_sensor.<make_model>_digital_key_paired`](#binary_sensormake_model_digital_key_paired)
- [`binary_sensor.<make_model>_surveillance_enabled`](#binary_sensormake_model_surveillance_enabled)
- [`binary_sensor.<make_model>_fast_charger_connected`](#binary_sensormake_model_fast_charger_connected)
- [`number.<make_model>_charge_limit`](#numbermake_model_charge_limit)
- [`switch.<make_model>_charging`](#switchmake_model_charging)
- [`lock.<make_model>_door_lock`](#lockmake_model_door_lock)

All entities have the following attributes:

- `age` The date at which the data was recorded by the vehicle\*; _corresponds to [`sc-data-age`](https://smartcar.com/docs/api-reference/headers#param-sc-data-age)_
- `fetched_at` The date at which Smartcar fetched the data\*; _corresponds to [`sc-data-fetched-at`](https://smartcar.com/docs/api-reference/headers#param-sc-fetched-at)_

\* _These will only be present when included in the API response._

Links to relevant API documentation are provided for each entity described below as well as the [permissions each entity requires](https://smartcar.com/docs/api-reference/permissions). When the required permissions are [not requested during setup](#authorization-data-entry), those entities will not be created.

In addition to the above, there is a sensor to aid in setting up the integration:

- [`sensor.<make_model>_last_webhook_received`](#sensormake_model_last_webhook_received)

### `device_tracker.<make_model>_location`

The GPS [location](https://smartcar.com/docs/api-reference/get-location) of the vehicle.

Enabled by default: :white_check_mark:  
Requires permissions: `read_location`

### `sensor.<make_model>_battery_capacity`

The [battery capacity](https://smartcar.com/docs/api-reference/get-nominal-capacity) of this vehicle in kWh.

Enabled by default: :x:  
Requires permissions: `read_battery`

### `sensor.<make_model>_battery`

The [state of charge](https://smartcar.com/docs/api-reference/evs/get-battery-level#param-percent-remaining) of the vehicle as a percentage.

Enabled by default: :white_check_mark:  
Requires permissions: `read_battery`  
Obtained concurrently with: [`sensor.<make_model>_range`](#sensormake_model_range)

### `sensor.<make_model>_charge_rate`

The [charge rate](https://smartcar.com/docs/api-reference/signals/charge#charge-rate) of the vehicle.

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `sensor.<make_model>_energy_added`

The [amount of energy added](https://smartcar.com/docs/api-reference/signals/charge#energy-added) in the current or most recent charging session.

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `sensor.<make_model>_time_to_complete`

The [estimated time remaining](https://smartcar.com/docs/api-reference/signals/charge#time-to-complete) until charging is complete.

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `sensor.<make_model>_low_voltage_battery`

The [state of charge of the low voltage battery](https://smartcar.com/docs/api-reference/signals/lowvoltagebattery#state-of-charge).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_door_front_right`

### `sensor.<make_model>_charging_status`

The [charging status](https://smartcar.com/docs/api-reference/evs/get-charge-status) of the vehicle.

Possible values:

- `​CHARGING`
- `FULLY_CHARGED`
- `NOT_CHARGING`

Enabled by default: :white_check_mark:  
Requires permissions: `read_charge`  
Obtained concurrently with: [`binary_sensor.<make_model>_charging_cable_plugged_in`](#binary_sensormake_model_charging_cable_plugged_in), [`switch.<make_model>_charging`](#switchmake_model_charging)

### `sensor.<make_model>_engine_oil_life`

The [estimated engine oil life](https://smartcar.com/docs/api-reference/get-engine-oil-life) remaining for the vehicle.

Enabled by default: :x:  
Requires permissions: `read_engine_oil`

### `sensor.<make_model>_fuel`

The [volume of fuel](https://smartcar.com/docs/api-reference/get-fuel-tank) remaining for the vehicle.

**Note:** This value is frequently `null` for many vehicles. Consider using [`sensor.<make_model>_fuel_percent`](#sensormake_model_fuel_percent) or [`sensor.<make_model>_fuel_range`](#sensormake_model_fuel_range) for more reliable fuel information.

Enabled by default: :x:  
Requires permissions: `read_fuel`  
Obtained concurrently with: [`sensor.<make_model>_fuel_percent`](#sensormake_model_fuel_percent), [`sensor.<make_model>_fuel_range`](#sensormake_model_fuel_range)

### `sensor.<make_model>_fuel_percent`

The [fuel level as a percentage](https://smartcar.com/docs/api-reference/get-fuel-tank#param-percent-remaining) remaining for the vehicle (0-100%).

This sensor provides more reliable fuel information than the amount-based sensor, as percentage values are more consistently available from vehicle APIs.

Enabled by default: :x:  
Requires permissions: `read_fuel`  
Obtained concurrently with: [`sensor.<make_model>_fuel`](#sensormake_model_fuel), [`sensor.<make_model>_fuel_range`](#sensormake_model_fuel_range)

### `sensor.<make_model>_fuel_range`

The [estimated driving range](https://smartcar.com/docs/api-reference/get-fuel-tank#param-range) remaining for the vehicle based on current fuel level.

Enabled by default: :x:  
Requires permissions: `read_fuel`  
Obtained concurrently with: [`sensor.<make_model>_fuel`](#sensormake_model_fuel), [`sensor.<make_model>_fuel_percent`](#sensormake_model_fuel_percent)

### `sensor.<make_model>_odometer`

The [odometer reading](https://smartcar.com/docs/api-reference/get-odometer) of the vehicle.

Enabled by default: :x:  
Requires permissions: `read_odometer`

### `sensor.<make_model>_range`

The [estimated range remaining](https://smartcar.com/docs/api-reference/evs/get-battery-level#param-range) for the vehicle.

Enabled by default: :white_check_mark:  
Requires permissions: `read_battery`  
Obtained concurrently with: [`sensor.<make_model>_battery`](#sensormake_model_battery)

### `sensor.<make_model>_gear_state`

The [gear state](https://smartcar.com/docs/api-reference/signals/transmission#gear-state) for the vehicle.

Possible values:

- `PARK`
- `DRIVE`
- `REVERSE`
- `NEUTRAL`

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `sensor.<make_model>_tire_pressure_back_left`

The [back left tire pressure](https://smartcar.com/docs/api-reference/get-tire-pressure#param-back-left) of the vehicle.

Enabled by default: :x:  
Requires permissions: `read_tires`  
Obtained concurrently with: [`sensor.<make_model>_tire_pressure_back_right`](#sensormake_model_tire_pressure_back_right), [`sensor.<make_model>_tire_pressure_front_left`](#sensormake_model_tire_pressure_front_left), [`sensor.<make_model>_tire_pressure_front_right`](#sensormake_model_tire_pressure_front_right)

### `sensor.<make_model>_tire_pressure_back_right`

The [back right tire pressure](https://smartcar.com/docs/api-reference/get-tire-pressure#param-back-right) of the vehicle.

Enabled by default: :x:  
Requires permissions: `read_tires`  
Obtained concurrently with: [`sensor.<make_model>_tire_pressure_back_left`](#sensormake_model_tire_pressure_back_left), [`sensor.<make_model>_tire_pressure_front_left`](#sensormake_model_tire_pressure_front_left), [`sensor.<make_model>_tire_pressure_front_right`](#sensormake_model_tire_pressure_front_right)

### `sensor.<make_model>_tire_pressure_front_left`

The [front left tire pressure](https://smartcar.com/docs/api-reference/get-tire-pressure#param-front-left) of the vehicle.

Enabled by default: :x:  
Requires permissions: `read_tires`  
Obtained concurrently with: [`sensor.<make_model>_tire_pressure_back_left`](#sensormake_model_tire_pressure_back_left), [`sensor.<make_model>_tire_pressure_back_right`](#sensormake_model_tire_pressure_back_right), [`sensor.<make_model>_tire_pressure_front_right`](#sensormake_model_tire_pressure_front_right)

### `sensor.<make_model>_tire_pressure_front_right`

The [front right tire pressure](https://smartcar.com/docs/api-reference/get-tire-pressure#param-front-right) of the vehicle.

Enabled by default: :x:
Requires permissions: `read_tires`
Obtained concurrently with: [`sensor.<make_model>_tire_pressure_back_left`](#sensormake_model_tire_pressure_back_left), [`sensor.<make_model>_tire_pressure_back_right`](#sensormake_model_tire_pressure_back_right), [`sensor.<make_model>_tire_pressure_front_left`](#sensormake_model_tire_pressure_front_left)

### `sensor.<make_model>_charging_voltage`

The [current voltage](https://smartcar.com/docs/api-reference/signals/charge#voltage) supplied during charging in volts.

Enabled by default: :x:
Webhooks only: :link: _currently only available via webhooks_

### `sensor.<make_model>_charging_current`

The [current amperage](https://smartcar.com/docs/api-reference/signals/charge#amperage) flowing to the vehicle during charging in amps.

Enabled by default: :x:
Webhooks only: :link: _currently only available via webhooks_

### `sensor.<make_model>_charging_power`

The [current power delivery rate](https://smartcar.com/docs/api-reference/signals/charge#wattage) during charging in kilowatts.

Enabled by default: :x:
Webhooks only: :link: _currently only available via webhooks_

### `sensor.<make_model>_charging_time_remaining`

The [estimated time remaining](https://smartcar.com/docs/api-reference/signals/charge#time-to-complete) until the vehicle reaches its charge limit in minutes.

Enabled by default: :x:
Webhooks only: :link: _currently only available via webhooks_

### `sensor.<make_model>_charging_current_max`

The [maximum available amperage](https://smartcar.com/docs/api-reference/signals/charge#amperage-max) for charging the vehicle in amps.

Enabled by default: :x:
Webhooks only: :link: _currently only available via webhooks_

### `sensor.<make_model>_firmware_version`

The [current firmware version](https://smartcar.com/docs/api-reference/signals/connectivitysoftware#current-firmware-version) installed on the vehicle.

Enabled by default: :x:
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_charging_cable_plugged_in`

Whether the vehicle [is currently plugged in](https://smartcar.com/docs/api-reference/evs/get-charge-status#param-is-plugged-in).

Enabled by default: :white_check_mark:  
Deprecated: This is deprecated and will be removed when the v2 API is no longer being used  
Requires permissions: `read_charge`  
Obtained concurrently with: [`sensor.<make_model>_charging_status`](#sensormake_model_charging_status), [`switch.<make_model>_charging`](#switchmake_model_charging)

### `binary_sensor.<make_model>_battery_heater_active`

Whether the vehicle is [battery heater is active](https://smartcar.com/docs/api-reference/signals/tractionbattery#is-heater-active).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_front_trunk`

Whether the [front trunk is open](https://smartcar.com/docs/api-reference/signals/closure#front-trunk).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_front_trunk_lock`

Whether the [front trunk is locked](https://smartcar.com/docs/api-reference/signals/closure#front-trunk).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_rear_trunk`

Whether the [rear trunk is open](https://smartcar.com/docs/api-reference/signals/closure#rear-trunk).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_rear_trunk_lock`

Whether the [rear trunk is locked](https://smartcar.com/docs/api-reference/signals/closure#rear-trunk).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_sunroof`

Whether the [sunroof is open](https://smartcar.com/docs/api-reference/signals/closure#sunroof).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_engine_cover`

Whether the [engine cover is open](https://smartcar.com/docs/api-reference/signals/closure#engine-cover).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_door_back_left`

Whether the [back left door is open](https://smartcar.com/docs/api-reference/signals/closure#doors).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_door_back_left_lock`

Whether the [back left door is locked](https://smartcar.com/docs/api-reference/signals/closure#doors).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_door_back_right`

Whether the [back right door is open](https://smartcar.com/docs/api-reference/signals/closure#doors).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_door_back_right_lock`

Whether the [back right door is locked](https://smartcar.com/docs/api-reference/signals/closure#doors).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_door_front_left`

Whether the [front left door is open](https://smartcar.com/docs/api-reference/signals/closure#doors).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_door_front_left_lock`

Whether the [front left door is locked](https://smartcar.com/docs/api-reference/signals/closure#doors).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_door_front_right`

Whether the [front right door is open](https://smartcar.com/docs/api-reference/signals/closure#doors).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_door_front_right_lock`

Whether the [front right door is locked](https://smartcar.com/docs/api-reference/signals/closure#doors).

### `binary_sensor.<make_model>_window_back_left`

Whether the [back left window is open](https://smartcar.com/docs/api-reference/signals/closure#windows).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_window_back_right`

Whether the [back right window is open](https://smartcar.com/docs/api-reference/signals/closure#windows).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_window_front_left`

Whether the [front left window is open](https://smartcar.com/docs/api-reference/signals/closure#windows).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_window_front_right`

Whether the [front right window is open](https://smartcar.com/docs/api-reference/signals/closure#windows).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_online`

Whether the vehicle is [online](https://smartcar.com/docs/api-reference/signals/connectivitystatus#is-online).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_asleep`

Whether the vehicle is [asleep](https://smartcar.com/docs/api-reference/signals/connectivitystatus#is-asleep).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_digital_key_paired`

Whether the vehicle is [has a digital key that has been successfully paired](https://smartcar.com/docs/api-reference/signals/connectivitystatus#is-digital-key-paired).

Enabled by default: :x:  
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_surveillance_enabled`

Whether the vehicle's [surveillance system is enabled](https://smartcar.com/docs/api-reference/signals/surveillance#is-enabled).

Enabled by default: :x:
Webhooks only: :link: _currently only available via webhooks_

### `binary_sensor.<make_model>_fast_charger_connected`

Whether a [DC fast charger is connected](https://smartcar.com/docs/api-reference/signals/charge#is-fast-charger-present) to the vehicle.

Enabled by default: :x:
Webhooks only: :link: _currently only available via webhooks_

### `number.<make_model>_charge_limit`

Change the [charge limit](https://smartcar.com/docs/api-reference/evs/get-charge-limit) by [setting it to a specific value](https://smartcar.com/docs/api-reference/evs/set-charge-limit).

Enabled by default: :x:  
Requires permissions: `read_charge`, `control_charge`

### `switch.<make_model>_charging`

Change whether the vehicle is [currently charging](https://smartcar.com/docs/api-reference/evs/get-charge-status#param-state) by [starting or stopping charging](https://smartcar.com/docs/api-reference/evs/control-charge).

Enabled by default: :white_check_mark:  
Requires permissions: `read_charge`, `control_charge`  
Obtained concurrently with: [`sensor.<make_model>_charging_status`](#sensormake_model_charging_status), [`binary_sensor.<make_model>_charging_cable_plugged_in`](#binary_sensormake_model_charging_cable_plugged_in)

### `lock.<make_model>_door_lock`

Change whether the vehicle is [currently locked](https://smartcar.com/docs/api-reference/get-lock-status) by [locking or unlocking](https://smartcar.com/docs/api-reference/control-lock-unlock).

Enabled by default: :white_check_mark:  
Requires permissions: `read_security`, `control_security`

_Note: some models, e.g., VW ID.4 2023+ do not have this functionality._

### `sensor.<make_model>_last_webhook_received`

The time the last webhook was received. This is set even when a received webhook is not valid (i.e. an unauthenticated request or for an unknown vehicle).

Enabled by default: :white_check_mark:

#### Attributes

- `response_status`: The status code used to respond to the webhook.
- `response_data`: The data sent in the response (when available).

## Actions

Smartcar provides the following actions:

- [`smartcar.lock_doors`](#smartcarlock_doors)
- [`smartcar.unlock_doors`](#smartcarunlock_doors)

### `smartcar.lock_doors`

Lock the doors of a vehicle. In most cases, the `lock.lock` action should be used on [`lock.<make_model>_door_lock`](#lockmake_model_door_lock) instead of using this action. It is only is provided for the case that the [`lock.<make_model>_door_lock`](#lockmake_model_door_lock) entity is not available due to unique permissions available for a vehicle in Smartcar. This occurs for a small subset of vehicles when Smartcar will only grant the `control_security` permission, but not the `read_security` permission.

#### Service Data Attributes

- `config_entry`: **required** Config entry to use. Example: `1b4a46c6cba0677bbfb5a8c53e8618b0`.
- `vin`: The VIN of the vehicle to target. If not provided, the first VIN for the config entry will be assumed.

### `smartcar.unlock_doors`

Lock the doors of a vehicle. In most cases, the `lock.unlock` action should be used on [`lock.<make_model>_door_lock`](#lockmake_model_door_lock) instead of using this action. It is only is provided for the case that the [`lock.<make_model>_door_lock`](#lockmake_model_door_lock) entity is not available due to unique permissions available for a vehicle in Smartcar. This occurs for a small subset of vehicles when Smartcar will only grant the `control_security` permission, but not the `read_security` permission.

#### Service Data Attributes

- `config_entry`: **required** Config entry to use. Example: `1b4a46c6cba0677bbfb5a8c53e8618b0`.
- `vin`: The VIN of the vehicle to target. If not provided, the first VIN for the config entry will be assumed.

## Rate Limits & Polling

- Consider setting up [webhooks](#webhooks). With webhooks enabled, polling will no longer occur avoiding most rate limit issues. Additionally, Smartcar is moving away from [their v2 API](https://smartcar.com/docs/api-reference/v2-overview) and polling may not be the best way to use the service.
- Smartcar's free developer tier typically has a limit of **500 API calls per vehicle per month**. Exceeding this may incur costs or stop the integration from working.
- By default, it uses **6 hour polling interval** and only fetches data required for enabled entities.
- Polling can be [customized as well](#customized-polling).

### Customized Polling

To customize polling, you can disable polling on the integration and write your own automation.

- First, configure the integration as described above.
- Go to _Settings_ &rarr; _Integartions_ (under _Devices & services_) &rarr; _Smartcar_
- Click the three dots to the right of the integration.
- Choose _System options_.
- Disable _Enable polling for changes_ and then click _Save_.
- Create an automation using [`homeassistant.update_entity`](https://www.home-assistant.io/integrations/homeassistant/#action-homeassistantupdate_entity) to refresh the desired value(s).

Examples are provided:

- [`examples/poll-smartcar-simple.yaml`](examples/poll-smartcar-simple.yaml)
- [`examples/poll-smartcar-custom.yaml`](examples/poll-smartcar-custom.yaml)
- [`examples/poll-smartcar-excessive.yaml`](examples/poll-smartcar-excessive.yaml)

When updating an entity via `homeassistant.update_entity`:

- A request to update an entity will also update related entities (see the _Obtained concurrently with_ notes on each entity above).
- Requests to update several entities at once will be [batched](https://smartcar.com/docs/api-reference/batch), reducing excessive network requests and potentially limiting the number of API calls counted against your account.

For instance:

- `homeassistant.update_entity` on [`sensor.<make_model>_battery`](#sensormake_model_battery) and [`sensor.<make_model>_range`](#sensormake_model_range) will make a single batch request that counts as **one** API call because the entities are related.
- `homeassistant.update_entity` on [`sensor.<make_model>_battery`](#sensormake_model_battery) and [`sensor.<make_model>_odometer`](#sensormake_model_odometer) will make a single batch request that counts as **two** API calls since they are unrelated.

## Upgrading from Legacy `v2` API to `v3`

For now, you can continue to use the `v2` API as long as it is supported by Smartcar, but [Smartcar documents the deprecation thusly](https://smartcar.com/docs/getting-started/how-to/m2m/migration-guide#overview):

> The Vehicles API v2.0 will be deprecated by Q4 of 2026. We recommend migrating to the latest version as soon as possible to ensure continued support and access to new features.

To upgrade from `v2` to `v3`, you need to use the _API credentials_ rather than the _Legacy credentials_. In Home Assistant, you will need to:

- Remove all Smartcar integrations that use v2. _Note: this is required in order to remove credentials in the next step_.  
  Before removing the items, you may want to note any customizations to entities such as entity IDs or areas in which entities are located so that you can re-create them once the migration is complete.
- Remove all [_Application Credentials_][ha-application-credentials] that use a v2 `client_id`. To be safe, you can remove all Smartcar credentials from the _Application Credentials_.
- Re-setup each smart car integration, ensuring that you use the new v3 _API credentials_ and _Application ID_ rather than _Legacy Credentials_.

## Known Issues / Limitations

- **Vehicle Compatibility:** Not all features are supported by all vehicle makes/models/years via the Smartcar API. Entities for unsupported features (e.g., [fuel status](#sensormake_model_fuel) for EVs or [lock control](#lockmake_model_door_lock) for VW ID.4 2023+) may or may still be created, but not function. Check the Smartcar compatibility details for your specific vehicle.
- **Fuel Data Availability:** The [`sensor.<make_model>_fuel`](#sensormake_model_fuel) (amount in litres) is frequently `null` for many vehicles. However, [`sensor.<make_model>_fuel_percent`](#sensormake_model_fuel_percent) and [`sensor.<make_model>_fuel_range`](#sensormake_model_fuel_range) are typically more reliable and provide comprehensive fuel monitoring even when the amount is unavailable.
- **API Latency:** There can be significant delays (seconds to minutes) between sending a command (e.g., start charging) and the vehicle executing/reporting the change back through the API. The state in Home Assistant will update after the next successful data poll.
- **Rate Limits:** Be mindful of the 500 calls/vehicle/month limit on the free tier.
- **Single User:** Smartcar applications must be configured with only a single user connected to vehicles.
- **FAQ:** In case ou haven't found the [FAQ](FAQ.md) yet, it is a great resource for troubleshooting and discovering if you're running up against an issue with this integration vs. a limitation in Smartcar's platform.

## Support / Issues

Please report any issues you find with this integration by opening an issue on the [GitHub Issues page](https://github.com/wbyoung/smartcar/issues).

[hacs]: https://hacs.xyz/
[hacs-repo]: https://github.com/hacs/integration
[hacs-badge]: https://my.home-assistant.io/badges/hacs_repository.svg
[hacs-open]: https://my.home-assistant.io/redirect/hacs_repository/?owner=wbyoung&repository=smartcar&category=integration
[releases]: https://github.com/wbyoung/smartcar/releases
[config-flow-start]: https://my.home-assistant.io/redirect/config_flow_start/?domain=smartcar
[smartcar-dashboard]: https://dashboard.smartcar.com/team/applications
[ha-remote-access]: https://www.home-assistant.io/docs/configuration/remote/
[ha-application-credentials]: https://www.home-assistant.io/integrations/application_credentials/
[gh-sponsors]: https://github.com/sponsors/wbyoung
