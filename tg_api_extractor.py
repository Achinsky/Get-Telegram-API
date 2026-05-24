import asyncio

asyncio.set_event_loop_policy(
    asyncio.WindowsProactorEventLoopPolicy()
)

import json
import random
import re
from pathlib import Path
import sys
import os
from PIL import Image, ImageTk
import customtkinter as ctk

import pyperclip
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "credentials.json"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


class TelegramExtractorApp:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.geometry("700x700")
        self.root.title("Get Telegram API")
        
        try:
            base_path = getattr(
                sys,
                '_MEIPASS',
                os.path.dirname(os.path.abspath(__file__))
            )

            png_path = os.path.join(base_path, "assets", "logo.png")

            icon_image = ImageTk.PhotoImage(Image.open(png_path))

            self.root.iconphoto(True, icon_image)

        except Exception as e:
            print(e)

        self.playwright = None
        self.browser = None
        self.page = None

        self.build_ui()

    def build_ui(self):
        title = ctk.CTkLabel(
            self.root,
            text="Telegram API Extractor",
            font=("Arial", 28, "bold")
        )
        title.pack(pady=20)

        subtitle = ctk.CTkLabel(
            self.root,
            text="Получение api_id и api_hash локально",
            font=("Arial", 14)
        )
        subtitle.pack(pady=(0, 20))

        self.phone_entry = ctk.CTkEntry(
            self.root,
            width=400,
            height=40,
            placeholder_text="+79991234567"
        )
        self.phone_entry.pack(pady=10)

        self.start_button = ctk.CTkButton(
            self.root,
            text="Получить код",
            width=250,
            height=40,
            command=self.start_login
        )
        self.start_button.pack(pady=10)

        self.code_entry = ctk.CTkEntry(
            self.root,
            width=400,
            height=40,
            placeholder_text="Код из Telegram"
        )
        self.code_entry.pack(pady=10)

        self.code_button = ctk.CTkButton(
            self.root,
            text="Подтвердить код",
            width=250,
            height=40,
            command=self.submit_code
        )
        self.code_button.pack(pady=10)

        self.log_box = ctk.CTkTextbox(
            self.root,
            width=600,
            height=180
        )
        self.log_box.pack(pady=20)

        self.result_box = ctk.CTkTextbox(
            self.root,
            width=600,
            height=200
        )
        self.result_box.pack(pady=10)

        self.copy_button = ctk.CTkButton(
            self.root,
            text="Скопировать результат",
            width=250,
            height=40,
            command=self.copy_result
        )
        self.copy_button.pack(pady=15)

    def log(self, text):
        self.log_box.insert("end", f"{text}\n")
        self.log_box.see("end")

    def save_credentials(self, data):
        OUTPUT_DIR.mkdir(exist_ok=True)

        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def click_submit(self):
        selectors = [
            'button:has-text("Next")',
            'button:has-text("Sign In")',
            'button.btn-primary',
            'input[type="submit"]',
        ]

        for selector in selectors:
            locator = self.page.locator(selector)

            if locator.count() > 0:
                try:
                    locator.first.click(timeout=5000)
                    return
                except Exception:
                    pass

    def start_login(self):
        self.login_thread()

    def login_thread(self):
        try:
            phone = self.phone_entry.get().strip()

            if not phone.startswith("+"):
                self.log("[!] Номер должен начинаться с +")
                return

            self.log("[+] Loading browser...")
            self.root.update()

            self.playwright = sync_playwright().start()
            base_path = getattr(
                sys,
                '_MEIPASS',
                os.path.dirname(os.path.abspath(__file__))
            )

            browser_path = os.path.join(
                base_path,
                "ms-playwright",
                "chromium-1223",
                "chrome-win64",
                "chrome.exe"
            )

            self.browser = self.playwright.chromium.launch(
                executable_path=browser_path,
                headless=False
            )

            context = self.browser.new_context()
            self.page = context.new_page()

            self.log("[+] Открываем my.telegram.org...")
            self.root.update()

            self.page.goto("https://my.telegram.org/auth")

            phone_input = self.page.get_by_role(
                "textbox",
                name="Your Phone Number"
            )

            phone_input.wait_for(timeout=30000)
            phone_input.fill(phone)

            self.click_submit()

            self.log("[+] Код отправлен в Telegram")
            self.root.update()
            self.log("[+] Введите код и нажмите 'Подтвердить код'")

        except Exception as e:
            self.log(f"[!] Ошибка: {e}")

    def submit_code(self):
        self.submit_code_thread()

    def submit_code_thread(self):
        try:
            code = self.code_entry.get().strip()

            code_input = self.page.get_by_placeholder(
                "Confirmation code"
            )

            code_input.wait_for(timeout=30000)
            code_input.fill(code)

            self.click_submit()

            self.page.wait_for_timeout(3000)

            self.log("[+] Авторизация успешна")

            self.extract_all()

        except Exception as e:
            self.log(f"[!] Ошибка подтверждения: {e}")

    def create_app(self):
        self.log("[+] Создаём приложение...")

        title = f"MyApp{random.randint(1000,9999)}"
        short_name = f"app{random.randint(100000,999999)}"

        title_input = self.page.locator("input").nth(0)
        title_input.fill(title)

        short_input = self.page.locator("input").nth(1)
        short_input.fill(short_name)

        textarea = self.page.locator("textarea")

        if textarea.count() > 0:
            textarea.first.fill("Personal Telegram API")

        try:
            self.page.locator('input[type="radio"]').nth(0).check()
        except Exception:
            pass

        self.page.get_by_text("Create application").click()

        self.page.wait_for_load_state("networkidle")

    def extract_all(self):
        self.log("[+] Переходим на страницу приложений...")

        self.page.goto("https://my.telegram.org/apps")

        self.page.wait_for_timeout(4000)

        text = self.page.locator("body").inner_text()

        if "Create new application" in text:
            self.create_app()
            self.page.goto("https://my.telegram.org/apps")
            self.page.wait_for_timeout(4000)
            text = self.page.locator("body").inner_text()

        api_id_match = re.search(r"App api_id:\s*(\d+)", text)
        api_hash_match = re.search(
            r"App api_hash:\s*([a-fA-F0-9]{32})",
            text
        )

        if not api_id_match or not api_hash_match:
            self.log("[!] Не удалось получить данные")
            return

        data = {
            "api_id": int(api_id_match.group(1)),
            "api_hash": api_hash_match.group(1)
        }

        self.save_credentials(data)

        result = (
            f"API_ID: {data['api_id']}\n"
            f"API_HASH: {data['api_hash']}\n"
        )

        self.result_box.delete("1.0", "end")
        self.result_box.insert("end", result)

        self.log("[+] Данные успешно получены")
        self.log(f"[+] Сохранено: {OUTPUT_FILE}")

    def copy_result(self):
        text = self.result_box.get("1.0", "end")
        pyperclip.copy(text)
        self.log("[+] Результат скопирован")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = TelegramExtractorApp()
    app.run()