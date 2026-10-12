import gi
import os
import subprocess  # nosec B404 - all calls below use argv lists, never shell=True
import threading
import time
import re
import json
import queue
from pathlib import Path

# Flatpak points XDG_CONFIG_HOME into the sandbox
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "lufux"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {"theme": 0, "lang": "", "verify": True}

# What a drive has to manage before Windows To Go is worth deploying onto it.
# The random figure is the one that decides: a stick doing 8 MB/s sequentially
# and a few dozen 4 KiB writes a second produced a system that spent 3.5 hours
# on its first boot and reported a 5 842 183 ms average disk response.
WTG_MIN_SEQ_MBPS = 15.0
WTG_MIN_RAND_IOPS = 100

# The ESP the Windows To Go script carves out (1 MiB gap + 512 MiB), plus what
# NTFS spends on its own metadata, plus the room Windows wants left over: it
# still has OOBE to finish after the apply. Deploying is measured in hours, so
# running out of space is worth catching before the first byte is written and
# not at the end.
WTG_ESP_BYTES = 513 * 1024 ** 2
WTG_NTFS_OVERHEAD = 1.03
WTG_FREE_MARGIN = 2 * 1024 ** 3

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


def trusted_bin(name):
    """The absolute path of a program pkexec is to run as root.

    pkexec looks a bare name up in the caller's $PATH, before it clears the
    environment, so handing it "bash" runs whichever bash that PATH lists
    first - as root.
    """
    path = resolve_bin(name)
    if not os.path.isabs(path):
        raise FileNotFoundError(f"{name} is not in {', '.join(TRUSTED_BIN_DIRS)}")
    return path


def pkexec_argv(program, *args):
    return [resolve_bin('pkexec'), trusted_bin(program), *args]


def reselect(drives, chosen, first):
    """The row to select once the drive list has been replaced, or None.

    set_model() puts the selection back on the first row, so a stick plugged in
    or pulled on step 1 used to move the choice silently onto another drive.
    The choice now follows its device name, and if that drive is gone no drive
    is chosen for the user rather than another one. Only a list that had no
    drives before gets its first row picked.
    """
    names = [d.split()[0] for d in drives]
    if chosen in names:
        return names.index(chosen)
    if chosen is None and first and drives:
        return 0
    return None


def is_drive_row(text):
    """False for the rows of the drive list that stand for no drive."""
    return text not in (T["no_drives"], T["pick_drive"])

def list_iso_editions(iso_path):
    """[(image index, name, size)] for the Windows images in an ISO, [] if unreadable.

    Windows To Go deploys one image out of install.wim, and a retail ISO carries
    several - Home, Pro, Education. A current Windows ISO keeps its tree in UDF,
    so it has to be mounted; udisks does that as the plain user, no password.
    """
    try:
        with mounted_iso(iso_path) as root:
            for name in ('install.wim', 'install.esd'):
                image = os.path.join(root, 'sources', name)
                if os.path.exists(image):
                    break
            else:
                return []
            info = subprocess.run(  # nosec B603
                [resolve_bin('wimlib-imagex'), 'info', image],
                text=True, capture_output=True, check=False, timeout=120).stdout
        return parse_wim_info(info)
    # a listing that fails costs the edition choice, never the flash
    except (OSError, ValueError, LookupError, GLib.Error, subprocess.SubprocessError):
        return []


