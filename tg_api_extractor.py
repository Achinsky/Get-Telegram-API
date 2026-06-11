import csv
import json
import queue
import random
import re
import threading
import webbrowser
from pathlib import Path
import sys
import os
from PIL import Image, ImageTk
import customtkinter as ctk
from tkinter import messagebox

import pyperclip
from playwright.sync_api import sync_playwright

OUTPUT_DIR   = Path("output")
OUTPUT_FILE  = OUTPUT_DIR / "credentials.json"
SETTINGS_FILE = Path(get_base_path() if False else ".") / "settings.json"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

ACCENT       = "#29A9E0"
ACCENT_HOV   = "#1A8BBF"
SIDEBAR_BG   = ("#1a1d23", "#1a1d23")
CONTENT_BG   = ("#141618", "#141618")
CARD_BG      = ("#1e2128", "#1e2128")
SIDEBAR_WIDTH = 180

TI = {
    "home":        chr(60097),
    "key":         chr(60103),
    "settings":    chr(60192),
    "info-circle": chr(60101),
    "copy":        chr(60026),
    "check":       chr(59998),
    "download":    chr(60054),
}

_tabler_loaded = False


def get_base_path() -> str:
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


SETTINGS_FILE = Path(get_base_path()) / "settings.json"


def load_settings() -> dict:
    try:
        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"headless": False, "autosave": True, "hide_data": False}


def save_settings(d: dict):
    try:
        SETTINGS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    except Exception:
        pass


def _load_tabler_font():
    global _tabler_loaded
    if _tabler_loaded:
        return
    fp = Path(get_base_path()) / "assets" / "tabler-icons.ttf"
    if not fp.exists():
        return
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.gdi32.AddFontResourceExW(str(fp), 0x10, 0)
        _tabler_loaded = True
    except Exception:
        pass


def _ti(icon: str, size: int = 14):
    _load_tabler_font()
    fb = {"home": "⌂", "key": "⚿", "settings": "⚙",
          "info-circle": "ℹ", "copy": "⎘", "check": "✓", "download": "↓"}
    if _tabler_loaded:
        return TI.get(icon, "?"), ("tabler-icons", size)
    return fb.get(icon, "•"), ("", size)


def find_chromium_executable() -> str | None:
    pd = Path(get_base_path()) / "ms-playwright"
    if not pd.exists():
        return None
    for d in sorted(pd.glob("chromium-*"), reverse=True):
        for c in [d / "chrome-win64" / "chrome.exe",
                  d / "chrome-mac" / "Chromium.app" / "Contents" / "MacOS" / "Chromium",
                  d / "chrome-linux" / "chrome"]:
            if c.exists():
                return str(c)
    return None


# ---------------------------------------------------------------------------
# Business logic
# ---------------------------------------------------------------------------

