import gi
import os
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

# What a drive has to manage before Windows To Go is worth deploying onto it.
# The random figure is the one that decides: a stick doing 8 MB/s sequentially
# and a few dozen 4 KiB writes a second produced a system that spent 3.5 hours
# on its first boot and reported a 5 842 183 ms average disk response.
WTG_MIN_SEQ_MBPS = 15.0
WTG_MIN_RAND_IOPS = 100

# resolving through $PATH would be no better than handing subprocess a bare
# name, since $PATH is user-controlled; only these locations are trusted.
TRUSTED_BIN_DIRS = ("/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin", "/usr/local/sbin")
_BIN_CACHE = {}

def resolve_bin(name):
    # cached: auto_refresh_drives resolves lsblk every 2 seconds for the whole
    # lifetime of the app. Only hits are cached, so a binary installed by the
    # dependency installer is still picked up on the next call.
    path = _BIN_CACHE.get(name)
    if path is None:
        for directory in TRUSTED_BIN_DIRS:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                path = candidate
                _BIN_CACHE[name] = path
                break
    return path or name

def list_iso_editions(iso_path):
    """[(image index, name)] for the Windows images in an ISO, [] if unreadable.

    Windows To Go deploys one image out of install.wim, and a retail ISO carries
    several - Home, Pro, Education. Reading that list means reading the file,
    and a current Windows ISO keeps its tree in UDF, so it has to be mounted;
    udisksctl does that as the plain user, no root and no password. Where udisks
    is missing the caller falls back to image 1, which is what Lufux deployed
    unconditionally before.
    """
    dev = None
    try:
        setup = subprocess.run(  # nosec B603
            [resolve_bin('udisksctl'), 'loop-setup', '-r', '-f', iso_path,
             '--no-user-interaction'],
            text=True, capture_output=True, check=False, timeout=30)
        match = re.search(r'(/dev/loop\d+)', setup.stdout)
        if not match:
            return []
        dev = match.group(1)
        subprocess.run(  # nosec B603
            [resolve_bin('udisksctl'), 'mount', '-b', dev, '--no-user-interaction'],
            text=True, capture_output=True, check=False, timeout=60)
        # udisksctl announces the mount point in the user's own language;
        # findmnt answers the same question in a fixed format
        target = subprocess.run(  # nosec B603
            [resolve_bin('findmnt'), '-rno', 'TARGET', dev],
            text=True, capture_output=True, check=False, timeout=10).stdout.split("\n")
        if not target[0]:
            return []
        for name in ('install.wim', 'install.esd'):
            image = os.path.join(target[0], 'sources', name)
            if os.path.exists(image):
                break
        else:
            return []
        info = subprocess.run(  # nosec B603
            [resolve_bin('wimlib-imagex'), 'info', image],
            text=True, capture_output=True, check=False, timeout=120).stdout

        editions = []
        index = None
        for line in info.splitlines():
            # "Display Name:" is a different key and must not be picked up here
            if line.startswith("Index:"):
                index = line.split(":", 1)[1].strip()
            elif line.startswith("Name:") and index is not None:
                editions.append((int(index), line.split(":", 1)[1].strip()))
                index = None
        return editions
    # a listing that fails costs the edition choice, never the flash
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    finally:
        if dev:
            for args in (('unmount', '-b', dev), ('loop-delete', '-b', dev)):
                try:
                    subprocess.run(  # nosec B603
                        [resolve_bin('udisksctl'), *args, '--no-user-interaction'],
                        capture_output=True, check=False, timeout=30)
                except (OSError, subprocess.SubprocessError):
                    pass


def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        # ValueError covers both JSONDecodeError and the UnicodeDecodeError a
        # non-UTF-8 config raises; this runs at import, so escaping it means
        # the app dies with a traceback and no window
        return dict(DEFAULT_CONFIG)

    cfg = dict(DEFAULT_CONFIG)
    if not isinstance(data, dict):
        return cfg
    # values are used as an env var and a theme index, so type-check them too
    if isinstance(data.get("lang"), str):
        cfg["lang"] = data["lang"]
    if isinstance(data.get("theme"), int) and data["theme"] in (0, 1, 2):
        cfg["theme"] = int(data["theme"])
    return cfg

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
from windows_togo_logic import get_windows_togo_script
from universal_logic import get_linux_script
from deps_logic import check_dependencies, get_distro_info, get_install_cmd

