import gi
import os
import shutil
import subprocess  # nosec B404 - all calls below use argv lists, never shell=True
import threading
import re
import sys
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "lufux"
CONFIG_FILE = CONFIG_DIR / "config.json"

# argv[0] of the root process, used by pkill -f to stop it
WORKER_TAG = "lufux-flash-worker"

DEFAULT_CONFIG = {"theme": 0, "lang": ""}

def resolve_bin(name):
    # absolute path for the binary, fallback to the name
    return shutil.which(name) or name

def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)
    return data if isinstance(data, dict) else dict(DEFAULT_CONFIG)

def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

APP_CONFIG = load_config()
if APP_CONFIG.get("lang"):
    os.environ["LANG"] = APP_CONFIG["lang"]

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio, Gdk

# importing logic
from windows_logic import get_windows_script
from universal_logic import get_linux_script
from deps_logic import check_dependencies, get_distro_info, get_install_cmd

# here I am
APP_VERSION = "1.1.5"
GITHUB_URL = "https://github.com/Advnirr/lufux"
WEB_URL = "https://advnirr.org/"

# Locals again
def get_locale_dict():
    lang = os.environ.get('LANG', '')
    if lang.startswith('ru'):
        return {
# russian locals
            "title": "Lufux",
            "about": "О программе",
            "btn_next": "Далее",
            "btn_back": "Назад",
            "btn_start": "Начать запись",
            "btn_cancel": "Отмена",
            "btn_yes": "Да, стереть",
            "btn_done": "Готово",
            "step_drive": "Шаг 1: Выбор накопителя",
            "step_iso": "Шаг 2: Выбор образа",
            "step_summary": "Шаг 3: Сводка",
            "no_drives": "Накопители не найдены",
            "select_iso": "Выбрать ISO-образ",
            "iso_not_selected": "Образ не выбран",
            "os_type": "Тип ОС:",
            "os_win": "Windows",
            "os_lin": "Linux / Isohybrid",
            "os_other": "Неизвестно / Другое",
            "partition_scheme": "Схема разделов (для Windows):",
            "scheme_gpt": "GPT (UEFI / FAT32)",
            "scheme_mbr": "MBR (Legacy BIOS / NTFS)",
            "summary_drive": "Целевой накопитель",
            "summary_iso": "Выбранный образ",
            "summary_os": "Определенная система",
            "summary_scheme": "Схема разметки",
            "nvme_lock": "Запись на NVMe заблокирована!",
            "warn1_title": "Внимание!",
            "warn1_body": "Все данные на накопителе\n<b>{dev}</b>\nбудут БЕЗВОЗВРАТНО УНИЧТОЖЕНЫ.\n\nПродолжить?",
            "warn2_title": "Последнее предупреждение",
            "warn2_body": "Вы абсолютно уверены? Это действие невозможно отменить.",
            "done": "Запись завершена успешно",
            "canceled": "Отменено пользователем",
            "err_crit": "Критическая ошибка:",
            "console_ready": "Инициализация... Ожидание старта.\n",
            "interrupt_title": "Прервать прогресс записи?",
            "interrupt_body": "Процесс записи образа все еще идет. Вы уверены, что хотите прервать его? Это приведет к неработоспособности накопителя до повторного форматирования",
            "interrupt_yes": "Да, прервать",
            "err_interrupted": "Прервано пользователем",
            "btn_restart": "Начать заново",
            "btn_close_app": "Закрыть программу",
            "btn_close_dialog": "Закрыть",
            "settings": "Параметры",
            "theme": "Тема оформления",
            "theme_sys": "Системная",
            "theme_light": "Светлая",
            "theme_dark": "Тёмная",
            "language": "Язык интерфейса",
            "lang_restart_title": "Смена языка",
            "lang_restart_body": "Новый язык будет применен после перезапуска программы.",
            "dep_missing_title": "Отсутствуют зависимости",
            "dep_missing_body": "Для записи требуются системные пакеты:\n<b>{deps}</b>\n\nDetected distribution: <b>{distro}</b>\nУстановить их сейчас?",
            "dep_unsupported": "Не хватает пакетов: <b>{deps}</b>\nПожалуйста, установите их вручную через пакетный менеджер.",
            "btn_install": "Установить",
            "err_code": "Код:"
        }
    return {
# english locals
        "title": "Lufux",
        "about": "About",
        "btn_next": "Next",
        "btn_back": "Back",
        "btn_start": "Start Flashing",
        "btn_cancel": "Cancel",
        "btn_yes": "Yes, wipe it",
        "btn_done": "Done",
        "step_drive": "Step 1: Select Drive",
        "step_iso": "Step 2: Select ISO",
        "step_summary": "Step 3: Summary",
        "no_drives": "No drives found",
        "select_iso": "Select ISO Image",
        "iso_not_selected": "No ISO selected",
        "os_type": "OS Type:",
        "os_win": "Windows",
        "os_lin": "Linux / Isohybrid",
        "os_other": "Unknown / Other",
        "partition_scheme": "Partition Scheme (for Windows):",
        "scheme_gpt": "GPT (UEFI / FAT32)",
        "scheme_mbr": "MBR (Legacy BIOS / NTFS)",
        "summary_drive": "Target Drive",
        "summary_iso": "Selected ISO",
        "summary_os": "Detected OS",
        "summary_scheme": "Partition Scheme",
        "nvme_lock": "NVMe writing is disabled!",
        "warn1_title": "Warning!",
        "warn1_body": "All data on drive\n<b>{dev}</b>\nwill be PERMANENTLY DESTROYED.\n\nContinue?",
        "warn2_title": "Final Warning",
        "warn2_body": "Are you absolutely sure? This action cannot be undone.",
        "done": "Flashing completed successfully",
        "canceled": "Canceled by user",
        "err_crit": "Critical Error:",
        "console_ready": "Initialization... Waiting to start.\n",
        "interrupt_title": "Interrupt flashing progress?",
        "interrupt_body": "The image writing process is still ongoing. Are you sure you want to interrupt it? The drive will be unbootable.",
        "interrupt_yes": "Yes, interrupt",
        "err_interrupted": "Interrupted by user",
        "btn_restart": "Restart",
        "btn_close_app": "Close Program",
        "btn_close_dialog": "Close",
        "settings": "Settings",
        "theme": "Theme",
        "theme_sys": "System",
        "theme_light": "Light",
        "theme_dark": "Dark",
        "language": "Language",
        "lang_restart_title": "Language Change",
        "lang_restart_body": "The new language will be applied after restarting the application.",
        "dep_missing_title": "Missing Dependencies",
        "dep_missing_body": "The following system packages are required:\n<b>{deps}</b>\n\nDetected distribution: <b>{distro}</b>\nInstall them now?",
        "dep_unsupported": "Missing packages: <b>{deps}</b>\nPlease install them manually using your package manager.",
        "btn_install": "Install",
        "err_code": "Code:"
    }

