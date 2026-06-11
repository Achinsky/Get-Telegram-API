import csv
import json
import queue
import random
import re
import threading
from pathlib import Path
import sys
import os
from PIL import Image, ImageTk
import customtkinter as ctk
from tkinter import messagebox

import pyperclip
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "credentials.json"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

ACCENT = "#3B82F6"
SIDEBAR_WIDTH = 180


def get_base_path() -> str:
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def find_chromium_executable() -> str | None:
    playwright_dir = Path(get_base_path()) / "ms-playwright"
    if not playwright_dir.exists():
        return None
    for chromium_dir in sorted(playwright_dir.glob("chromium-*"), reverse=True):
        for candidate in [
            chromium_dir / "chrome-win64" / "chrome.exe",
            chromium_dir / "chrome-mac" / "Chromium.app" / "Contents" / "MacOS" / "Chromium",
            chromium_dir / "chrome-linux" / "chrome",
        ]:
            if candidate.exists():
                return str(candidate)
    return None


# ---------------------------------------------------------------------------
# Business logic
# ---------------------------------------------------------------------------

class TelegramExtractor:
    def __init__(self, log_callback):
        self._log = log_callback
        self.playwright = None
        self.browser = None
        self.page = None
        self._task_queue: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def _worker_loop(self):
        while True:
            task, event, box = self._task_queue.get()
            if task is None:
                break
            try:
                box["value"] = task()
                box["error"] = None
            except Exception as exc:
                box["value"] = None
                box["error"] = exc
            finally:
                event.set()

    def _run(self, fn):
        box = {"value": None, "error": None}
        ev = threading.Event()
        self._task_queue.put((fn, ev, box))
        ev.wait()
        if box["error"]:
            raise box["error"]
        return box["value"]

    def _start_browser(self):
        self._close_browser_internal()
        self.playwright = sync_playwright().start()
        exe = find_chromium_executable()
        kwargs = {"headless": False}
        if exe:
            self._log(f"[+] Chromium: {exe}")
            kwargs["executable_path"] = exe
        else:
            self._log("[+] Используется системный Playwright")
        self.browser = self.playwright.chromium.launch(**kwargs)
        self.page = self.browser.new_context().new_page()

    def _close_browser_internal(self):
        for attr in ("browser", "playwright"):
            try:
                obj = getattr(self, attr)
                if obj:
                    obj.close() if attr == "browser" else obj.stop()
                    setattr(self, attr, None)
            except Exception:
                pass

    def close_browser(self):
        self._run(self._close_browser_internal)

    def stop(self):
        self._task_queue.put((None, threading.Event(), {}))

    def send_code(self, phone: str):
        def _t():
            self._log("[+] Запускаем браузер...")
            self._start_browser()
            self._log("[+] Открываем my.telegram.org...")
            self.page.goto("https://my.telegram.org/auth")
            inp = self.page.get_by_role("textbox", name="Your Phone Number")
            inp.wait_for(timeout=30000)
            inp.fill(phone)
            self._click_submit()
            self._log("[+] Код отправлен в Telegram")
            self._log("[+] Введите код и нажмите «Подтвердить»")
        self._run(_t)

    def confirm_code(self, code: str) -> dict:
        def _t():
            inp = self.page.get_by_placeholder("Confirmation code")
            inp.wait_for(timeout=30000)
            inp.fill(code)
            self._click_submit()
            self.page.wait_for_timeout(3000)
            self._log("[+] Авторизация успешна")
            return self._extract_credentials()
        return self._run(_t)

    def _click_submit(self):
        for sel in ['button:has-text("Next")', 'button:has-text("Sign In")',
                    'button.btn-primary', 'input[type="submit"]']:
            loc = self.page.locator(sel)
            if loc.count() > 0:
                try:
                    loc.first.click(timeout=5000)
                    return
                except Exception:
                    pass

    def _create_app(self):
        self._log("[+] Создаём приложение...")
        self.page.locator("input").nth(0).fill(f"MyApp{random.randint(1000,9999)}")
        self.page.locator("input").nth(1).fill(f"app{random.randint(100000,999999)}")
        ta = self.page.locator("textarea")
        if ta.count() > 0:
            ta.first.fill("Personal Telegram API")
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

        m_id   = re.search(r"App api_id:\s*(\d+)", text)
        m_hash = re.search(r"App api_hash:\s*([a-fA-F0-9]{32})", text)
        if not m_id or not m_hash:
            raise RuntimeError("Не удалось найти api_id / api_hash на странице")

        m_test_host = re.search(r"Test configuration:\s*([\d.:]+)", text)
        m_prod_host = re.search(r"Production configuration:\s*([\d.:]+)", text)
        m_test_key  = re.search(r"(-----BEGIN RSA PUBLIC KEY-----.*?-----END RSA PUBLIC KEY-----)", text, re.S)
        m_prod_key  = re.search(r"(-----BEGIN RSA PUBLIC KEY-----.*?-----END RSA PUBLIC KEY-----(?:.*?-----BEGIN RSA PUBLIC KEY-----.*?-----END RSA PUBLIC KEY-----)?)", text, re.S)

        keys_raw = re.findall(r"(-----BEGIN RSA PUBLIC KEY-----.*?-----END RSA PUBLIC KEY-----)", text, re.S)

        data = {
            "api_id":   int(m_id.group(1)),
            "api_hash": m_hash.group(1),
            "test_server":       m_test_host.group(1) if m_test_host else "",
            "production_server": m_prod_host.group(1) if m_prod_host else "",
            "public_keys":       keys_raw,
        }

        OUTPUT_DIR.mkdir(exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        self._log("[+] Данные успешно получены")
        self._log(f"[+] Сохранено: {OUTPUT_FILE}")
        return data


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _label(parent, text, font_size=13, weight="normal", color=None, **kw):
    kwargs = dict(text=text, font=(ctk.ThemeManager.theme["CTkFont"]["family"], font_size,
                                   "bold" if weight == "bold" else "normal"))
    if color:
        kwargs["text_color"] = color
    return ctk.CTkLabel(parent, **kwargs, **kw)


def _btn(parent, text, cmd, width=160, fg=None, **kw):
    return ctk.CTkButton(
        parent, text=text, command=cmd, width=width,
        fg_color=fg or ACCENT, hover_color="#2563EB", **kw
    )


# ---------------------------------------------------------------------------
# Sidebar nav button
# ---------------------------------------------------------------------------

class NavButton(ctk.CTkButton):
    def __init__(self, parent, text, icon, command, **kw):
        super().__init__(
            parent, text=f"  {icon}  {text}", command=command,
            anchor="w", width=SIDEBAR_WIDTH - 16,
            fg_color="transparent", hover_color=("#d0d4da", "#2a2d35"),
            text_color=("gray40", "gray70"), corner_radius=8,
            font=(ctk.ThemeManager.theme["CTkFont"]["family"], 13), **kw
        )
        self._active = False

    def set_active(self, active: bool):
        self._active = active
        if active:
            self.configure(
                fg_color=(ACCENT, ACCENT),
                text_color=("white", "white"),
            )
        else:
            self.configure(
                fg_color="transparent",
                text_color=("gray40", "gray70"),
            )


# ---------------------------------------------------------------------------
# Tab frames
# ---------------------------------------------------------------------------

class MainTab(ctk.CTkFrame):
    def __init__(self, parent, extractor: TelegramExtractor, on_data_ready):
        super().__init__(parent, fg_color="transparent")
        self._extractor = extractor
        self._on_data_ready = on_data_ready
        self._log_visible = True
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)

        _label(self, "Авторизация", 20, "bold").grid(row=0, column=0, sticky="w", padx=28, pady=(28, 2))
        _label(self, "Введите номер телефона — получите api_id и api_hash", 13,
               color=("gray40", "gray60")).grid(row=1, column=0, sticky="w", padx=28, pady=(0, 20))

        phone_row = ctk.CTkFrame(self, fg_color="transparent")
        phone_row.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 10))
        phone_row.grid_columnconfigure(0, weight=1)
        self.phone_entry = ctk.CTkEntry(phone_row, placeholder_text="+79991234567", height=38)
        self.phone_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.btn_code = _btn(phone_row, "Получить код", self._start_login, width=140, height=38)
        self.btn_code.grid(row=0, column=1)

        code_row = ctk.CTkFrame(self, fg_color="transparent")
        code_row.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 16))
        code_row.grid_columnconfigure(0, weight=1)
        self.code_entry = ctk.CTkEntry(code_row, placeholder_text="Код из Telegram", height=38)
        self.code_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.btn_confirm = _btn(code_row, "Подтвердить", self._submit_code, width=140, height=38)
        self.btn_confirm.grid(row=0, column=1)

        log_header = ctk.CTkFrame(self, fg_color="transparent")
        log_header.grid(row=4, column=0, sticky="ew", padx=28, pady=(0, 4))
        _label(log_header, "Лог", 12, color=("gray50", "gray50")).pack(side="left")
        self.toggle_btn = ctk.CTkButton(
            log_header, text="скрыть", width=60, height=22,
            fg_color="transparent", hover_color=("#e5e7eb", "#2a2d35"),
            text_color=("gray50", "gray50"), font=(ctk.ThemeManager.theme["CTkFont"]["family"], 11),
            command=self._toggle_log
        )
        self.toggle_btn.pack(side="right")

        self.log_box = ctk.CTkTextbox(self, height=180, state="disabled",
                                      font=(ctk.ThemeManager.theme["CTkFont"]["family"], 12))
        self.log_box.grid(row=5, column=0, sticky="nsew", padx=28, pady=(0, 28))

    def log(self, text: str):
        self.after(0, lambda t=text: self._append(t))

    def _append(self, text: str):
        self.log_box.configure(state="normal")
        tag = "ok" if text.startswith("[+]") else "err"
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _toggle_log(self):
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.log_box.grid()
            self.toggle_btn.configure(text="скрыть")
        else:
            self.log_box.grid_remove()
            self.toggle_btn.configure(text="показать")

    def _start_login(self):
        phone = self.phone_entry.get().strip()
        if not phone.startswith("+"):
            self.log("[!] Номер должен начинаться с +")
            return
        self.btn_code.configure(state="disabled")
        threading.Thread(target=self._login_worker, args=(phone,), daemon=True).start()

    def _login_worker(self, phone):
        try:
            self._extractor.send_code(phone)
        except Exception as e:
            self.log(f"[!] Ошибка: {e}")
        finally:
            self.after(0, lambda: self.btn_code.configure(state="normal"))

    def _submit_code(self):
        code = self.code_entry.get().strip()
        if not code:
            self.log("[!] Введите код")
            return
        self.btn_confirm.configure(state="disabled")
        threading.Thread(target=self._code_worker, args=(code,), daemon=True).start()

    def _code_worker(self, code):
        try:
            data = self._extractor.confirm_code(code)
            self.after(0, lambda: self._on_data_ready(data))
        except Exception as e:
            self.log(f"[!] Ошибка подтверждения: {e}")
        finally:
            self.after(0, lambda: self.btn_confirm.configure(state="normal"))