def parse_wim_info(info):
    """[(index, name, size)] out of `wimlib-imagex info` on a WIM.

    The size is what the image occupies once applied, which is not what
    "Total Bytes" says: that field adds up file sizes, and Windows keeps
    WinSxS as hard links, so every linked file is counted again for each name
    it has. "Hard Link Bytes" is that duplication, and wimlib applies the
    links as links, so it never reaches the drive. A real Windows 11 image
    measured 18.5 GiB by the first figure and 11.3 GiB by the difference -
    and 11.9 GiB is what actually landed on a stick.

    Both figures stay 0 if a future wimlib stops printing them, and the
    capacity check then skips itself rather than guessing.
    """
    editions = []
    index = None
    for line in info.splitlines():
        # "Display Name:" is a different key and must not be picked up here
        if line.startswith("Index:"):
            index = line.split(":", 1)[1].strip()
        elif line.startswith("Name:") and index is not None:
            editions.append([int(index), line.split(":", 1)[1].strip(), 0])
            index = None
        elif line.startswith("Total Bytes:") and editions:
            editions[-1][2] += int(line.split(":", 1)[1].strip())
        elif line.startswith("Hard Link Bytes:") and editions:
            editions[-1][2] -= int(line.split(":", 1)[1].strip())
    return [tuple(edition) for edition in editions]


def fmt_size(size):
    """Bytes as a human figure with its unit; a netinst ISO is not 0.0 GiB."""
    if size >= 1024 ** 3:
        return f"{size / 1024 ** 3:.1f} GiB"
    return f"{size / 1024 ** 2:.0f} MiB"


def unwritten_bytes(meminfo="/proc/meminfo"):
    """Data the kernel still has to write out, all drives together."""
    try:
        with open(meminfo, encoding="ascii") as f:
            return sum(int(line.split()[1]) for line in f
                       if line.startswith(("Dirty:", "Writeback:"))) * 1024
    except (OSError, ValueError, IndexError):
        return 0


def device_size_bytes(dev):
    """The whole device's size in bytes, or 0 when udisks cannot say."""
    return device_size(dev)


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
    if isinstance(data.get("verify"), bool):
        cfg["verify"] = data["verify"]
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
from windows_logic import write_windows
from windows_togo_logic import write_windows_togo
from universal_logic import write_image
from udisks_logic import PortalPath, list_drives, device_size, is_canceled, mounted_iso, can_format
from deps_logic import check_dependencies, get_distro_info, get_install_cmd
from iso_logic import volume_label, identify, windows_name

# here I am
APP_VERSION = "1.4.1"
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
            "drop_iso": "Отпустите, чтобы выбрать образ",
            "notify_done": "Образ записан",
            "notify_failed": "Ошибка записи",
            "notify_body": "{name} на {dev}",
            "step_drive": "Шаг 1: Выбор накопителя",
            "step_iso": "Шаг 2: Выбор образа",
            "step_summary": "Шаг 3: Сводка",
            "no_drives": "Накопители не найдены",
            "pick_drive": "Выберите накопитель",
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
            "verify_row": "Проверить после записи",
            "verify_hint": "Сравнить флешку с образом",
            "speed_eta": "{pct}% · {speed} МБ/с · осталось {eta}",
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
            "stopping": "Остановка процесса записи...",
            "stopping_left": "Остановка: осталось записать {mb} МБ",
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
            "iso_portal": "Lufux не может открыть образ из этой папки. Переложите его в домашнюю папку.",
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
            "cap_block_title": "Образ не поместится",
            "cap_block_body": (
                "Для записи нужно <b>{needed}</b>, а на накопителе "
                "<b>{size}</b>.\n\n"
                "Возьмите накопитель больше или выберите редакцию поменьше."
            ),
            "cap_tight_title": "Места почти не останется",
            "cap_tight_body": (
                "После развёртывания свободным останется около "
                "<b>{free}</b>.\n\n"
                "Windows ещё предстоит завершить первую настройку, и на таком "
                "остатке она может не пройти её до конца."
            ),
            "cap_log": "Нужно {needed}, на накопителе {size}",
            "err_code": "Код:",
            "flash_failed": "Запись не завершилась. Подробности — в журнале.",
            "scheme_dd": "Isohybrid (побайтовая копия через dd)"
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
        "drop_iso": "Drop to choose the image",
        "notify_done": "Image written",
        "notify_failed": "Writing failed",
        "notify_body": "{name} on {dev}",
        "step_drive": "Step 1: Select Drive",
        "step_iso": "Step 2: Select ISO",
        "step_summary": "Step 3: Summary",
        "no_drives": "No drives found",
        "pick_drive": "Select a drive",
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
        "verify_row": "Verify after writing",
        "verify_hint": "Compare the drive with the image",
        "speed_eta": "{pct}% · {speed} MB/s · {eta} left",
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
        "stopping": "Stopping the flashing process...",
        "stopping_left": "Stopping: {mb} MB left to write",
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
        "iso_portal": "Lufux cannot open the image from this folder. Move it to your home folder.",
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
        "cap_block_title": "The image will not fit",
        "cap_block_body": (
            "Writing this needs <b>{needed}</b> and the drive holds "
            "<b>{size}</b>.\n\n"
            "Use a larger drive, or pick a smaller edition."
        ),
        "cap_tight_title": "Almost nothing will be left free",
        "cap_tight_body": (
            "About <b>{free}</b> would be free once the deployment "
            "finishes.\n\n"
            "Windows still has its first-run setup to get through, and it may "
            "not finish with that little room."
        ),
        "cap_log": "Needs {needed}, the drive holds {size}",
        "err_code": "Code:",
        "flash_failed": "Flashing did not finish. The log has the details.",
        "scheme_dd": "Isohybrid (dd block copy)"
    }