class TelegramExtractor:
    def __init__(self, log_cb):
        self._log = log_cb
        self.playwright = self.browser = self.page = None
        self._q: queue.Queue = queue.Queue()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            fn, ev, box = self._q.get()
            if fn is None:
                break
            try:
                box["v"] = fn()
            except Exception as e:
                box["e"] = e
            finally:
                ev.set()

    def _run(self, fn):
        box = {"v": None, "e": None}
        ev = threading.Event()
        self._q.put((fn, ev, box))
        ev.wait()
        if box["e"]:
            raise box["e"]
        return box["v"]

    def _open_browser(self, headless=False):
        self._close()
        self.playwright = sync_playwright().start()
        exe = find_chromium_executable()
        kw = {"headless": headless}
        if exe:
            self._log(f"[+] Chromium: {exe}")
            kw["executable_path"] = exe
        else:
            self._log("[+] Используется системный Playwright")
        self.browser = self.playwright.chromium.launch(**kw)
        self.page = self.browser.new_context().new_page()

    def _close(self):
        for a in ("browser", "playwright"):
            try:
                o = getattr(self, a)
                if o:
                    (o.close if a == "browser" else o.stop)()
                    setattr(self, a, None)
            except Exception:
                pass

    def stop(self):
        self._q.put((None, threading.Event(), {}))

    def send_code(self, phone: str, headless=False):
        def _t():
            self._log("[+] Запускаем браузер...")
            self._open_browser(headless)
            self._log("[+] Открываем my.telegram.org...")
            self.page.goto("https://my.telegram.org/auth")
            inp = self.page.get_by_role("textbox", name="Your Phone Number")
            inp.wait_for(timeout=30000)
            inp.fill(phone)
            self._submit()
            self._log("[+] Код отправлен в Telegram")
            self._log("[+] Введите код и нажмите «Подтвердить»")
        self._run(_t)

    def confirm_code(self, code: str) -> dict:
        def _t():
            inp = self.page.get_by_placeholder("Confirmation code")
            inp.wait_for(timeout=30000)
            inp.fill(code)
            self._submit()
            self.page.wait_for_timeout(3000)
            self._log("[+] Авторизация успешна")
            return self._extract()
        return self._run(_t)

    def _submit(self):
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
        # Use only VISIBLE text inputs — skip hidden fields like input[name="hash"]
        visible_inputs = self.page.locator(
            "input[type='text']:visible, input:not([type]):visible"
        )
        visible_inputs.first.wait_for(timeout=10000)
        count = visible_inputs.count()
        if count >= 1:
            visible_inputs.nth(0).fill(f"MyApp{random.randint(1000, 9999)}")
        if count >= 2:
            visible_inputs.nth(1).fill(f"personalapi{random.randint(1000, 9999)}")

        ta = self.page.locator("textarea")
        if ta.count():
            ta.first.fill("Personal Telegram API")
        try:
            self.page.locator('select[name="app_platform"]').select_option("other")
        except Exception:
            pass
        try:
            self.page.locator('input[type="radio"]').nth(0).check()
        except Exception:
            pass
        self.page.get_by_text("Create application").click()
        self.page.wait_for_load_state("networkidle")

    def _extract(self) -> dict:
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

        m_title = re.search(r"App title:\s*(.+)", text)
        m_short = re.search(r"Short name:\s*(.+)", text)
        m_test  = re.search(r"Test configuration:\s*([\d.:]+)", text)
        m_prod  = re.search(r"Production configuration:\s*([\d.:]+)", text)
        keys    = re.findall(
            r"(-----BEGIN RSA PUBLIC KEY-----.*?-----END RSA PUBLIC KEY-----)",
            text, re.S)

        data = {
            "api_id":            int(m_id.group(1)),
            "api_hash":          m_hash.group(1),
            "app_title":         m_title.group(1).strip() if m_title else "",
            "short_name":        m_short.group(1).strip() if m_short else "",
            "test_server":       m_test.group(1) if m_test else "",
            "production_server": m_prod.group(1) if m_prod else "",
            "public_keys":       keys,
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

def _sf(size=13, bold=False):
    return (ctk.ThemeManager.theme["CTkFont"]["family"], size,
            "bold" if bold else "normal")


def _lbl(parent, text, size=13, bold=False, color=None, **kw):
    kw2 = dict(text=text, font=_sf(size, bold))
    if color:
        kw2["text_color"] = color
    return ctk.CTkLabel(parent, **kw2, **kw)


def _mask(value: str) -> str:
    """Replace value with bullet dots for privacy mode."""
    return "•" * min(len(value), 16)


class CopyButton(ctk.CTkButton):
    """Icon button that flashes ✓ for 1.5 s after copying."""

    def __init__(self, parent, get_value, **kw):
        self._get_value = get_value
        char, font = _ti("copy", 13)
        super().__init__(
            parent,
            text=char,
            font=font if _tabler_loaded else _sf(11),
            width=28, height=22,
            fg_color="transparent",
            hover_color=("#2a2d35", "#2a2d35"),
            text_color=("gray55", "gray55"),
            command=self._do_copy,
            **kw
        )

    def _do_copy(self):
        try:
            pyperclip.copy(self._get_value())
        except Exception:
            return
        ok_char, ok_font = _ti("check", 13)
        self.configure(text=ok_char,
                       text_color=(ACCENT, ACCENT),
                       font=ok_font if _tabler_loaded else _sf(11))
        self.after(1500, self._reset)

    def _reset(self):
        char, font = _ti("copy", 13)
        self.configure(text=char,
                       text_color=("gray55", "gray55"),
                       font=font if _tabler_loaded else _sf(11))


def _data_card(parent, label: str, value: str, col: int, row: int,
               hide: bool = False):
    display = _mask(value) if hide else value
    card = ctk.CTkFrame(parent, corner_radius=8, fg_color=CARD_BG)
    card.grid(row=row, column=col,
              padx=(0 if col == 0 else 6, 0), pady=4, sticky="ew")
    card.grid_columnconfigure(0, weight=1)

    top = ctk.CTkFrame(card, fg_color="transparent")
    top.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
    top.grid_columnconfigure(0, weight=1)
    _lbl(top, label, 11, color=("gray55", "gray55")).grid(
        row=0, column=0, sticky="w")
    CopyButton(top, lambda v=value: v).grid(row=0, column=1, sticky="e")

    _lbl(card, display, 13, bold=True).grid(
        row=1, column=0, sticky="w", padx=12, pady=(2, 10))
    return card


def _key_card(parent, label: str, value: str, col: int, row: int,
              hide: bool = False):
    display = _mask(value) if hide else value.strip()
    card = ctk.CTkFrame(parent, corner_radius=8, fg_color=CARD_BG)
    card.grid(row=row, column=col,
              padx=(0 if col == 0 else 6, 0), pady=4, sticky="nsew")
    card.grid_columnconfigure(0, weight=1)
    card.grid_rowconfigure(1, weight=1)

    top = ctk.CTkFrame(card, fg_color="transparent")
    top.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
    top.grid_columnconfigure(0, weight=1)
    _lbl(top, label, 11, color=("gray55", "gray55")).grid(
        row=0, column=0, sticky="w")
    CopyButton(top, lambda v=value: v).grid(row=0, column=1, sticky="e")

    tb = ctk.CTkTextbox(card, height=110, state="disabled",
                        font=(_sf(10)[0], 10), wrap="none",
                        fg_color="transparent")
    tb.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
    tb.configure(state="normal")
    tb.insert("end", display)
    tb.configure(state="disabled")
    return card


# ---------------------------------------------------------------------------
# NavButton
# ---------------------------------------------------------------------------

class NavButton(ctk.CTkButton):
    def __init__(self, parent, label, icon, cmd, **kw):
        char, _ = _ti(icon, 14)
        super().__init__(
            parent, text=f"  {char}  {label}", command=cmd,
            anchor="w", width=SIDEBAR_WIDTH - 16,
            fg_color="transparent",
            hover_color=("#252830", "#252830"),
            text_color=("gray60", "gray60"),
            corner_radius=6, font=_sf(13), **kw)

    def set_active(self, on: bool):
        if on:
            self.configure(fg_color=(ACCENT, ACCENT),
                           text_color=("white", "white"))
        else:
            self.configure(fg_color="transparent",
                           text_color=("gray60", "gray60"))


# ---------------------------------------------------------------------------
# Tab: Main
# ---------------------------------------------------------------------------

class MainTab(ctk.CTkFrame):
    def __init__(self, parent, extractor, on_ready, settings: dict):
        super().__init__(parent, fg_color="transparent")
        self._ext = extractor
        self._on_ready = on_ready
        self._settings = settings
        self._log_vis = True
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)

        _lbl(self, "Авторизация", 20, bold=True).grid(
            row=0, column=0, sticky="w", padx=28, pady=(28, 2))
        _lbl(self, "Введите номер телефона — получите api_id и api_hash",
             color=("gray50", "gray50")).grid(
            row=1, column=0, sticky="w", padx=28, pady=(0, 20))

        r1 = ctk.CTkFrame(self, fg_color="transparent")
        r1.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 10))
        r1.grid_columnconfigure(0, weight=1)
        self.phone = ctk.CTkEntry(r1, placeholder_text="+79991234567",
                                  height=38)
        self.phone.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.btn_get = ctk.CTkButton(
            r1, text="Получить код", width=140, height=38,
            fg_color=ACCENT, hover_color=ACCENT_HOV,
            command=self._get_code)
        self.btn_get.grid(row=0, column=1)

        r2 = ctk.CTkFrame(self, fg_color="transparent")
        r2.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 16))
        r2.grid_columnconfigure(0, weight=1)
        self.code = ctk.CTkEntry(r2, placeholder_text="Код из Telegram",
                                 height=38)
        self.code.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.btn_ok = ctk.CTkButton(
            r2, text="Подтвердить", width=140, height=38,
            fg_color=ACCENT, hover_color=ACCENT_HOV,
            command=self._confirm)
        self.btn_ok.grid(row=0, column=1)

        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=4, column=0, sticky="ew", padx=28, pady=(0, 4))
        _lbl(hdr, "ЛОГ", 11, color=("gray45", "gray45")).pack(side="left")
        self.tog = ctk.CTkButton(
            hdr, text="∨ скрыть", width=72, height=20,
            fg_color="transparent",
            hover_color=("#252830", "#252830"),
            text_color=("gray50", "gray50"), font=_sf(11),
            command=self._toggle)
        self.tog.pack(side="right")

        self.log_box = ctk.CTkTextbox(
            self, height=180, state="disabled", font=_sf(12))
        self.log_box.grid(row=5, column=0, sticky="nsew",
                          padx=28, pady=(0, 28))

    def log(self, text):
        self.after(0, lambda t=text: self._ap(t))

    def _ap(self, t):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", t + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _toggle(self):
        self._log_vis = not self._log_vis
        if self._log_vis:
            self.log_box.grid()
            self.tog.configure(text="∨ скрыть")
        else:
            self.log_box.grid_remove()
            self.tog.configure(text="∧ показать")

    def _get_code(self):
        phone = self.phone.get().strip()
        if not phone.startswith("+"):
            self.log("[!] Номер должен начинаться с +")
            return
        self.btn_get.configure(state="disabled")
        threading.Thread(
            target=self._t_get,
            args=(phone, self._settings.get("headless", False)),
            daemon=True).start()

    def _t_get(self, phone, headless):
        try:
            self._ext.send_code(phone, headless)
        except Exception as e:
            self.log(f"[!] Ошибка: {e}")
        finally:
            self.after(0, lambda: self.btn_get.configure(state="normal"))

    def _confirm(self):
        code = self.code.get().strip()
        if not code:
            self.log("[!] Введите код")
            return
        self.btn_ok.configure(state="disabled")
        threading.Thread(target=self._t_confirm, args=(code,),
                         daemon=True).start()

    def _t_confirm(self, code):
        try:
            data = self._ext.confirm_code(code)
            self.after(0, lambda: self._on_ready(data))
        except Exception as e:
            self.log(f"[!] Ошибка подтверждения: {e}")
        finally:
            self.after(0, lambda: self.btn_ok.configure(state="normal"))