class DataTab(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")
        self._data = None
        self._build_empty()

    def _build_empty(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(10, weight=1)

        _label(self, "Мои данные", 20, "bold").grid(row=0, column=0, sticky="w", padx=28, pady=(28, 2))
        self._sub = _label(self, "Данные появятся после успешной авторизации", 13,
                           color=("gray40", "gray60"))
        self._sub.grid(row=1, column=0, sticky="w", padx=28, pady=(0, 20))

        self._cards_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._cards_frame.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 16))

        self._export_label = _label(self, "Экспорт", 13, "bold")
        self._export_label.grid(row=3, column=0, sticky="w", padx=28, pady=(0, 8))
        self._export_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._export_frame.grid(row=4, column=0, sticky="w", padx=28, pady=(0, 20))

        self._keys_label = _label(self, "Public keys", 13, "bold")
        self._keys_label.grid(row=5, column=0, sticky="w", padx=28, pady=(0, 8))
        self._keys_box = ctk.CTkTextbox(self, height=160, state="disabled",
                                        font=(ctk.ThemeManager.theme["CTkFont"]["family"], 11))
        self._keys_box.grid(row=6, column=0, sticky="ew", padx=28, pady=(0, 28))

    def update_data(self, data: dict):
        self._data = data
        self._sub.configure(text="Данные успешно получены")

        for w in self._cards_frame.winfo_children():
            w.destroy()

        cards = [
            ("App api_id",           str(data["api_id"])),
            ("App api_hash",         data["api_hash"]),
            ("Test server",          data.get("test_server", "—")),
            ("Production server",    data.get("production_server", "—")),
        ]
        for i, (label, value) in enumerate(cards):
            card = ctk.CTkFrame(self._cards_frame, corner_radius=10)
            card.grid(row=i // 2, column=i % 2, padx=(0 if i%2==0 else 8, 0), pady=4, sticky="ew")
            self._cards_frame.grid_columnconfigure(i % 2, weight=1)
            _label(card, label, 11, color=("gray50", "gray50")).pack(anchor="w", padx=14, pady=(10, 2))
            _label(card, value, 13, "bold").pack(anchor="w", padx=14, pady=(0, 10))

        for w in self._export_frame.winfo_children():
            w.destroy()

        formats = [
            (".json", self._export_json),
            (".txt",  self._export_txt),
            (".env",  self._export_env),
            (".csv",  self._export_csv),
            (".md",   self._export_md),
            ("⎘ Копировать", self._copy_all),
        ]
        for label, cmd in formats:
            b = ctk.CTkButton(
                self._export_frame, text=label, command=cmd,
                width=90, height=30, fg_color="transparent",
                border_width=1, border_color=("gray70", "gray40"),
                text_color=("gray30", "gray80"),
                hover_color=("#e5e7eb", "#2a2d35"),
                font=(ctk.ThemeManager.theme["CTkFont"]["family"], 12)
            )
            b.pack(side="left", padx=(0, 6))

        self._keys_box.configure(state="normal")
        self._keys_box.delete("1.0", "end")
        for i, key in enumerate(data.get("public_keys", []), 1):
            self._keys_box.insert("end", f"— Key {i} —\n{key.strip()}\n\n")
        self._keys_box.configure(state="disabled")

    def _get_path(self, ext):
        OUTPUT_DIR.mkdir(exist_ok=True)
        return OUTPUT_DIR / f"credentials{ext}"

    def _export_json(self):
        if not self._data:
            return
        path = self._get_path(".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=4)
        messagebox.showinfo("Экспорт", f"Сохранено: {path}")

    def _export_txt(self):
        if not self._data:
            return
        path = self._get_path(".txt")
        lines = [
            f"api_id = {self._data['api_id']}",
            f"api_hash = {self._data['api_hash']}",
            f"test_server = {self._data.get('test_server', '')}",
            f"production_server = {self._data.get('production_server', '')}",
        ]
        for i, k in enumerate(self._data.get("public_keys", []), 1):
            lines.append(f"\n[public_key_{i}]\n{k.strip()}")
        path.write_text("\n".join(lines), encoding="utf-8")
        messagebox.showinfo("Экспорт", f"Сохранено: {path}")

    def _export_env(self):
        if not self._data:
            return
        path = self._get_path(".env")
        lines = [
            f"API_ID={self._data['api_id']}",
            f"API_HASH={self._data['api_hash']}",
            f"TEST_SERVER={self._data.get('test_server', '')}",
            f"PRODUCTION_SERVER={self._data.get('production_server', '')}",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        messagebox.showinfo("Экспорт", f"Сохранено: {path}")

    def _export_csv(self):
        if not self._data:
            return
        path = self._get_path(".csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["field", "value"])
            w.writerow(["api_id",            self._data["api_id"]])
            w.writerow(["api_hash",           self._data["api_hash"]])
            w.writerow(["test_server",        self._data.get("test_server", "")])
            w.writerow(["production_server",  self._data.get("production_server", "")])
        messagebox.showinfo("Экспорт", f"Сохранено: {path}")

    def _export_md(self):
        if not self._data:
            return
        path = self._get_path(".md")
        lines = [
            "# Telegram API credentials\n",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| api_id | `{self._data['api_id']}` |",
            f"| api_hash | `{self._data['api_hash']}` |",
            f"| test_server | `{self._data.get('test_server', '')}` |",
            f"| production_server | `{self._data.get('production_server', '')}` |",
        ]
        for i, k in enumerate(self._data.get("public_keys", []), 1):
            lines.append(f"\n## Public key {i}\n\n```\n{k.strip()}\n```")
        path.write_text("\n".join(lines), encoding="utf-8")
        messagebox.showinfo("Экспорт", f"Сохранено: {path}")

    def _copy_all(self):
        if not self._data:
            return
        text = (
            f"api_id = {self._data['api_id']}\n"
            f"api_hash = {self._data['api_hash']}\n"
            f"test_server = {self._data.get('test_server','')}\n"
            f"production_server = {self._data.get('production_server','')}\n"
        )
        pyperclip.copy(text)
        messagebox.showinfo("Скопировано", "Данные скопированы в буфер обмена")


class SettingsTab(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        _label(self, "Настройки", 20, "bold").grid(row=0, column=0, sticky="w", padx=28, pady=(28, 20))

        settings = [
            ("Headless-режим", "Скрывать окно браузера при работе"),
            ("Автосохранение", "Сохранять credentials.json автоматически"),
            ("Системная тема", "Следовать тёмной/светлой теме ОС"),
        ]
        self._switches = {}
        for i, (name, desc) in enumerate(settings):
            row = ctk.CTkFrame(self, fg_color="transparent")
            row.grid(row=i+1, column=0, sticky="ew", padx=28, pady=4)
            row.grid_columnconfigure(0, weight=1)
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.grid(row=0, column=0, sticky="w")
            _label(info, name, 13, "bold").pack(anchor="w")
            _label(info, desc, 12, color=("gray50", "gray50")).pack(anchor="w")
            sw = ctk.CTkSwitch(row, text="", width=46)
            sw.grid(row=0, column=1, padx=(10, 0))
            if name == "Автосохранение":
                sw.select()
            self._switches[name] = sw

            sep = ctk.CTkFrame(self, height=1, fg_color=("gray85", "gray25"))
            sep.grid(row=i+10, column=0, sticky="ew", padx=28, pady=2)


class AboutTab(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        _label(self, "О программе", 20, "bold").grid(row=0, column=0, sticky="w", padx=28, pady=(28, 16))

        badge = ctk.CTkFrame(self, corner_radius=8)
        badge.grid(row=1, column=0, sticky="w", padx=28, pady=(0, 16))
        _label(badge, "v1.1.0", 12).pack(padx=12, pady=6)

        _label(self,
               "Portable-утилита для автоматического получения api_id и api_hash\n"
               "с сайта my.telegram.org через встроенный браузер Playwright.\n"
               "Работает полностью локально — данные никуда не отправляются.",
               13, color=("gray40", "gray60"), justify="left"
               ).grid(row=2, column=0, sticky="w", padx=28, pady=(0, 20))

        links = [
            ("⎋  github.com/Achinsky/Get-Telegram-API", "https://github.com/Achinsky/Get-Telegram-API"),
            ("⊕  MIT License", None),
        ]
        for text, _ in links:
            _label(self, text, 13, color=("gray40", "gray60")).grid(
                row=links.index((text, _)) + 3,
                column=0, sticky="w", padx=28, pady=2
            )


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

class TelegramExtractorApp:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.geometry("820x580")
        self.root.minsize(700, 500)
        self.root.title("Get Telegram API")
        self._load_icon()

        self.extractor = TelegramExtractor(log_callback=self._log)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_layout()

    def _load_icon(self):
        try:
            p = os.path.join(get_base_path(), "assets", "logo.png")
            self.root.iconphoto(True, ImageTk.PhotoImage(Image.open(p)))
        except Exception as e:
            print(e)

    def _on_close(self):
        self.extractor.stop()
        self.root.destroy()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self):
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        # Sidebar
        sidebar = ctk.CTkFrame(self.root, width=SIDEBAR_WIDTH, corner_radius=0,
                                fg_color=("#f3f4f6", "#1c1f26"))
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(10, weight=1)

        # Logo
        logo_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        logo_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(20, 16))
        try:
            p = os.path.join(get_base_path(), "assets", "logo.png")
            img = ctk.CTkImage(Image.open(p), size=(28, 28))
            ctk.CTkLabel(logo_frame, image=img, text="").pack(side="left", padx=(4, 8))
        except Exception:
            pass
        _label(logo_frame, "Get Telegram API", 13, "bold").pack(side="left")

        sep = ctk.CTkFrame(sidebar, height=1, fg_color=("gray80", "gray30"))
        sep.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))

        # Content area
        self._content = ctk.CTkFrame(self.root, corner_radius=0, fg_color="transparent")
        self._content.grid(row=0, column=1, sticky="nsew")
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(0, weight=1)

        # Tabs
        self.data_tab = DataTab(self._content)
        self.main_tab = MainTab(self._content, self.extractor, self._on_data_ready)
        self.settings_tab = SettingsTab(self._content)
        self.about_tab = AboutTab(self._content)

        self._tabs = {
            "main":     self.main_tab,
            "data":     self.data_tab,
            "settings": self.settings_tab,
            "about":    self.about_tab,
        }
        for tab in self._tabs.values():
            tab.grid(row=0, column=0, sticky="nsew")

        # Nav buttons
        nav_items = [
            ("main",     "🏠", "Главная"),
            ("data",     "🔑", "Мои данные"),
            ("settings", "⚙", "Настройки"),
        ]
        self._nav_btns = {}
        for i, (key, icon, label) in enumerate(nav_items):
            btn = NavButton(sidebar, label, icon, command=lambda k=key: self._show_tab(k))
            btn.grid(row=i+2, column=0, padx=8, pady=2, sticky="ew")
            self._nav_btns[key] = btn

        # About at bottom
        about_btn = NavButton(sidebar, "О программе", "ℹ", command=lambda: self._show_tab("about"))
        about_btn.grid(row=10, column=0, padx=8, pady=(0, 12), sticky="sew")
        self._nav_btns["about"] = about_btn

        self._show_tab("main")

    def _show_tab(self, key: str):
        for k, tab in self._tabs.items():
            if k == key:
                tab.tkraise()
            self._nav_btns[k].set_active(k == key)

    def _log(self, text: str):
        self.root.after(0, lambda t=text: self.main_tab.log(t))

    def _on_data_ready(self, data: dict):
        self.data_tab.update_data(data)
        self._show_tab("data")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = TelegramExtractorApp()
    app.run()