T = get_locale_dict()

class LufuxWindow(Adw.ApplicationWindow):
    def __init__(self, iso_path=None, drive=None, **kwargs):
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
        self.speed_refused = False
        # background jobs other than the flash that report back to this window
        self.jobs = 0

        self.connect("close-request", self.on_close_request)

        # Nautilus on Hyprland offers only MOVE; the file stays where it is
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        drop.connect("enter", self.on_drag_enter)
        drop.connect("leave", lambda *_: self.drop_hint.set_visible(False))
        drop.connect("drop", self.on_drop)
        self.add_controller(drop)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        overlay = Gtk.Overlay(child=main_box)
        self.set_content(overlay)

        self.drop_hint = Gtk.Box(can_target=False, visible=False)
        self.drop_hint.add_css_class("drop-hint")
        self.drop_hint.append(Gtk.Label(label=T["drop_iso"], hexpand=True, css_classes=["title-2"]))
        overlay.add_overlay(self.drop_hint)

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
        for _ in range(3):
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
        self.auto_refresh_drives()
        self.refresh_id = GLib.timeout_add_seconds(2, self.auto_refresh_drives)
        if drive:
            names = [d.split()[0] for d in self.last_drives]
            if drive in names:
                self.drive_dropdown.set_selected(names.index(drive))
        if iso_path:
            self.set_iso(iso_path)

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
        self.iso_system = ""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15, halign=Gtk.Align.CENTER)
        page.set_child(box)

        self.iso_btn = Gtk.Button(label=T["select_iso"])
        self.iso_btn.connect("clicked", self.on_select_iso)
        box.append(self.iso_btn)

        self.iso_name = Gtk.Label()
        self.iso_name.add_css_class("title-3")
        self.iso_name.set_visible(False)
        box.append(self.iso_name)

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
        self.update_iso_badge()

    def update_iso_badge(self):
        """Name the system in the chosen ISO."""
        if not self.iso_path:
            return
        windows = self.os_dropdown.get_selected() == 0
        if windows:
            name = windows_name(self.editions)
        else:
            name = identify(volume_label(self.iso_path), os.path.basename(self.iso_path))
        self.iso_system = name
        self.iso_name.set_label(name)
        self.iso_name.set_visible(True)

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

    def selected_img_bytes(self):
        """Uncompressed size of the image to deploy, 0 when it is not known."""
        pos = self.edition_dropdown.get_selected()
        if self.editions and 0 <= pos < len(self.editions):
            return self.editions[pos][2]
        return self.editions[0][2] if self.editions else 0

    def read_editions(self, iso):
        editions = list_iso_editions(iso)
        GLib.idle_add(self.apply_editions, iso, editions)

    def apply_editions(self, iso, editions):
        # a second ISO can be chosen while the first one is still being read
        if iso != self.iso_path:
            return
        self.editions = editions
        names = [name for _, name, _ in editions] or [T["edition_reading"]]
        self.edition_dropdown.set_model(Gtk.StringList.new(names))
        self.edition_dropdown.set_selected(0)
        self.update_edition_visible()
        self.update_iso_badge()

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

        self.sum_verify = Adw.SwitchRow(title=T["verify_row"], subtitle=T["verify_hint"])
        self.sum_verify.set_active(APP_CONFIG.get("verify", True))
        self.sum_verify.connect("notify::active", self.on_verify_toggled)
        pref_group.add(self.sum_verify)
        return page

    def on_verify_toggled(self, row, param):
        APP_CONFIG["verify"] = row.get_active()
        save_config(APP_CONFIG)

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
            is_valid_drive = sel is not None and is_drive_row(sel.get_string())
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
        if self.iso_system and self.iso_system != os_text:
            os_text = f"{self.iso_system} · {os_text}"
        self.sum_os.set_subtitle(os_text)

        # a single-edition image never shows the picker, so the summary is the
        # only place that says which Windows is about to be written
        wtg = os_idx == 0 and self.wtg_check.get_active()
        self.sum_edition.set_visible(wtg and bool(self.editions))
        if wtg and self.editions:
            self.sum_edition.set_subtitle(
                {idx: name for idx, name, _ in self.editions}.get(
                    self.selected_img_index(), ""))

        if wtg:
            self.sum_scheme.set_subtitle(T["wtg_summary"])
        elif os_idx == 0:
            scheme_idx = self.scheme_dropdown.get_selected()
            scheme_text = T["scheme_gpt"] if scheme_idx == 0 else T["scheme_mbr"]
            self.sum_scheme.set_subtitle(scheme_text)
        else:
            self.sum_scheme.set_subtitle(T["scheme_dd"])
        # only dd writes the image as is, so only it can be compared
        self.sum_verify.set_visible(os_idx != 0)

    # --- Confirmation and start ---

    def request_start(self):
        if "nvme" in self.selected_dev:
            self.append_log(T["nvme_lock"])
            return

        problem = self.capacity_problem()
        if problem:
            kind, needed, size = problem
            if kind == "block":
                self.show_capacity_block(needed, size)
            else:
                self.show_capacity_warning(size - needed)
            return

        self.proceed_to_warnings()

    def capacity_problem(self):
        """("block"|"tight", needed, drive size) if it may not fit, else None.

        "block" means it cannot fit at all, "tight" that Windows would be left
        with almost nothing free. Any missing number returns None: a check that
        cannot be made must not stand in the way of a flash.
        """
        size = device_size_bytes(self.selected_dev)
        if not size:
            return None

        wtg = self.os_dropdown.get_selected() == 0 and self.wtg_check.get_active()
        if wtg:
            image = self.selected_img_bytes()
            if not image:
                return None
            needed = WTG_ESP_BYTES + int(image * WTG_NTFS_OVERHEAD)
        else:
            # the other modes put the ISO itself on the drive, whole
            try:
                needed = os.path.getsize(self.iso_path)
            except OSError:
                return None

        if needed > size:
            return ("block", needed, size)
        if wtg and size - needed < WTG_FREE_MARGIN:
            return ("tight", needed, size)
        return None

    def show_capacity_block(self, needed, size):
        self.append_log(T["cap_log"].format(needed=fmt_size(needed), size=fmt_size(size)))
        dialog = Adw.AlertDialog(
            heading=T["cap_block_title"],
            body=T["cap_block_body"].format(needed=fmt_size(needed), size=fmt_size(size)),
        )
        dialog.set_body_use_markup(True)
        dialog.add_response("ok", T["btn_close_dialog"])
        dialog.choose(self, None, lambda *_: None)

    def show_capacity_warning(self, free):
        dialog = Adw.AlertDialog(
            heading=T["cap_tight_title"],
            body=T["cap_tight_body"].format(free=fmt_size(free)),
        )
        dialog.set_body_use_markup(True)
        dialog.add_response("cancel", T["btn_cancel"])
        dialog.add_response("continue", T["btn_continue_anyway"])
        dialog.choose(self, None, self.on_capacity_response)

    def on_capacity_response(self, dialog, result):
        if dialog.choose_finish(result) == "continue":
            self.proceed_to_warnings()

    def proceed_to_warnings(self):
        # deps check: dd needs none of the Windows tools, and GRUB is only needed
        # for the MBR media it makes BIOS-bootable
        windows = self.os_dropdown.get_selected() == 0
        wtg = windows and self.wtg_check.get_active()
        bios_boot = (windows
                     and not self.wtg_check.get_active()
                     and self.scheme_dropdown.get_selected() == 1)
        missing = check_dependencies(windows=windows, bios_boot=bios_boot)
        # udisks runs the host's mkfs, which only it can see
        if windows:
            needs = ("ntfs",) if bios_boot else ("vfat", "ntfs") if wtg else ("vfat",)
            missing += [f"mkfs.{fs}" for fs in needs if not can_format(fs)]
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
            self.jobs += 1
            threading.Thread(target=self.install_deps_worker, daemon=True).start()

    def install_deps_worker(self):
        # install_cmd is a list of argv lists, run without shell
        try:
            for cmd in self.install_cmd:
                # cmd is ["pkexec", program, ...]; the program is pinned like
                # every other one that runs as root
                argv = pkexec_argv(cmd[1], *cmd[2:])
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
        self.jobs -= 1
        self.btn_next.set_sensitive(True)
        self.show_warn1_dialog()

    def show_deps_error(self, err_text):
        self.jobs -= 1
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
            self.speed_refused = False
            # read the dropdowns here, on the main thread: GTK4 forbids widget
            # access from anywhere else
            os_idx = self.os_dropdown.get_selected()
            scheme = "gpt" if self.scheme_dropdown.get_selected() == 0 else "mbr"
            wtg = self.wtg_check.get_active()
            img_index = self.selected_img_index()
            verify = os_idx != 0 and self.sum_verify.get_active()
            self.worker = threading.Thread(
                target=self.worker_thread,
                args=(self.iso_path, self.selected_dev, os_idx, scheme, wtg, img_index, verify),
                daemon=True,
            )
            self.worker.start()

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
        # the writer runs in this process and checks the flag
        self.is_flashing = False
        self.append_log(T["stopping"])
        # a slow drive takes minutes to take what is already in the cache
        GLib.timeout_add_seconds(1, self.show_stopping)

    def show_stopping(self):
        if not self.worker.is_alive():
            return False
        left = unwritten_bytes() >> 20
        if left:
            self.flash_progress.set_text(T["stopping_left"].format(mb=left))
        return True

    def show_interrupted_error(self):
        err_dialog = Adw.AlertDialog(heading=T["err_crit"], body=T["err_interrupted"])
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

        # the saved choice can be ahead of LANG when it changed mid-flash
        current_lang = APP_CONFIG.get("lang") or os.environ.get('LANG', '')
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

        if self.is_flashing or self.jobs:
            dialog = Adw.AlertDialog(
                heading=T["lang_restart_title"],
                body=T["lang_restart_body"]
            )
            dialog.add_response("ok", T.get("btn_close_dialog", "OK"))
            dialog.choose(self, None, lambda *args: None)
        else:
            os.environ['LANG'] = new_lang
            # not from inside the dialog's own signal: the dialog goes with the window
            GLib.idle_add(self.rebuild)

    def rebuild(self):
        """Swap this window for a new one in the current language."""
        T.clear()
        T.update(get_locale_dict())
        sel = self.drive_dropdown.get_selected_item()
        drive = sel.get_string().split()[0] if sel and is_drive_row(sel.get_string()) else None
        win = LufuxWindow(application=self.get_application(), iso_path=self.iso_path,
                          drive=drive)
        win.set_default_size(self.get_width(), self.get_height())
        win.present()
        GLib.source_remove(self.refresh_id)
        self.destroy()
        return False

    def auto_refresh_drives(self):
        if self.current_step == 0:
            new_drives = self.get_usb_drives()
            if new_drives != self.last_drives:
                first = self.last_drives in ([], [T["no_drives"]])
                sel = self.drive_dropdown.get_selected_item()
                chosen = None
                if sel is not None and is_drive_row(sel.get_string()):
                    chosen = sel.get_string().split()[0]
                self.last_drives = new_drives
                row = reselect(new_drives, chosen, first)
                rows = new_drives
                if row is None and new_drives != [T["no_drives"]]:
                    # a DropDown always selects some row - INVALID_LIST_POSITION
                    # snaps back to the first - so "no drive" is a row of its own
                    rows = [T["pick_drive"], *new_drives]
                    row = 0
                self.drive_dropdown.set_model(Gtk.StringList.new(rows))
                self.drive_dropdown.set_selected(row or 0)
                self.update_ui_state()
        return True

    def get_usb_drives(self):
        try:
            drives = [" ".join(x for x in (dev.removeprefix("/dev/"), fmt_size(size), model) if x)
                      for dev, size, model in list_drives()]
            return drives if drives else [T["no_drives"]]
        except GLib.Error:
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
                self.set_iso(file.get_path())
        except GLib.Error:
            pass

    def on_drag_enter(self, target, x, y):
        if self.current_step > 1:
            return 0
        self.drop_hint.set_visible(True)
        offered = target.get_current_drop().get_actions()
        return Gdk.DragAction.COPY if offered & Gdk.DragAction.COPY else Gdk.DragAction.MOVE

    def on_drop(self, target, files, x, y):
        self.drop_hint.set_visible(False)
        files = files.get_files()
        path = files[0].get_path() if len(files) == 1 else None
        if self.current_step > 1 or not path or not path.lower().endswith(".iso"):
            return False
        self.set_iso(path)
        sel = self.drive_dropdown.get_selected_item()
        if self.current_step == 0 and sel is not None and is_drive_row(sel.get_string()):
            self.current_step = 1
            self.update_ui_state()
        return True

    def set_iso(self, path):
        self.iso_path = path
        self.iso_label.set_label(os.path.basename(path))
        self.analyze_iso()
        self.editions = []
        self.update_edition_visible()
        self.update_iso_badge()
        # only Windows has editions; a loop mount of anything else is wasted time
        if self.os_dropdown.get_selected() == 0:
            threading.Thread(target=self.read_editions, args=(path,), daemon=True).start()
        self.update_ui_state()

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

    def udisks_worker(self, write, iso, dev, *args):
        """Run a writer that goes through udisks, in this process."""
        started = [time.monotonic()]

        def status(msg):
            started[0] = time.monotonic()
            GLib.idle_add(self.update_flash_progress, 0.0, msg)
            GLib.idle_add(self.append_log, f"[*] {msg}")

        def progress(done, total):
            elapsed = time.monotonic() - started[0]
            label = None
            if elapsed >= 1 and done:
                speed = done / elapsed
                eta = int((total - done) / speed)
                label = T["speed_eta"].format(pct=done * 100 // total, speed=f"{speed / 1e6:.1f}",
                                              eta=f"{eta // 60}:{eta % 60:02d}")
            GLib.idle_add(self.update_flash_progress, done / total, label)

        try:
            done = write(iso, dev, status, progress, lambda: not self.is_flashing, *args)
        except GLib.Error as e:
            self.is_flashing = False
            if is_canceled(e):
                GLib.idle_add(self.append_log, T["canceled"])
                GLib.idle_add(self.show_flash_failed, T["canceled"], "")
            else:
                msg = re.sub(r"^GDBus\.Error:\S+\s*", "", e.message)
                GLib.idle_add(self.append_log, f"{T['err_crit']} {msg}")
                GLib.idle_add(self.show_flash_failed, T["err_crit"], f"{T['flash_failed']}\n\n{msg}")
            return
        except PortalPath:
            self.is_flashing = False
            GLib.idle_add(self.append_log, f"{T['err_crit']} {T['iso_portal']}")
            GLib.idle_add(self.show_flash_failed, T["err_crit"], T["iso_portal"])
            return
        except Exception as e:  # noqa: BLE001
            self.is_flashing = False
            GLib.idle_add(self.append_log, f"{T['err_crit']} {e}")
            GLib.idle_add(self.show_flash_failed, T["err_crit"], f"{T['flash_failed']}\n\n{e}")
            return
        if done:
            GLib.idle_add(self.on_flash_success)
        elif not self.speed_refused:
            GLib.idle_add(self.show_interrupted_error)

    def worker_thread(self, iso, dev, os_idx, scheme, wtg, img_index=1, verify=False):
        if os_idx != 0:
            self.udisks_worker(write_image, iso, dev, verify)
        elif wtg:
            self.udisks_worker(write_windows_togo, iso, dev, img_index, self.ask_speed)
        else:
            self.udisks_worker(write_windows, iso, dev, scheme)

    # --- Drive speed gate (Windows To Go only) ---

    def ask_speed(self, seq, iops):
        """Called on the writer's thread: wait for the user's answer."""
        self.speed_answer = queue.Queue()
        GLib.idle_add(self.on_speedtest, seq, iops)
        while self.is_flashing:
            try:
                return self.speed_answer.get(timeout=0.5) == "continue"
            except queue.Empty:
                pass
        return False

    def answer_speedtest(self, answer):
        self.speed_answer.put(answer)

    def on_speedtest(self, seq, iops):
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
        self.speed_refused = True
        self.answer_speedtest("abort")
        self.append_log(T["speed_canceled"])
        self.update_flash_progress(0.0)
        canceled = Adw.AlertDialog(heading=T["speed_title"], body=T["speed_canceled"])
        canceled.add_response("close", T["btn_close_app"])
        canceled.add_response("restart", T["btn_restart"])
        canceled.choose(self, None, self.on_error_response)

    def notify(self, title, body=""):
        """A desktop notification, when the window is not in front to say it."""
        if self.is_active():
            return
        note = Gio.Notification.new(title)
        # the Flatpak exports the icon under the app ID, packages as lufux
        note.set_icon(Gio.ThemedIcon.new_from_names(["io.github.Advnirr.Lufux"]))
        if body:
            note.set_body(body)
        self.get_application().send_notification("flash", note)

    def show_flash_failed(self, heading, body):
        # a failed flash used to leave only a log line behind: this page hides
        # the navigation and has no Done button, so the app had to be closed
        # before anything could be tried again
        self.update_flash_progress(0.0)
        self.notify(T["notify_failed"], body or heading)
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("close", T["btn_close_app"])
        dialog.add_response("restart", T["btn_restart"])
        dialog.choose(self, None, self.on_error_response)
        return False

    def on_flash_success(self):
        self.is_flashing = False
        self.append_log(T["done"])
        self.notify(T["notify_done"], T["notify_body"].format(
            name=self.iso_system or os.path.basename(self.iso_path),
            dev=self.selected_dev.removeprefix("/dev/")))
        self.flash_progress.set_fraction(1.0)

        self.flash_progress.set_visible(False)
        self.btn_done.set_visible(True)

    def update_flash_progress(self, fraction, label=None):
        self.flash_progress.set_fraction(fraction)
        # None restores the built-in percentage text
        self.flash_progress.set_text(label)


class LufuxApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.Advnirr.Lufux")
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
        .drop-hint {
            margin: 12px;
            border: 3px dashed @accent_color;
            border-radius: 12px;
            background-color: alpha(@window_bg_color, 0.95);
            color: @accent_color;
        }
        """)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        win = LufuxWindow(application=app)
        win.present()

if __name__ == '__main__':
    app = LufuxApp()
    app.run(None)
