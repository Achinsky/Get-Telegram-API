# Get Telegram API

Portable utility for automatic extraction of `api_id` and `api_hash` from [my.telegram.org](https://my.telegram.org).

Works fully locally via embedded Chromium — no data is sent anywhere.

## Usage

1. Download `Get Telegram API.exe` from [Releases](https://github.com/Achinsky/Get-Telegram-API/releases)
2. Run the EXE
3. Enter your phone number → click **Get Code**
4. Enter the code from Telegram → click **Confirm**
5. Your `api_id`, `api_hash`, servers and RSA keys appear in the **My Data** tab

## Features

- Dark UI with sidebar navigation
- Tabs: Main, My Data, Settings, About
- Copy button on every data card with visual feedback
- Export credentials to `.json`, `.txt`, `.env`, `.csv`, `.md`
- Data masking option (hide sensitive values with ••••)
- Settings saved automatically to `settings.json`
- Headless browser mode
- Automatic Telegram app creation if none exists
- Portable single-file EXE with embedded Chromium

## Security

Everything works locally through Playwright and embedded Chromium.
Your credentials are never sent to any third-party server.

## Author

Telegram: [@zaurachinsky](https://t.me/zaurachinsky)
GitHub: [Achinsky](https://github.com/Achinsky)

## License

MIT