# here I am
APP_VERSION = "1.3.6"
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
            "edition": "Редакция Windows:",
            "edition_reading": "Чтение образа...",
            "os_win": "Windows",
            "os_lin": "Linux / Isohybrid",
            "os_other": "Неизвестно / Другое",
            "partition_scheme": "Схема разделов (для Windows):",
            "scheme_gpt": "GPT (UEFI / FAT32)",
            "scheme_mbr": "MBR (Legacy BIOS / NTFS)",
            "wtg_mode": "Windows To Go (запускаемая Windows на USB)",
            "wtg_summary": "Windows To Go (GPT / UEFI)",
            "summary_drive": "Целевой накопитель",
            "summary_iso": "Выбранный образ",
            "summary_os": "Определенная система",
            "summary_scheme": "Схема разметки",
            "summary_edition": "Редакция",
            "nvme_lock": "Запись на NVMe заблокирована!",
            "warn1_title": "Внимание!",
            "warn1_body": "Все данные на накопителе\n<b>{dev}</b>\nбудут БЕЗВОЗВРАТНО УНИЧТОЖЕНЫ.\n\nПродолжить?",
            "warn2_title": "Последнее предупреждение",
            "warn2_body": "Вы абсолютно уверены? Это действие невозможно отменить.",
            "done": "Запись завершена успешно",
            "canceled": "Отменено пользователем",
            "err_crit": "Критическая ошибка:",
            "console_ready": "Инициализация... Ожидание старта.\n",
            "stale_title": "Остатки прошлой записи",
            "stale_body": "Прошлая запись не завершилась и оставила смонтированные каталоги. Они держат образ и loop-устройство занятыми. Убрать?",
            "stale_yes": "Убрать",
            "stale_no": "Оставить",
            "stale_done": "Остатки убраны",
            "stale_failed": "Не удалось убрать остатки",
            "interrupt_title": "Прервать прогресс записи?",
            "interrupt_body": "Процесс записи образа все еще идет. Вы уверены, что хотите прервать его? Это приведет к неработоспособности накопителя до повторного форматирования",
            "interrupt_yes": "Да, прервать",
            "err_interrupted": "Прервано пользователем",
            "stopping": "Остановка процесса записи...",
            "err_kill_failed": "Не удалось остановить процесс записи — он может всё ещё писать на накопитель. Не извлекайте его.",
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
            "speed_title": "Накопитель слишком медленный",
            "speed_body": (
                "Замер накопителя:\n"
                "• последовательная запись — <b>{seq} МБ/с</b>\n"
                "• случайная запись 4 КБ — <b>{iops} операций/с</b>\n\n"
                "Это мало, ориентир — {min_seq} МБ/с и {min_iops} операций/с. "
                "Windows будет работать с этого накопителя: на такой скорости "
                "она грузится часами и подвисает почти на любом действии.\n\n"
                "Запись займёт несколько часов в любом случае. Накопитель уже "
                "очищен, отмена оставит его пустым."
            ),
            "speed_ok": "Скорость накопителя: {seq} МБ/с, {iops} операций/с — достаточно",
            "speed_slow": "Скорость накопителя: {seq} МБ/с, {iops} операций/с — мало",
            "btn_continue_anyway": "Всё равно продолжить",
            "speed_canceled": "Запись отменена: накопитель слишком медленный",
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
        "edition": "Windows edition:",
        "edition_reading": "Reading the image...",
        "os_win": "Windows",
        "os_lin": "Linux / Isohybrid",
        "os_other": "Unknown / Other",
        "partition_scheme": "Partition Scheme (for Windows):",
        "scheme_gpt": "GPT (UEFI / FAT32)",
        "scheme_mbr": "MBR (Legacy BIOS / NTFS)",
        "wtg_mode": "Windows To Go (bootable Windows on USB)",
        "wtg_summary": "Windows To Go (GPT / UEFI)",
        "summary_drive": "Target Drive",
        "summary_iso": "Selected ISO",
        "summary_os": "Detected OS",
        "summary_scheme": "Partition Scheme",
        "summary_edition": "Edition",
        "nvme_lock": "NVMe writing is disabled!",
        "warn1_title": "Warning!",
        "warn1_body": "All data on drive\n<b>{dev}</b>\nwill be PERMANENTLY DESTROYED.\n\nContinue?",
        "warn2_title": "Final Warning",
        "warn2_body": "Are you absolutely sure? This action cannot be undone.",
        "done": "Flashing completed successfully",
        "canceled": "Canceled by user",
        "err_crit": "Critical Error:",
        "console_ready": "Initialization... Waiting to start.\n",
        "stale_title": "Leftovers from an earlier flash",
        "stale_body": "An earlier flash did not finish and left its mount points behind. They keep the ISO and a loop device busy. Clean them up?",
        "stale_yes": "Clean up",
        "stale_no": "Leave them",
        "stale_done": "Leftovers cleaned up",
        "stale_failed": "Could not clean up the leftovers",
        "interrupt_title": "Interrupt flashing progress?",
        "interrupt_body": "The image writing process is still ongoing. Are you sure you want to interrupt it? The drive will be unbootable.",
        "interrupt_yes": "Yes, interrupt",
        "err_interrupted": "Interrupted by user",
        "stopping": "Stopping the flashing process...",
        "err_kill_failed": "Could not stop the flashing process - it may still be writing to the drive. Do not unplug it.",
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
        "speed_title": "This drive is too slow",
        "speed_body": (
            "Measured on this drive:\n"
            "• sequential write — <b>{seq} MB/s</b>\n"
            "• random 4 KB write — <b>{iops} ops/s</b>\n\n"
            "That is low; the bar is {min_seq} MB/s and {min_iops} ops/s. "
            "Windows will be running off this drive, and at that speed it "
            "boots in hours and stalls on almost anything you do.\n\n"
            "Writing takes hours either way. The drive is already erased, so "
            "cancelling leaves it empty."
        ),
        "speed_ok": "Drive speed: {seq} MB/s, {iops} ops/s — good enough",
        "speed_slow": "Drive speed: {seq} MB/s, {iops} ops/s — too low",
        "btn_continue_anyway": "Continue anyway",
        "speed_canceled": "Flashing cancelled: the drive is too slow",
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
        # [(image index, name)] read out of the chosen ISO, empty until then
        self.editions = []
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
        # after the window is up, so the dialog has something to attach to
        GLib.idle_add(self.check_stale_leftovers)

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

        # Windows To Go: deploy a runnable Windows instead of installer media.
        # Forces GPT/UEFI, so the scheme selector is hidden while it is on.
        self.wtg_check = Gtk.CheckButton(label=T["wtg_mode"])
        self.wtg_check.set_visible(False)
        self.wtg_check.connect("toggled", self.on_wtg_toggled)
        box.append(self.wtg_check)

        # Which edition to deploy. Only Windows To Go picks a single image out
        # of the ISO; installer media copies the whole file either way.
        self.edition_label = Gtk.Label(label=T["edition"])
        self.edition_label.set_visible(False)
        box.append(self.edition_label)

        self.edition_dropdown = Gtk.DropDown.new_from_strings([T["edition_reading"]])
        self.edition_dropdown.set_visible(False)
        self.edition_dropdown.set_size_request(280, -1)
        box.append(self.edition_dropdown)

        self.os_dropdown.connect("notify::selected", self.on_os_changed)

        return page

    def on_os_changed(self, dropdown, param):
        is_windows = dropdown.get_selected() == 0
        self.wtg_check.set_visible(is_windows)
        wtg = is_windows and self.wtg_check.get_active()
        self.scheme_label.set_visible(is_windows and not wtg)
        self.scheme_dropdown.set_visible(is_windows and not wtg)
        self.update_edition_visible()

    def on_wtg_toggled(self, check):
        # Windows To Go is always GPT/UEFI, so hide the scheme picker
        wtg = check.get_active()
        self.scheme_label.set_visible(not wtg)
        self.scheme_dropdown.set_visible(not wtg)
        self.update_edition_visible()

    def update_edition_visible(self):
        # Nothing to choose from a single-edition image, and nothing to choose
        # at all until the ISO has been read
        wtg = self.os_dropdown.get_selected() == 0 and self.wtg_check.get_active()
        show = wtg and len(self.editions) > 1
        self.edition_label.set_visible(show)
        self.edition_dropdown.set_visible(show)

    def selected_img_index(self):
        """The WIM image to deploy: the one picked, or the first if unknown."""
        pos = self.edition_dropdown.get_selected()
        if self.editions and 0 <= pos < len(self.editions):
            return self.editions[pos][0]
        return 1

    def read_editions(self, iso):
        editions = list_iso_editions(iso)
        GLib.idle_add(self.apply_editions, iso, editions)

    def apply_editions(self, iso, editions):
        # a second ISO can be chosen while the first one is still being read
        if iso != self.iso_path:
            return
        self.editions = editions
        names = [name for _, name in editions] or [T["edition_reading"]]
        self.edition_dropdown.set_model(Gtk.StringList.new(names))
        self.edition_dropdown.set_selected(0)
        self.update_edition_visible()

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
        self.sum_edition = Adw.ActionRow(title=T["summary_edition"])
        self.sum_edition.set_visible(False)

        pref_group.add(self.sum_drive)
        pref_group.add(self.sum_iso)
        pref_group.add(self.sum_os)
        pref_group.add(self.sum_scheme)
        pref_group.add(self.sum_edition)
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
        
        # a single-edition image never shows the picker, so the summary is the
        # only place that says which Windows is about to be written
        wtg = os_idx == 0 and self.wtg_check.get_active()
        self.sum_edition.set_visible(wtg and bool(self.editions))
        if wtg and self.editions:
            self.sum_edition.set_subtitle(
                dict(self.editions).get(self.selected_img_index(), ""))

        if wtg:
            self.sum_scheme.set_subtitle(T["wtg_summary"])
        elif os_idx == 0:
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
        # background thread: an escaping exception would leave btn_next
        # disabled with no dialog and no way out but restarting the app
        except Exception as e:  # noqa: BLE001
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
            self.update_flash_progress(0.0)
            self.is_flashing = True
            # read the dropdowns here, on the main thread: GTK4 forbids widget
            # access from anywhere else
            os_idx = self.os_dropdown.get_selected()
            scheme = "gpt" if self.scheme_dropdown.get_selected() == 0 else "mbr"
            wtg = self.wtg_check.get_active()
            img_index = self.selected_img_index()
            threading.Thread(
                target=self.worker_thread,
                args=(self.iso_path, self.selected_dev, os_idx, scheme, wtg, img_index),
                daemon=True,
            ).start()

    # --- Leftovers from an earlier flash ---

    # The scripts mount through mktemp -d, so every leftover has one of these
    # prefixes followed by mktemp's six characters. Cleanup runs as root, so
    # match the whole name and never a caller-supplied string.
    STALE_MOUNT_RE = re.compile(r"^/tmp/lufux_(?:iso|usb|win|efi)\.[A-Za-z0-9]{6}$")

    @staticmethod
    def find_stale_mounts():
        """Mount points left behind by a flash that did not finish."""
        found = []
        try:
            with open("/proc/self/mountinfo", encoding="utf-8") as f:
                for line in f:
                    fields = line.split(" ")
                    if len(fields) < 5:
                        continue
                    # mountinfo escapes spaces and the like as octal
                    target = fields[4].encode().decode("unicode_escape")
                    if LufuxWindow.STALE_MOUNT_RE.match(target):
                        found.append(target)
        except OSError:
            return []
        return sorted(set(found))

    def worker_running(self):
        try:
            return subprocess.run(  # nosec B603
                [resolve_bin('pgrep'), '-f', WORKER_TAG],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False,
            ).returncode == 0
        except OSError:
            return False

    def check_stale_leftovers(self):
        # a flash of our own still running owns these; only offer to clean up
        # what nothing is using
        if self.worker_running():
            return False
        self.stale_mounts = self.find_stale_mounts()
        if not self.stale_mounts:
            return False
        body = T["stale_body"] + "\n\n" + "\n".join(self.stale_mounts)
        dialog = Adw.AlertDialog(heading=T["stale_title"], body=body)
        dialog.add_response("no", T["stale_no"])
        dialog.add_response("yes", T["stale_yes"])
        dialog.set_response_appearance("yes", Adw.ResponseAppearance.SUGGESTED)
        dialog.choose(self, None, self.on_stale_response)
        return False

    def on_stale_response(self, dialog, result):
        if dialog.choose_finish(result) != "yes":
            return
        # pkexec pops a polkit dialog, which would freeze the GTK main loop
        threading.Thread(target=self.clean_stale_thread,
                         args=(list(self.stale_mounts),), daemon=True).start()

    def clean_stale_thread(self, mounts):
        # re-validate here: this list is about to be handed to root
        mounts = [m for m in mounts if self.STALE_MOUNT_RE.match(m)]
        ok = False
        if mounts:
            # umount frees the loop device with it, mount(8) having set autoclear
            # plain umount first: a lazy detach would also hide a mount that
            # something is legitimately still using
            script = ('for m in "$@"; do umount "$m" 2>/dev/null || '
                      'umount -l "$m" 2>/dev/null; rmdir "$m" 2>/dev/null; done')
            try:
                ok = subprocess.run(  # nosec B603
                    [resolve_bin('pkexec'), 'bash', '-c', script, 'lufux-cleanup', *mounts],
                    stderr=subprocess.DEVNULL, check=False,
                ).returncode == 0
            except OSError:
                ok = False
        left = self.find_stale_mounts()
        GLib.idle_add(self.show_stale_result, ok and not left)

    def show_stale_result(self, ok):
        dialog = Adw.AlertDialog(heading=T["stale_done"] if ok else T["stale_failed"], body="")
        dialog.add_response("ok", T["btn_close_dialog"])
        dialog.choose(self, None, lambda d, r: d.choose_finish(r))
        return False

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

    def kill_worker(self):
        self.is_flashing = False
        proc = self.proc
        pgid = None
        if proc:
            try:
                pgid = os.getpgid(proc.pid)
            except OSError:
                pgid = None
        # pkexec pops a polkit dialog, which would freeze the GTK main loop for
        # as long as it is up, so do the kill on a thread and report after
        self.append_log(T["stopping"])
        threading.Thread(target=self.kill_worker_thread, args=(proc, pgid), daemon=True).start()

    def kill_worker_thread(self, proc, pgid):
        # WORKER_TAG only ever appears in the argv of the root bash, never in
        # the argv of the dd/rsync/wimlib it spawns, so matching on it leaves
        # them reparented and still writing to the device. The worker runs in
        # its own session, so killing the group takes the children with it.
        argv = [resolve_bin('pkexec'), 'pkill']
        argv += ['-g', str(pgid)] if pgid is not None else ['-f', WORKER_TAG]
        try:
            code = subprocess.run(  # nosec B603
                argv, stderr=subprocess.DEVNULL, check=False,
            ).returncode
        except OSError:
            code = -1

        # pkill: 0 = signalled, 1 = nothing matched (already gone).
        # pkexec: 126 = authentication dismissed or denied, 127 = failed to run.
        killed = code in (0, 1)

        if proc:
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                pass

        GLib.idle_add(self.show_interrupted_error, killed)

    def show_interrupted_error(self, killed=True):
        body = T["err_interrupted"] if killed else T["err_kill_failed"]
        err_dialog = Adw.AlertDialog(heading=T["err_crit"], body=body)
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
            self.update_flash_progress(0.0)
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
                [resolve_bin('lsblk'), '-I', '8', '-d', '-n', '-o', 'NAME,RM,TRAN,SIZE,MODEL'],
                capture_output=True, text=True, check=True,
            )
            # major 8 is every SCSI/SATA disk, so without this filter the
            # internal system drive is offered up for wiping
            drives = []
            for line in res.stdout.split('\n'):
                fields = line.split(None, 4)
                if len(fields) < 4:
                    continue
                name, removable, transport, size = fields[:4]
                model = fields[4].strip() if len(fields) > 4 else ""
                if removable != "1" and transport != "usb":
                    continue
                drives.append(" ".join(x for x in (name, size, model) if x))
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
        dialog.set_filters(filters)
        dialog.set_default_filter(f_iso)
        dialog.open(self, None, self.on_file_selected)

    def on_file_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                self.iso_path = file.get_path()
                self.iso_label.set_label(os.path.basename(self.iso_path))
                self.analyze_iso()
                self.editions = []
                self.update_edition_visible()
                threading.Thread(target=self.read_editions,
                                 args=(self.iso_path,), daemon=True).start()
                self.update_ui_state()
        except GLib.Error:
            pass

    # A current Windows ISO keeps its real tree in a UDF filesystem and leaves
    # only a README on the ISO9660 side, and libarchive cannot read UDF at all -
    # so listing one with bsdtar returned two entries and every Windows image
    # was detected as "Other". Match the raw image instead. ISO9660 records hold
    # names as plain bytes and UDF holds them as UTF-16BE, and UDF stores each
    # path component in its own record, so the markers are single components.
    ISO_WINDOWS = ('install.wim', 'install.esd', 'boot.wim', 'bootmgr.efi')
    ISO_LINUX = ('isolinux', 'casper', 'vmlinuz', 'initrd.img', 'grub.cfg')
    # Names live in the volume metadata, which sits near the front of the image
    # (630 KB in on the ISO this was built against). A match usually lands in
    # the first chunk; this bound is what an unrecognised image costs.
    ISO_SCAN = 64 << 20
    ISO_CHUNK = 4 << 20

    @staticmethod
    def _iso_views(buf):
        """The chunk as lowercased text, in each encoding a name can be in.

        UTF-16BE is decoded at both alignments: nothing promises the records
        begin on an even offset within the chunk.
        """
        yield buf.decode('latin-1').lower()
        for start in (0, 1):
            body = buf[start:]
            yield body[:len(body) & ~1].decode('utf-16-be', 'ignore').lower()

    def _iso_has(self, markers):
        try:
            with open(self.iso_path, 'rb') as f:
                carry = b''
                read = 0
                while read < self.ISO_SCAN:
                    buf = f.read(self.ISO_CHUNK)
                    if not buf:
                        break
                    read += len(buf)
                    window = carry + buf
                    for text in self._iso_views(window):
                        if any(m in text for m in markers):
                            return True
                    # a name can straddle two chunks
                    carry = window[-64:]
        except OSError:
            return False
        return False

    def analyze_iso(self):
        if self._iso_has(self.ISO_WINDOWS):
            self.os_dropdown.set_selected(0)
        elif self._iso_has(self.ISO_LINUX):
            self.os_dropdown.set_selected(1)
        else:
            self.os_dropdown.set_selected(2)

    def append_log(self, msg):
        end_iter = self.console_buffer.get_end_iter()
        self.console_buffer.insert(end_iter, msg + "\n")
        mark = self.console_buffer.create_mark(None, self.console_buffer.get_end_iter(), False)
        self.console_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)

    # --- Worker ---

    def worker_thread(self, iso, dev, os_idx, scheme, wtg, img_index=1):
        if os_idx == 0 and wtg:
            script = get_windows_togo_script(img_index)
        elif os_idx == 0:
            script = get_windows_script(scheme)
        else:
            script = get_linux_script()

        # run via bash -c, pass iso/dev/scheme as $1/$2/$3 instead of a temp
        # file, so the iso name can't be interpreted by a shell. WORKER_TAG is
        # argv[0] so kill_worker can find the root process.
        try:
            self.proc = subprocess.Popen(  # nosec B603
                [resolve_bin('pkexec'), 'bash', '-c', script, WORKER_TAG, iso, dev, scheme],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True,
                start_new_session=True,
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
                        # each command counts its own phase from zero, so drop
                        # the previous one's percentage here: otherwise mkntfs
                        # finishing at 100% leaves the bar full for the twenty
                        # minutes before wimlib prints a percentage of its own
                        GLib.idle_add(self.update_flash_progress, 0.0, msg)
                        GLib.idle_add(self.append_log, f"[*] {msg}")
                elif line.startswith("SPEEDTEST:"):
                    # the worker is now blocked reading its stdin: it deploys
                    # or gives up on whatever answer goes back
                    GLib.idle_add(self.on_speedtest, line)
                else:
                    # a loose [\d.]+ also matches "1.2.3" out of a version
                    # string, and float() would then raise inside this thread
                    match = re.search(r'(\d+(?:\.\d+)?)%', line)
                    if match:
                        pct = float(match.group(1)) / 100.0
                        # percentage lines never reach the log, so on a long
                        # deployment the bar is the only thing moving; label it
                        # with what is being counted ("Extracting file data:
                        # 3 GiB of 11 GiB") rather than a bare number
                        GLib.idle_add(self.update_flash_progress, pct,
                                      line.split(" (")[0].strip() or None)
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
        # background thread: anything escaping here freezes the GUI at the
        # last reported percentage with is_flashing still True
        except Exception as e:  # noqa: BLE001
            GLib.idle_add(self.append_log, f"{T['err_crit']} {e}")
            self.is_flashing = False

    # --- Drive speed gate (Windows To Go only) ---

    def answer_speedtest(self, answer):
        """Unblock the worker's `read`. Runs on the main thread, as does the
        dialog that calls it, so the two cannot answer twice."""
        try:
            self.proc.stdin.write(answer + "\n")
            self.proc.stdin.flush()
        # the worker has a timeout on that read and dies on its own, so a
        # worker that is already gone needs nothing more from us here
        except (OSError, ValueError, AttributeError):
            pass

    def on_speedtest(self, line):
        try:
            _, seq_s, iops_s = line.split()
            seq, iops = float(seq_s), float(iops_s)
        # an unreadable measurement must not cost the user a flash
        except ValueError:
            self.answer_speedtest("continue")
            return

        numbers = {"seq": f"{seq:.1f}", "iops": f"{iops:.0f}"}
        if seq >= WTG_MIN_SEQ_MBPS and iops >= WTG_MIN_RAND_IOPS:
            self.append_log("[*] " + T["speed_ok"].format(**numbers))
            self.answer_speedtest("continue")
            return

        self.append_log("[*] " + T["speed_slow"].format(**numbers))
        dialog = Adw.AlertDialog(
            heading=T["speed_title"],
            body=T["speed_body"].format(
                min_seq=f"{WTG_MIN_SEQ_MBPS:.0f}",
                min_iops=WTG_MIN_RAND_IOPS,
                **numbers,
            ),
        )
        dialog.set_body_use_markup(True)
        dialog.add_response("cancel", T["btn_cancel"])
        dialog.add_response("continue", T["btn_continue_anyway"])
        dialog.set_response_appearance("continue", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.choose(self, None, self.on_speedtest_response)

    def on_speedtest_response(self, dialog, result):
        if dialog.choose_finish(result) == "continue":
            self.answer_speedtest("continue")
            return

        # is_flashing goes down first: the worker exits on this answer, and the
        # reader thread must treat that as the chosen ending, not a failure
        self.is_flashing = False
        self.answer_speedtest("abort")
        self.append_log(T["speed_canceled"])
        self.update_flash_progress(0.0)
        canceled = Adw.AlertDialog(heading=T["speed_title"], body=T["speed_canceled"])
        canceled.add_response("close", T["btn_close_app"])
        canceled.add_response("restart", T["btn_restart"])
        canceled.choose(self, None, self.on_error_response)

    def on_flash_success(self):
        self.is_flashing = False
        self.append_log(T["done"])
        self.flash_progress.set_fraction(1.0)
        
        self.flash_progress.set_visible(False)
        self.btn_done.set_visible(True)

    def update_flash_progress(self, fraction, label=None):
        self.flash_progress.set_fraction(fraction)
        # None restores the built-in percentage text
        self.flash_progress.set_text(label)


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