# ---------------------------------------------------------------------------
# Tab: My Data
# ---------------------------------------------------------------------------

class DataTab(ctk.CTkFrame):
    def __init__(self, parent, settings: dict):
        super().__init__(parent, fg_color="transparent")
        self._data = None
        self._settings = settings

        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent", corner_radius=0)
        self._scroll.pack(fill="both", expand=True)
        self._scroll.grid_columnconfigure(0, weight=1)

        _lbl(self._scroll, "Мои данные", 20, bold=True).grid(
            row=0, column=0, sticky="w", padx=28, pady=(28, 2))
        self._sub = _lbl(
            self._scroll,
            "Данные появятся после успешной авторизации",
            color=("gray50", "gray50"))
        self._sub.grid(row=1, column=0, sticky="w", padx=28, pady=(0, 20))

        self._app_frame = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._app_frame.grid(row=2, column=0, sticky="ew", padx=28,
                             pady=(0, 8))
        self._app_frame.grid_columnconfigure((0, 1), weight=1)

        self._srv_frame = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._srv_frame.grid(row=3, column=0, sticky="ew", padx=28,
                             pady=(0, 8))
        self._srv_frame.grid_columnconfigure((0, 1), weight=1)

        self._key_frame = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._key_frame.grid(row=4, column=0, sticky="ew", padx=28,
                             pady=(0, 8))
        self._key_frame.grid_columnconfigure((0, 1), weight=1)

        _lbl(self._scroll, "Экспорт", 13, bold=True).grid(
            row=5, column=0, sticky="w", padx=28, pady=(8, 6))
        self._exp_frame = ctk.CTkFrame(self._scroll, fg_color="transparent")
        self._exp_frame.grid(row=6, column=0, sticky="w", padx=28,
                             pady=(0, 28))

    def update_data(self, data: dict):
        self._data = data
        self._sub.configure(text="Данные успешно получены")
        self.refresh_cards()

    def refresh_cards(self):
        """Re-draw cards honouring current hide_data setting."""
        if not self._data:
            return
        data = self._data
        hide = self._settings.get("hide_data", False)

        for f in (self._app_frame, self._srv_frame,
                  self._key_frame, self._exp_frame):
            for w in f.winfo_children():
                w.destroy()

        _data_card(self._app_frame, "App api_id",
                   str(data["api_id"]), 0, 0, hide)
        _data_card(self._app_frame, "App api_hash",
                   data["api_hash"],   1, 0, hide)
        _data_card(self._app_frame, "App title",
                   data.get("app_title", "—"), 0, 1, hide)
        _data_card(self._app_frame, "Short name",
                   data.get("short_name", "—"), 1, 1, hide)

        _data_card(self._srv_frame, "Test server",
                   data.get("test_server", "—"), 0, 0, hide)
        _data_card(self._srv_frame, "Production server",
                   data.get("production_server", "—"), 1, 0, hide)

        keys = data.get("public_keys", [])
        for i, key in enumerate(keys[:2]):
            _key_card(self._key_frame, f"Public key {i+1}",
                      key, i, 0, hide)

        fmts = [(".json", self._ej), (".txt", self._et),
                (".env",  self._ee), (".csv", self._ec),
                (".md",   self._em)]
        for lbl_text, cmd in fmts:
            ctk.CTkButton(
                self._exp_frame, text=lbl_text, command=cmd,
                width=72, height=30,
                fg_color="transparent",
                border_width=1, border_color=("gray35", "gray35"),
                text_color=("gray70", "gray70"),
                hover_color=("#252830", "#252830"),
                font=_sf(12)
            ).pack(side="left", padx=(0, 6))

    def _full_text(self) -> str:
        d = self._data
        keys = d.get("public_keys", [])
        k1 = keys[0].strip() if keys else ""
        k2 = keys[1].strip() if len(keys) > 1 else ""
        return (
            f"— App configuration:\n\n"
            f"App api_id: {d['api_id']}\n"
            f"App api_hash: {d['api_hash']}\n"
            f"App title: {d.get('app_title', '')}\n"
            f"Short name: {d.get('short_name', '')}\n\n\n"
            f"— Available MTProto servers\n\n"
            f"Test configuration: {d.get('test_server', '')}\n"
            f"Public keys:\n{k1}\n\n"
            f"Production configuration: {d.get('production_server', '')}\n"
            f"Public keys:\n{k2}\n"
        )

    def _save(self, ext, content):
        OUTPUT_DIR.mkdir(exist_ok=True)
        p = OUTPUT_DIR / f"credentials{ext}"
        p.write_text(content, encoding="utf-8")
        messagebox.showinfo("Экспорт", f"Сохранено: {p}")

    def _ej(self):
        if not self._data:
            return
        OUTPUT_DIR.mkdir(exist_ok=True)
        with open(OUTPUT_DIR / "credentials.json", "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=4)
        messagebox.showinfo("Экспорт",
                            f"Сохранено: {OUTPUT_DIR / 'credentials.json'}")

    def _et(self):
        if self._data:
            self._save(".txt", self._full_text())

    def _ee(self):
        if not self._data:
            return
        d = self._data
        self._save(".env",
                   f"API_ID={d['api_id']}\n"
                   f"API_HASH={d['api_hash']}\n"
                   f"TEST_SERVER={d.get('test_server', '')}\n"
                   f"PRODUCTION_SERVER={d.get('production_server', '')}\n")

    def _ec(self):
        if not self._data:
            return
        import io
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["field", "value"])
        for k, v in [("api_id", self._data["api_id"]),
                     ("api_hash", self._data["api_hash"]),
                     ("app_title", self._data.get("app_title", "")),
                     ("short_name", self._data.get("short_name", "")),
                     ("test_server", self._data.get("test_server", "")),
                     ("production_server",
                      self._data.get("production_server", ""))]:
            w.writerow([k, v])
        self._save(".csv", buf.getvalue())

    def _em(self):
        if not self._data:
            return
        d = self._data
        keys = d.get("public_keys", [])
        lines = [
            "# Telegram API credentials\n",
            "| Field | Value |", "|-------|-------|",
            f"| api_id | `{d['api_id']}` |",
            f"| api_hash | `{d['api_hash']}` |",
            f"| app_title | `{d.get('app_title', '')}` |",
            f"| short_name | `{d.get('short_name', '')}` |",
            f"| test_server | `{d.get('test_server', '')}` |",
            f"| production_server | `{d.get('production_server', '')}` |",
        ]
        for i, k in enumerate(keys, 1):
            lines.append(f"\n## Public key {i}\n\n```\n{k.strip()}\n```")
        self._save(".md", "\n".join(lines))


