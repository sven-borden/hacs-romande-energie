# README.md

# HACS Romande Energie Integration

This repository contains the Romande Energie integration for Home Assistant, allowing users to interact with their Romande Energie accounts and retrieve electricity consumption data.

## Features

- Log in to the Romande Energie API
- Retrieve session information
- Get contracts associated with the account
- Fetch electricity consumption data

## Installation

1. Install the [Home Assistant Community Store (HACS)](https://hacs.xyz/docs/installation/installation).
2. Add this repository to HACS:
   - Go to HACS in Home Assistant.
   - Click on "Integrations" and then "Explore & Download Repositories".
   - Search for "hacs-romande-energie" and install it.
3. Restart Home Assistant.

## Configuration

To configure the Romande Energie integration:

1. Go to `Configuration` in Home Assistant.
2. Click on `Integrations`.
3. Click on `Add Integration` and search for `Romande Energie`.
4. Enter your Romande Energie account credentials (username and password).

## Usage

Once configured, the integration will automatically retrieve and display your electricity consumption data in Home Assistant. You can create sensors to visualize this data on your dashboard.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request for any enhancements or bug fixes.

## License

This project is licensed under the MIT License. See the LICENSE file for more details.