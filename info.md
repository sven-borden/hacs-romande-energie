# Information about the Romande Energie Integration

## Overview
The Romande Energie integration allows users to connect their Home Assistant instance with the Romande Energie API. This integration provides access to electricity consumption data, contract information, and session management.

## Features
- **Secure login**: E-mail + password + SMS one-time code (OTP), then autonomous token refresh.
- **Daily & monthly consumption**: Electricity consumption sensors, in kWh.
- **Daily & monthly surplus**: Solar export sensors for producers, in kWh.
- **Energy dashboard**: Long-term statistics for use in the Home Assistant Energy dashboard.

## Installation
To install the Romande Énergie integration, add it through the Home Assistant Community Store (HACS) or manually place the `romande_energie` folder in your `custom_components` directory.

## Configuration
Add the integration from `Settings` → `Devices & Services`. Enter your Romande Énergie
e-mail and password, then the **SMS one-time code** sent to your registered mobile number.

After setup the session is kept alive automatically. If Home Assistant is offline for
longer than ~30 minutes the session may lapse; Home Assistant will then prompt you to
**re-authenticate** by entering a new SMS code.

## Usage
Once configured, the integration exposes daily and monthly consumption sensors (plus
daily and monthly surplus sensors for solar producers) and writes long-term statistics
so the data can be added to the Home Assistant Energy dashboard.

## Support
For support and issues, please refer to the project's GitHub repository or the Home Assistant community forums.