# ---------------------------------------------------------------------------
# Tab: Settings
# ---------------------------------------------------------------------------

class SettingsTab(ctk.CTkFrame):
    def __init__(self, parent, settings: dict, on_change):
        super().__init__(parent, fg_color="transparent")
        self._settings = settings
        self._on_change = on_change
        self.grid_columnconfigure(0, weight=1)

        _lbl(self, "Настройки", 20, bold=True).grid(
            row=0, column=0, sticky="w", padx=28, pady=(28, 20))

        rows = [
            ("headless",  "Headless-режим",
             "Скрывать окно браузера при работе"),
            ("autosave",  "Автосохранение",
             "Сохранять credentials.json автоматически"),
            ("hide_data", "Скрытие данных",
             "Маскировать значения в разделе «Мои данные»"),
        ]
        self._switches = {}
        for i, (key, name, desc) in enumerate(rows):
            r = ctk.CTkFrame(self, fg_color="transparent")
            r.grid(row=i + 1, column=0, sticky="ew", padx=28, pady=4)
            r.grid_columnconfigure(0, weight=1)
            info = ctk.CTkFrame(r, fg_color="transparent")
            info.grid(row=0, column=0, sticky="w")
            _lbl(info, name, 13, bold=True).pack(anchor="w")
            _lbl(info, desc, 12, color=("gray50", "gray50")).pack(anchor="w")
            sw = ctk.CTkSwitch(r, text="", width=46,
                               button_color=ACCENT,
                               progress_color=ACCENT,
                               command=lambda k=key: self._toggled(k))
            sw.grid(row=0, column=1)
            if settings.get(key, False):
                sw.select()
            self._switches[key] = sw
            ctk.CTkFrame(self, height=1,
                         fg_color=("gray20", "gray20")).grid(
                row=i + 10, column=0, sticky="ew", padx=28, pady=2)

    def _toggled(self, key: str):
        self._settings[key] = bool(self._switches[key].get())
        self._on_change(key)