T = get_locale_dict()

class LufuxWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title(T["title"])
        self.set_default_size(600, 520)
        
        self.iso_path = None
        self.selected_dev = None
        self.pages = ["page_drive", "page_iso", "page_summary", "page_flash"]
        self.current_step = 0
        
        self.is_flashing = False
        self.proc = None

        self.connect("close-request", self.on_close_request)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        header = Adw.HeaderBar()
        main_box.append(header)
        menu = Gio.Menu.new()
        menu.append(T["settings"], "win.settings")
        menu.append(T["about"], "win.about")

        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        header.pack_end(menu_btn)

        act_about = Gio.SimpleAction.new("about", None)
        act_about.connect("activate", self.show_about)
        self.add_action(act_about)

        act_settings = Gio.SimpleAction.new("settings", None)
        act_settings.connect("activate", self.show_settings)
        self.add_action(act_settings)

        self.view_stack = Adw.ViewStack()
        self.view_stack.set_vexpand(True)
        main_box.append(self.view_stack)

        self.view_stack.add_named(self.setup_page_drive(), "page_drive")
        self.view_stack.add_named(self.setup_page_iso(), "page_iso")
        self.view_stack.add_named(self.setup_page_summary(), "page_summary")
        self.view_stack.add_named(self.setup_page_flash(), "page_flash")

        # Navigation wizard panel
        self.nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.nav_box.set_margin_start(15)
        self.nav_box.set_margin_end(15)
        self.nav_box.set_margin_bottom(15)
        self.nav_box.set_margin_top(10)
        main_box.append(self.nav_box)

        self.btn_back = Gtk.Button(label=T["btn_back"])
        self.btn_back.connect("clicked", self.go_back)
        self.nav_box.append(self.btn_back)

        self.dots_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.CENTER, hexpand=True)
        self.dots_box.set_valign(Gtk.Align.CENTER)
        self.dots = []
        for i in range(3):
            dot = Gtk.Box()
            dot.set_size_request(10, 10)
            dot.set_valign(Gtk.Align.CENTER)
            dot.set_halign(Gtk.Align.CENTER)
            dot.add_css_class("wizard-dot")
            self.dots.append(dot)
            self.dots_box.append(dot)
        self.nav_box.append(self.dots_box)

        self.btn_next = Gtk.Button(label=T["btn_next"])
        self.btn_next.add_css_class("suggested-action")
        self.btn_next.connect("clicked", self.go_next)
        self.nav_box.append(self.btn_next)

        self.update_ui_state()

        self.last_drives = []
        GLib.timeout_add_seconds(2, self.auto_refresh_drives)
        
        self.apply_saved_theme()

    def apply_saved_theme(self):
        idx = APP_CONFIG.get("theme", 0)
        style_mgr = Adw.StyleManager.get_default()
        if idx == 1:
            style_mgr.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        elif idx == 2:
            style_mgr.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        else:
            style_mgr.set_color_scheme(Adw.ColorScheme.DEFAULT)

    # --- Pages ---

    def setup_page_drive(self):
        page = Adw.StatusPage(title=T["step_drive"], icon_name="drive-removable-media-symbolic")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15, halign=Gtk.Align.CENTER)
        page.set_child(box)

        self.drive_dropdown = Gtk.DropDown()
        self.drive_dropdown.connect("notify::selected", lambda *_: self.update_ui_state())
        box.append(self.drive_dropdown)
        return page

    def setup_page_iso(self):
        page = Adw.StatusPage(title=T["step_iso"], icon_name="media-optical-symbolic")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15, halign=Gtk.Align.CENTER)
        page.set_child(box)

        self.iso_btn = Gtk.Button(label=T["select_iso"])
        self.iso_btn.connect("clicked", self.on_select_iso)
        box.append(self.iso_btn)

        self.iso_label = Gtk.Label(label=T["iso_not_selected"])
        self.iso_label.add_css_class("dim-label")
        box.append(self.iso_label)

        box.append(Gtk.Label(label=T["os_type"]))
        self.os_dropdown = Gtk.DropDown.new_from_strings([T["os_win"], T["os_lin"], T["os_other"]])
        self.os_dropdown.set_selected(2)
        self.os_dropdown.set_size_request(280, -1)
        box.append(self.os_dropdown)

        self.scheme_label = Gtk.Label(label=T["partition_scheme"])
        self.scheme_label.set_visible(False) 
        box.append(self.scheme_label)
        
        self.scheme_dropdown = Gtk.DropDown.new_from_strings([T["scheme_gpt"], T["scheme_mbr"]])
        self.scheme_dropdown.set_visible(False) 
        self.scheme_dropdown.set_size_request(280, -1)
        box.append(self.scheme_dropdown)

        self.os_dropdown.connect("notify::selected", self.on_os_changed)

        return page

    def on_os_changed(self, dropdown, param):
        is_windows = dropdown.get_selected() == 0
        self.scheme_label.set_visible(is_windows)
        self.scheme_dropdown.set_visible(is_windows)

    def setup_page_summary(self):
        page = Adw.StatusPage(title=T["step_summary"], icon_name="emblem-system-symbolic")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, halign=Gtk.Align.CENTER)
        box.set_size_request(400, -1)
        page.set_child(box)

        pref_group = Adw.PreferencesGroup()
        box.append(pref_group)

        self.sum_drive = Adw.ActionRow(title=T["summary_drive"])
        self.sum_iso = Adw.ActionRow(title=T["summary_iso"])
        self.sum_os = Adw.ActionRow(title=T["summary_os"])
        self.sum_scheme = Adw.ActionRow(title=T["summary_scheme"])
        
        pref_group.add(self.sum_drive)
        pref_group.add(self.sum_iso)
        pref_group.add(self.sum_os)
        pref_group.add(self.sum_scheme)
        return page

    def setup_page_flash(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_start(15)
        box.set_margin_end(15)
        box.set_margin_bottom(15)
        box.set_margin_top(15)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.add_css_class("view")
        self.console_buffer = Gtk.TextBuffer()
        self.console_buffer.set_text(T["console_ready"])
        self.console_view = Gtk.TextView(buffer=self.console_buffer, editable=False, monospace=True)
        self.console_view.set_margin_start(10)
        self.console_view.set_margin_top(10)
        self.console_view.set_margin_bottom(10)
        scroll.set_child(self.console_view)
        box.append(scroll)

        # progressbar
        self.flash_progress = Gtk.ProgressBar()
        self.flash_progress.set_show_text(True)
        box.append(self.flash_progress)

        # readyy btn
        self.btn_done = Gtk.Button(label=T["btn_done"])
        self.btn_done.add_css_class("suggested-action")
        self.btn_done.set_visible(False)
        self.btn_done.connect("clicked", lambda _: self.close())
        box.append(self.btn_done)

        return box

    # --- Navigations ---

    def go_next(self, btn):
        if self.current_step == 2:
            self.request_start()
            return
            
        if self.current_step < 2:
            self.current_step += 1
            self.update_ui_state()

    def go_back(self, btn):
        if self.current_step > 0:
            self.current_step -= 1
            self.update_ui_state()

    def update_ui_state(self):
        self.view_stack.set_visible_child_name(self.pages[self.current_step])
        
        for i, dot in enumerate(self.dots):
            if i == self.current_step:
                dot.add_css_class("active")
            else:
                dot.remove_css_class("active")
        
        self.btn_back.set_sensitive(self.current_step > 0)
        
        if self.current_step == 0:
            self.btn_next.set_label(T["btn_next"])
            sel = self.drive_dropdown.get_selected_item()
            is_valid_drive = sel is not None and T["no_drives"] not in sel.get_string()
            self.btn_next.set_sensitive(is_valid_drive)
            
        elif self.current_step == 1:
            self.btn_next.set_label(T["btn_next"])
            self.btn_next.set_sensitive(self.iso_path is not None)
            
        elif self.current_step == 2:
            self.btn_next.set_label(T["btn_start"])
            self.btn_next.set_sensitive(True)
            self.update_summary_data()

    def update_summary_data(self):
        sel_drive = self.drive_dropdown.get_selected_item().get_string()
        self.selected_dev = f"/dev/{sel_drive.split()[0]}"
        
        self.sum_drive.set_subtitle(sel_drive)
        self.sum_iso.set_subtitle(os.path.basename(self.iso_path))
        
        os_idx = self.os_dropdown.get_selected()
        os_text = T["os_win"] if os_idx == 0 else T["os_lin"] if os_idx == 1 else T["os_other"]
        self.sum_os.set_subtitle(os_text)
        
        if os_idx == 0:
            scheme_idx = self.scheme_dropdown.get_selected()
            scheme_text = T["scheme_gpt"] if scheme_idx == 0 else T["scheme_mbr"]
            self.sum_scheme.set_subtitle(scheme_text)
        else:
            self.sum_scheme.set_subtitle("Isohybrid (dd block copy)")

    # --- Confirmation and start ---

    def request_start(self):
        if "nvme" in self.selected_dev:
            self.append_log(T["nvme_lock"])
            return
            
        # deps check
        missing = check_dependencies()
        if missing:
            self.prompt_install_dependencies(missing)
        else:
            self.show_warn1_dialog()

    def prompt_install_dependencies(self, missing):
        base, distro_name = get_distro_info()
        deps_str = ", ".join(missing)
        self.install_cmd = get_install_cmd(missing)
        
        if not self.install_cmd:
            dialog = Adw.AlertDialog(
                heading=T["dep_missing_title"],
                body=T["dep_unsupported"].format(deps=deps_str)
            )
            dialog.set_body_use_markup(True)
            dialog.add_response("ok", T["btn_close_dialog"])
            dialog.choose(self, None, lambda *_: None)
            return

        body = T["dep_missing_body"].format(deps=deps_str, distro=distro_name)
        dialog = Adw.AlertDialog(heading=T["dep_missing_title"], body=body)
        dialog.set_body_use_markup(True)
        dialog.add_response("cancel", T["btn_cancel"])
        dialog.add_response("install", T["btn_install"])
        dialog.set_response_appearance("install", Adw.ResponseAppearance.SUGGESTED)
        dialog.choose(self, None, self.on_install_deps_response)

    def on_install_deps_response(self, dialog, result):
        resp = dialog.choose_finish(result)
        if resp == "install":
            self.btn_next.set_sensitive(False)
            threading.Thread(target=self.install_deps_worker, daemon=True).start()

    def install_deps_worker(self):
        # install_cmd is a list of argv lists, run without shell
        try:
            for cmd in self.install_cmd:
                argv = [resolve_bin(cmd[0]), *cmd[1:]]
                proc = subprocess.run(argv, text=True, capture_output=True, check=False)  # nosec B603
                if proc.returncode != 0:
                    GLib.idle_add(
                        self.show_deps_error,
                        f"{T['err_code']} {proc.returncode}:\n{proc.stderr}",
                    )
                    return
            GLib.idle_add(self.on_deps_installed_success)
        except OSError as e:
            GLib.idle_add(self.show_deps_error, str(e))

    def on_deps_installed_success(self):
        self.btn_next.set_sensitive(True)
        self.show_warn1_dialog()
        
    def show_deps_error(self, err_text):
        self.btn_next.set_sensitive(True)
        dialog = Adw.AlertDialog(heading=T["err_crit"], body=err_text[:500])
        dialog.add_response("ok", T["btn_close_dialog"])
        dialog.choose(self, None, lambda *_: None)

    def show_warn1_dialog(self):
        dialog = Adw.AlertDialog(
            heading=T["warn1_title"],
            body=T["warn1_body"].format(dev=self.selected_dev)
        )
        dialog.set_body_use_markup(True)
        dialog.add_response("cancel", T["btn_cancel"])
        dialog.add_response("yes", T["btn_yes"])
        dialog.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.choose(self, None, self.on_warn1_response)

    def on_warn1_response(self, dialog, result):
        response = dialog.choose_finish(result)
        if response == "yes":
            dialog2 = Adw.AlertDialog(
                heading=T["warn2_title"],
                body=T["warn2_body"]
            )
            dialog2.add_response("cancel", T["btn_cancel"])
            dialog2.add_response("yes", T["btn_yes"])
            dialog2.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog2.choose(self, None, self.on_warn2_response)

    def on_warn2_response(self, dialog, result):
        response = dialog.choose_finish(result)
        if response == "yes":
            self.current_step = 3
            self.nav_box.set_visible(False)
            self.view_stack.set_visible_child_name("page_flash")
            self.flash_progress.set_fraction(0.0)
            self.is_flashing = True
            threading.Thread(target=self.worker_thread, args=(self.iso_path, self.selected_dev), daemon=True).start()

    # --- Window closing ---

    def on_close_request(self, window):
        if self.is_flashing:
            dialog = Adw.AlertDialog(heading=T["interrupt_title"], body=T["interrupt_body"])
            dialog.add_response("no", T["btn_cancel"])
            dialog.add_response("yes", T["interrupt_yes"])
            dialog.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.choose(self, None, self.on_interrupt_response)
            return True
        return False

    def on_interrupt_response(self, dialog, result):
        response = dialog.choose_finish(result)
        if response == "yes":
            self.kill_worker()
            self.show_interrupted_error()

    def kill_worker(self):
        self.is_flashing = False
        # kill the root process by its tag
        subprocess.run(  # nosec B603
            [resolve_bin('pkexec'), 'pkill', '-f', WORKER_TAG],
            stderr=subprocess.DEVNULL, check=False,
        )
        if self.proc:
            try:
                self.proc.kill()
            except (ProcessLookupError, OSError):
                pass

    def show_interrupted_error(self):
        err_dialog = Adw.AlertDialog(heading="Ошибка", body=T["err_interrupted"])
        err_dialog.add_response("close", T["btn_close_app"])
        err_dialog.add_response("restart", T["btn_restart"])
        err_dialog.set_response_appearance("close", Adw.ResponseAppearance.DESTRUCTIVE)
        err_dialog.choose(self, None, self.on_error_response)

    def on_error_response(self, dialog, result):
        resp = dialog.choose_finish(result)
        if resp == "close":
            self.close()
        elif resp == "restart":
            self.current_step = 0
            self.flash_progress.set_fraction(0)
            self.flash_progress.set_visible(True)
            self.btn_done.set_visible(False)
            self.nav_box.set_visible(True)
            self.console_buffer.set_text(T["console_ready"])
            self.update_ui_state()

    # --- Methods ---

    def show_about(self, action=None, param=None):
        dialog = Adw.AboutDialog(
            application_name=T["title"],
            application_icon="lufux",
            version=APP_VERSION,
            developer_name="Advnirr",
            issue_url=GITHUB_URL,
            website=WEB_URL,
        )
        dialog.present(self)
              
    def show_settings(self, action=None, param=None):
        pref_dialog = Adw.PreferencesDialog(title=T["settings"])
        
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup()
        page.add(group)
        pref_dialog.add(page)

        # themes: dark and light
        theme_row = Adw.ComboRow(title=T.get("theme", "Тема"))
        theme_model = Gtk.StringList.new([T.get("theme_sys", "Системная"), T.get("theme_light", "Светлая"), T.get("theme_dark", "Тёмная")])
        theme_row.set_model(theme_model)
        
        theme_row.set_selected(APP_CONFIG.get("theme", 0))
        theme_row.connect("notify::selected", self.on_theme_changed)
        group.add(theme_row)

        # langs/locals
        lang_row = Adw.ComboRow(title=T.get("language", "Язык"))
        lang_model = Gtk.StringList.new(["English", "Русский"])
        lang_row.set_model(lang_model)
        
        current_lang = APP_CONFIG.get("lang", os.environ.get('LANG', ''))
        lang_row.set_selected(1 if current_lang.startswith('ru') else 0)
        lang_row.connect("notify::selected", self.on_lang_changed)
        group.add(lang_row)

        pref_dialog.present(self)

    def on_theme_changed(self, combo, param):
        idx = combo.get_selected()
        APP_CONFIG["theme"] = idx
        save_config(APP_CONFIG)
        self.apply_saved_theme()

    def on_lang_changed(self, combo, param):
        idx = combo.get_selected()
        new_lang = 'ru_RU.UTF-8' if idx == 1 else 'en_US.UTF-8'
        
        if APP_CONFIG.get("lang") != new_lang:
            APP_CONFIG["lang"] = new_lang
            save_config(APP_CONFIG)

        if self.is_flashing:
            dialog = Adw.AlertDialog(
                heading=T["lang_restart_title"],
                body=T["lang_restart_body"]
            )
            dialog.add_response("ok", T.get("btn_close_dialog", "OK"))
            dialog.choose(self, None, lambda *args: None)
        else:
            os.environ['LANG'] = new_lang
            # restart to apply the new language
            os.execv(sys.executable, [sys.executable] + sys.argv)  # nosec B606

    def auto_refresh_drives(self):
        if self.current_step == 0:
            new_drives = self.get_usb_drives()
            if new_drives != self.last_drives:
                self.last_drives = new_drives
                self.drive_dropdown.set_model(Gtk.StringList.new(new_drives))
                self.update_ui_state()
        return True

    def get_usb_drives(self):
        try:
            res = subprocess.run(  # nosec B603
                [resolve_bin('lsblk'), '-I', '8', '-d', '-n', '-o', 'NAME,SIZE,MODEL'],
                capture_output=True, text=True, check=True,
            )
            drives = [line.strip() for line in res.stdout.split('\n') if line.strip()]
            return drives if drives else [T["no_drives"]]
        except (subprocess.SubprocessError, OSError):
            return [T["no_drives"]]

    def on_select_iso(self, btn):
        dialog = Gtk.FileDialog.new()
        dialog.set_title(T["select_iso"])
        f_iso = Gtk.FileFilter()
        f_iso.set_name("ISO Images")
        f_iso.add_pattern("*.iso")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f_iso)
        dialog.open(self, None, self.on_file_selected)

    def on_file_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                self.iso_path = file.get_path()
                self.iso_label.set_label(os.path.basename(self.iso_path))
                self.analyze_iso()
                self.update_ui_state()
        except GLib.Error:
            pass

    def analyze_iso(self):
        try:
            res = subprocess.run(  # nosec B603
                [resolve_bin('bsdtar'), '-tf', self.iso_path],
                capture_output=True, text=True, timeout=3, check=False,
            )
            files = res.stdout.lower()
            
            if any(x in files for x in ['sources/install.wim', 'sources/install.esd', 'sources/boot.wim', 'bootmgr']):
                self.os_dropdown.set_selected(0)
            elif any(x in files for x in ['isolinux', 'casper', 'arch/', 'vmlinuz', 'live/', 'boot/grub/']):
                self.os_dropdown.set_selected(1)
            else:
                self.os_dropdown.set_selected(2)
        except (subprocess.SubprocessError, OSError):
            self.os_dropdown.set_selected(2)

    def append_log(self, msg):
        end_iter = self.console_buffer.get_end_iter()
        self.console_buffer.insert(end_iter, msg + "\n")
        mark = self.console_buffer.create_mark(None, self.console_buffer.get_end_iter(), False)
        self.console_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)

    # --- Worker ---

    def worker_thread(self, iso, dev):
        os_idx = self.os_dropdown.get_selected()
        scheme_idx = self.scheme_dropdown.get_selected()
        scheme = "gpt" if scheme_idx == 0 else "mbr"

        if os_idx == 0:
            script = get_windows_script(scheme)
        else:
            script = get_linux_script()

        # run via bash -c, pass iso/dev/scheme as $1/$2/$3 instead of a temp
        # file, so the iso name can't be interpreted by a shell. WORKER_TAG is
        # argv[0] so kill_worker can find the root process.
        try:
            self.proc = subprocess.Popen(  # nosec B603
                [resolve_bin('pkexec'), 'bash', '-c', script, WORKER_TAG, iso, dev, scheme],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )

            for line in iter(self.proc.stdout.readline, ''):
                if not self.is_flashing:
                    break

                line = line.strip()
                if line.startswith("STATUS:"):
                    msg = line.replace("STATUS:", "").strip()
                    if msg == "DONE":
                        GLib.idle_add(self.on_flash_success)
                    else:
                        GLib.idle_add(self.append_log, f"[*] {msg}")
                else:
                    match = re.search(r'([\d\.]+)%', line)
                    if match:
                        pct = float(match.group(1)) / 100.0
                        GLib.idle_add(self.update_flash_progress, pct)
                    elif line:
                        GLib.idle_add(self.append_log, f"> {line}")

            self.proc.wait()

            if self.is_flashing:
                if self.proc.returncode == 126:
                    GLib.idle_add(self.append_log, T["canceled"])
                    self.is_flashing = False
                elif self.proc.returncode != 0:
                    GLib.idle_add(self.append_log, f"{T['err_crit']} ({T['err_code']} {self.proc.returncode})")
                    self.is_flashing = False
        except OSError as e:
            GLib.idle_add(self.append_log, f"{T['err_crit']} {e}")
            self.is_flashing = False

    def on_flash_success(self):
        self.is_flashing = False
        self.append_log(T["done"])
        self.flash_progress.set_fraction(1.0)
        
        self.flash_progress.set_visible(False)
        self.btn_done.set_visible(True)

    def update_flash_progress(self, fraction):
        self.flash_progress.set_fraction(fraction)


class LufuxApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.mikhail.lufux")
        self.connect("activate", self.on_activate)

    def on_activate(self, app):
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
        .wizard-dot {
            border-radius: 50%;
            background-color: alpha(currentColor, 0.2);
            transition: background-color 0.2s ease-in-out;
        }
        .wizard-dot.active {
            background-color: @accent_bg_color;
        }
        """)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        win = LufuxWindow(application=app)
        win.present()

if __name__ == '__main__':
    app = LufuxApp()
    app.run(None)
