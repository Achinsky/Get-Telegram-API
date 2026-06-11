# Get Telegram API

A portable utility that automatically extracts `api_id` and `api_hash` from [my.telegram.org](https://my.telegram.org) — the credentials required to work with the Telegram API.

Everything runs locally on your machine. No data is sent anywhere.

---

## What are api_id and api_hash?

To use Telegram API libraries like [Telethon](https://github.com/LonamiWebs/Telethon) or [Pyrogram](https://github.com/pyrogram/pyrogram), you need a personal `api_id` and `api_hash`. These are issued by Telegram at [my.telegram.org](https://my.telegram.org/apps) and are tied to your account.

This tool automates the process of obtaining them — no manual browser interaction needed.

---

## Quick Start

1. Download `Get Telegram API.exe` from [Releases](https://github.com/Achinsky/Get-Telegram-API/releases)
2. Run the EXE
3. Enter your phone number → click **Get Code**
4. Enter the confirmation code from Telegram → click **Confirm**
5. Your credentials appear in the **My Data** tab — copy or export them

---

## Features

- **My Data tab** — displays `api_id`, `api_hash`, App title, Short name, MTProto servers and RSA public keys
- **Copy button** on every field with visual confirmation (✓ flash)
- **Export** to `.json`, `.txt`, `.env`, `.csv`, `.md`
- **Data masking** — hide sensitive values with •••• in the UI
- **Settings** — headless browser mode, autosave, data masking; persisted to `settings.json`
- **Automatic app creation** — if no Telegram app exists, one is created automatically
- Portable single-file EXE, no installation required

---

## Windows SmartScreen Warning

When running the EXE for the first time, Windows may show:

> *"Windows protected your PC — unrecognised app"*

This happens because the EXE is not digitally signed (code signing certificates cost ~$200/year and are impractical for an open-source project).

**To proceed:** click **More info** → **Run anyway**.

If you prefer not to trust unsigned binaries, you can run the script directly from source — see [Run from source](#run-from-source) below.

---

## Why is the EXE 240 MB?

The EXE bundles a full Chromium browser (~220 MB) alongside the Python runtime and dependencies. Chromium is needed to interact with my.telegram.org, which relies heavily on JavaScript and session-based authentication.

There is no lighter alternative that reliably handles Telegram's web interface without a real browser engine.

---

## Run from source

If you have Python 3.10+ installed:

```bash
git clone https://github.com/Achinsky/Get-Telegram-API.git
cd Get-Telegram-API
pip install -r requirements.txt
playwright install chromium
python tg_api_extractor.py
```

No SmartScreen warning. No 240 MB download. Chromium is fetched separately by Playwright (~150 MB, stored in `%LOCALAPPDATA%\ms-playwright`).

---

## Security

- The tool opens [my.telegram.org](https://my.telegram.org) in an embedded Chromium window — you can see every action it takes
- No background network requests are made outside of my.telegram.org
- Credentials are saved locally to `output/credentials.json`
- Source code is fully open and auditable

---

## Author

Telegram: [@zaurachinsky](https://t.me/zaurachinsky)
GitHub: [Achinsky](https://github.com/Achinsky)

---

## License

MIT
