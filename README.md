# README.md

# HACS Romande Energie Integration

This repository contains the Romande Energie integration for Home Assistant, allowing users to interact with their Romande Energie accounts and retrieve electricity consumption data.

## Features

- Log in to the Romande Énergie customer portal (e-mail + password + SMS one-time code)
- Automatically keeps the session alive by refreshing tokens (no repeated SMS codes)
- Fetches daily electricity data from your smart meter
- Entities:
  - Daily consumption (kWh)
  - Monthly consumption total (kWh)
  - Daily surplus (kWh) — for solar producers
  - Monthly surplus total (kWh) — for solar producers
- Home Assistant Energy dashboard support via long-term statistics

## Installation

1. Install the [Home Assistant Community Store (HACS)](https://hacs.xyz/docs/installation/installation).
2. Add this repository to HACS:
   - Go to HACS in Home Assistant.
   - Click on "Integrations" and then "Explore & Download Repositories".
   - Search for "hacs-romande-energie" and install it.
3. Restart Home Assistant.

## Configuration

The Romande Énergie portal requires a two-step login: your credentials **and** an SMS
one-time code (OTP).

1. Go to `Settings` → `Devices & Services` in Home Assistant.
2. Click `Add Integration` and search for `Romande Energie`.
3. Enter your Romande Énergie **e-mail** and **password**.
4. An **SMS code** is sent to the mobile number registered on your account. Enter that
   6-digit code to finish setup.

After setup the integration keeps its session alive by refreshing tokens on its own, so
you normally will **not** be asked for another SMS code.

### Re-authentication

The portal session only survives short gaps. If Home Assistant is offline (or the network
is down) for longer than ~30 minutes, the session lapses and cannot be refreshed silently.
When that happens Home Assistant raises a **re-authentication** notification: open it and
enter a fresh SMS code to restore the connection. This is expected behaviour, not a bug.

## Usage

Once configured, the integration exposes daily and monthly consumption sensors — plus
daily and monthly surplus sensors if you are a solar producer. It also writes long-term
statistics, so you can add your consumption (and surplus) directly to the Home Assistant
**Energy dashboard**.

### Which day the daily sensors show

The portal syncs your meter roughly once a day, and the day it publishes last stays
incomplete until the following sync fills it in. The daily sensors therefore show the
most recent **fully synced** day rather than that partial one — typically the day before
yesterday. The exact date is on each sensor as the `measurement_day` attribute.

The Energy-dashboard statistics do include the day still syncing, and every poll rewrites
the last 30 days, so a partial value is corrected automatically once the portal completes
it. No action is needed on your side.

## Disclaimer

This integration is not developed, endorsed, or supported by Romande Energie SA. It's an independent project created by community members to integrate Romande Energie's services with Home Assistant. Romande Energie is not responsible for this integration's functionality, and any issues or questions should be directed to this project's GitHub repository, not to Romande Energie's customer service.

The names "Romande Energie" and related trademarks belong to Romande Energie SA and are used here for identification purposes only.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request for any enhancements or bug fixes.

## License

This project is licensed under the MIT License. See the LICENSE file for more details.