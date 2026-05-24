# Get Telegram API

Утилита для автоматического получения Telegram `api_id` и `api_hash`.

## Возможности

- Автоматическая авторизация через my.telegram.org
- Получение api_id и api_hash

## Запуск

1. Качай:
   `Get Telegram API.exe`

2. Запусти файл

3. Введи номер телефона

4. Подтверди код из Telegram

5. Получи API данные

## Безопасность

- Все данные обрабатываются локально
- Никакие данные не отправляются на сервер
- Исходный код открыт

## Сборка

```bash
pip install -r requirements.txt
playwright install chromium

pyinstaller --onefile --noconsole --windowed ^
--icon=assets/TGAPIEXT.ico ^
--name "Get Telegram API" ^
--collect-all customtkinter ^
tg_api_extractor.py