# ---------------------------------------------------------------------------
# Tab: About
# ---------------------------------------------------------------------------

class AboutTab(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        _lbl(self, "О программе", 20, bold=True).grid(
            row=0, column=0, sticky="w", padx=28, pady=(28, 16))

        badge = ctk.CTkFrame(self, corner_radius=6, fg_color=CARD_BG)
        badge.grid(row=1, column=0, sticky="w", padx=28, pady=(0, 16))
        _lbl(badge, "v1.1.0", 12,
             color=("gray70", "gray70")).pack(padx=12, pady=6)

        _lbl(self,
             "Portable-утилита для автоматического получения api_id и api_hash\n"
             "с сайта my.telegram.org через встроенный браузер Playwright.\n"
             "Работает полностью локально — данные никуда не отправляются.",
             13, color=("gray50", "gray50"), justify="left").grid(
            row=2, column=0, sticky="w", padx=28, pady=(0, 20))

        links = [
            ("  github.com/Achinsky/Get-Telegram-API",
             "https://github.com/Achinsky/Get-Telegram-API"),
            ("  t.me/zaurachinsky",
             "https://t.me/zaurachinsky"),
        ]
        for i, (text, url) in enumerate(links):
            ctk.CTkButton(
                self, text=text, anchor="w",
                fg_color="transparent",
                hover_color=("#252830", "#252830"),
                text_color=(ACCENT, ACCENT),
                font=_sf(13),
                command=lambda u=url: webbrowser.open(u)
            ).grid(row=i + 3, column=0, sticky="w", padx=22, pady=1)

        _lbl(self, "  MIT License", 13,
             color=("gray50", "gray50")).grid(
            row=len(links) + 3, column=0, sticky="w", padx=28, pady=1)


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

class TelegramExtractorApp:
    def __init__(self):
        self._settings = load_settings()

        self.root = ctk.CTk()
        self.root.geometry("860x600")
        self.root.minsize(720, 500)
        self.root.title("Get Telegram API")
        self._load_icon()

        self.extractor = TelegramExtractor(log_cb=self._log)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._build()

    def _load_icon(self):
        base = get_base_path()
        ico  = os.path.join(base, "assets", "logo.ico")
        png  = os.path.join(base, "assets", "logo.png")
        try:
            if sys.platform == "win32" and os.path.exists(ico):
                self.root.iconbitmap(ico)
            elif os.path.exists(png):
                self.root.iconphoto(True,
                                    ImageTk.PhotoImage(Image.open(png)))
        except Exception as e:
            print(f"Icon: {e}")

    def _close(self):
        save_settings(self._settings)
        self.extractor.stop()
        self.root.destroy()

    def _build(self):
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        # Sidebar
        sb = ctk.CTkFrame(self.root, width=SIDEBAR_WIDTH, corner_radius=0,
                          fg_color=SIDEBAR_BG)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(10, weight=1)
        sb.grid_columnconfigure(0, weight=1)

        title_fr = ctk.CTkFrame(sb, fg_color="transparent")
        title_fr.grid(row=0, column=0, sticky="ew", pady=(22, 16))
        _lbl(title_fr, "Get Telegram API", 13, bold=True,
             color=("gray90", "gray90")).pack(anchor="center")

        ctk.CTkFrame(sb, height=1,
                     fg_color=("gray20", "gray20")).grid(
            row=1, column=0, sticky="ew", padx=12, pady=(0, 8))

        # Content
        cont = ctk.CTkFrame(self.root, corner_radius=0, fg_color=CONTENT_BG)
        cont.grid(row=0, column=1, sticky="nsew")
        cont.grid_columnconfigure(0, weight=1)
        cont.grid_rowconfigure(0, weight=1)

        self.data_tab     = DataTab(cont, self._settings)
        self.main_tab     = MainTab(cont, self.extractor,
                                    self._on_ready, self._settings)
        self.settings_tab = SettingsTab(cont, self._settings,
                                        self._on_setting_change)
        self.about_tab    = AboutTab(cont)

        self._tabs = {
            "main":     self.main_tab,
            "data":     self.data_tab,
            "settings": self.settings_tab,
            "about":    self.about_tab,
        }
        for t in self._tabs.values():
            t.grid(row=0, column=0, sticky="nsew")

        nav = [("main",     "home",        "Главная"),
               ("data",     "key",         "Мои данные"),
               ("settings", "settings",    "Настройки")]
        self._btns = {}
        for i, (k, ic, lbl) in enumerate(nav):
            b = NavButton(sb, lbl, ic, cmd=lambda x=k: self._show(x))
            b.grid(row=i + 2, column=0, padx=8, pady=2, sticky="ew")
            self._btns[k] = b

        ab = NavButton(sb, "О программе", "info-circle",
                       cmd=lambda: self._show("about"))
        ab.grid(row=10, column=0, padx=8, pady=(0, 14), sticky="sew")
        self._btns["about"] = ab

        self._show("main")

    def _show(self, key):
        for k, tab in self._tabs.items():
            if k == key:
                tab.tkraise()
            self._btns[k].set_active(k == key)

    def _log(self, text):
        self.root.after(0, lambda t=text: self.main_tab.log(t))

    def _on_ready(self, data):
        self.data_tab.update_data(data)
        self._show("data")

    def _on_setting_change(self, key: str):
        """Called when any setting toggle changes."""
        save_settings(self._settings)
        # If hide_data toggled, refresh data cards immediately
        if key == "hide_data":
            self.data_tab.refresh_cards()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = TelegramExtractorApp()
    app.run()
