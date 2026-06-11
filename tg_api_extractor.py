import json
import random
import re
import threading
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


def get_base_path() -> str:
    """Return base path — works both for script and PyInstaller EXE."""
    return getattr(
        sys,
        "_MEIPASS",
        os.path.dirname(os.path.abspath(__file__))
    )


def find_chromium_executable() -> str | None:
    """
    Dynamically locate the bundled Chromium executable.
    Searches for any chromium-* folder under ms-playwright so the
    path does not need to be updated when Playwright bumps its version.
    """
    base = get_base_path()
    playwright_dir = Path(base) / "ms-playwright"

    if not playwright_dir.exists():
        return None

    # Walk chromium-* directories sorted descending — pick the newest
    for chromium_dir in sorted(playwright_dir.glob("chromium-*"), reverse=True):
        candidates = [
            chromium_dir / "chrome-win64" / "chrome.exe",   # Windows
            chromium_dir / "chrome-mac"  / "Chromium.app" / "Contents" / "MacOS" / "Chromium",  # macOS
            chromium_dir / "chrome-linux" / "chrome",        # Linux
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

    return None


# ---------------------------------------------------------------------------
# Business logic — no UI code here
# ---------------------------------------------------------------------------

class TelegramExtractor:
    """Handles all browser automation and data extraction logic."""

    def __init__(self, log_callback):
        self._log = log_callback
        self.playwright = None
        self.browser = None
        self.page = None

    # ------------------------------------------------------------------
    # Browser lifecycle
    # ------------------------------------------------------------------

    def start_browser(self):
        """Launch Playwright + Chromium. Closes any previous session first."""
        self.close_browser()

        self.playwright = sync_playwright().start()

        exe_path = find_chromium_executable()

        launch_kwargs = {"headless": False}
        if exe_path:
            self._log(f"[+] Chromium: {exe_path}")
            launch_kwargs["executable_path"] = exe_path
        else:
            # Fall back to the Playwright-managed browser
            self._log("[+] Bundled Chromium not found — using system Playwright install")

        self.browser = self.playwright.chromium.launch(**launch_kwargs)
        context = self.browser.new_context()
        self.page = context.new_page()

    def close_browser(self):
        """Safely close browser and stop Playwright."""
        try:
            if self.browser:
                self.browser.close()
                self.browser = None
        except Exception:
            pass

        try:
            if self.playwright:
                self.playwright.stop()
                self.playwright = None
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Telegram auth
    # ------------------------------------------------------------------

    def send_code(self, phone: str):
        """Navigate to my.telegram.org and request a login code."""
        self._log("[+] Loading browser...")
        self.start_browser()

        self._log("[+] Открываем my.telegram.org...")
        self.page.goto("https://my.telegram.org/auth")

        phone_input = self.page.get_by_role("textbox", name="Your Phone Number")
        phone_input.wait_for(timeout=30000)
        phone_input.fill(phone)

        self._click_submit()

        self._log("[+] Код отправлен в Telegram")
        self._log("[+] Введите код и нажмите 'Подтвердить код'")

    def confirm_code(self, code: str) -> dict:
        """Enter the confirmation code and extract API credentials."""
        code_input = self.page.get_by_placeholder("Confirmation code")
        code_input.wait_for(timeout=30000)
        code_input.fill(code)

        self._click_submit()
        self.page.wait_for_timeout(3000)

        self._log("[+] Авторизация успешна")
        return self._extract_credentials()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _click_submit(self):
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

    def _create_app(self):
        self._log("[+] Создаём приложение...")

        title_val = f"MyApp{random.randint(1000, 9999)}"
        short_name = f"app{random.randint(100000, 999999)}"

        self.page.locator("input").nth(0).fill(title_val)
        self.page.locator("input").nth(1).fill(short_name)

        textarea = self.page.locator("textarea")
        if textarea.count() > 0:
            textarea.first.fill("Personal Telegram API")

        try:
            self.page.locator('input[type="radio"]').nth(0).check()
        except Exception:
            pass

        self.page.get_by_text("Create application").click()
        self.page.wait_for_load_state("networkidle")

    def _extract_credentials(self) -> dict:
        self._log("[+] Переходим на страницу приложений...")
        self.page.goto("https://my.telegram.org/apps")
        self.page.wait_for_timeout(4000)

        text = self.page.locator("body").inner_text()

        if "Create new application" in text:
            self._create_app()
            self.page.goto("https://my.telegram.org/apps")
            self.page.wait_for_timeout(4000)
            text = self.page.locator("body").inner_text()

        api_id_match   = re.search(r"App api_id:\s*(\d+)", text)
        api_hash_match = re.search(r"App api_hash:\s*([a-fA-F0-9]{32})", text)

        if not api_id_match or not api_hash_match:
            raise RuntimeError("Не удалось найти api_id / api_hash на странице")

        data = {
            "api_id":   int(api_id_match.group(1)),
            "api_hash": api_hash_match.group(1),
        }

        OUTPUT_DIR.mkdir(exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        self._log("[+] Данные успешно получены")
        self._log(f"[+] Сохранено: {OUTPUT_FILE}")
        return data


# ---------------------------------------------------------------------------
# UI — no business logic here
# ---------------------------------------------------------------------------

class TelegramExtractorApp:
    """CustomTkinter GUI that delegates all work to TelegramExtractor."""

    def __init__(self):
        self.root = ctk.CTk()
        self.root.geometry("700x700")
        self.root.title("Get Telegram API")

        self._load_icon()

        self.extractor = TelegramExtractor(log_callback=self.log)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _load_icon(self):
        try:
            png_path = os.path.join(get_base_path(), "assets", "logo.png")
            icon_image = ImageTk.PhotoImage(Image.open(png_path))
            self.root.iconphoto(True, icon_image)
        except Exception as e:
            print(e)

    def _on_close(self):
        self.extractor.close_browser()
        self.root.destroy()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        ctk.CTkLabel(
            self.root,
            text="Telegram API Extractor",
            font=("Arial", 28, "bold"),
        ).pack(pady=20)

        ctk.CTkLabel(
            self.root,
            text="Получение api_id и api_hash локально",
            font=("Arial", 14),
        ).pack(pady=(0, 20))

        self.phone_entry = ctk.CTkEntry(
            self.root, width=400, height=40, placeholder_text="+79991234567"
        )
        self.phone_entry.pack(pady=10)

        self.start_button = ctk.CTkButton(
            self.root,
            text="Получить код",
            width=250,
            height=40,
            command=self._start_login,
        )
        self.start_button.pack(pady=10)

        self.code_entry = ctk.CTkEntry(
            self.root, width=400, height=40, placeholder_text="Код из Telegram"
        )
        self.code_entry.pack(pady=10)

        self.code_button = ctk.CTkButton(
            self.root,
            text="Подтвердить код",
            width=250,
            height=40,
            command=self._submit_code,
        )
        self.code_button.pack(pady=10)

        self.log_box = ctk.CTkTextbox(self.root, width=600, height=180)
        self.log_box.pack(pady=20)

        self.result_box = ctk.CTkTextbox(self.root, width=600, height=200)
        self.result_box.pack(pady=10)

        ctk.CTkButton(
            self.root,
            text="Скопировать результат",
            width=250,
            height=40,
            command=self._copy_result,
        ).pack(pady=15)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def log(self, text: str):
        self.log_box.insert("end", f"{text}\n")
        self.log_box.see("end")

    def _set_result(self, data: dict):
        result = f"API_ID: {data['api_id']}\nAPI_HASH: {data['api_hash']}\n"
        self.result_box.delete("1.0", "end")
        self.result_box.insert("end", result)

    def _copy_result(self):
        pyperclip.copy(self.result_box.get("1.0", "end"))
        self.log("[+] Результат скопирован")

    # ------------------------------------------------------------------
    # Button handlers — run work in background threads
    # ------------------------------------------------------------------

    def _start_login(self):
        phone = self.phone_entry.get().strip()
        if not phone.startswith("+"):
            self.log("[!] Номер должен начинаться с +")
            return

        self.start_button.configure(state="disabled")
        threading.Thread(target=self._login_worker, args=(phone,), daemon=True).start()

    def _login_worker(self, phone: str):
        try:
            self.extractor.send_code(phone)
        except Exception as e:
            self.log(f"[!] Ошибка: {e}")
        finally:
            self.root.after(0, lambda: self.start_button.configure(state="normal"))

    def _submit_code(self):
        code = self.code_entry.get().strip()
        if not code:
            self.log("[!] Введите код")
            return

        self.code_button.configure(state="disabled")
        threading.Thread(target=self._code_worker, args=(code,), daemon=True).start()

    def _code_worker(self, code: str):
        try:
            data = self.extractor.confirm_code(code)
            self.root.after(0, lambda: self._set_result(data))
        except Exception as e:
            self.log(f"[!] Ошибка подтверждения: {e}")
        finally:
            self.root.after(0, lambda: self.code_button.configure(state="normal"))

    # ------------------------------------------------------------------

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = TelegramExtractorApp()
    app.run()
