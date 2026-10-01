# Lufux

<img src="lufux.svg" align="right" width="180" alt="Lufux Logo">

**[English](README.md) | Русский**

Простая программа с графическим интерфейсом для создания загрузочных флешек в Linux: образы ISOHybrid, установщики Windows и Windows To Go. Написана на Python, GTK4 и Libadwaita.

<p align="left">
  <a href="https://github.com/Advnirr/lufux/releases">
    <img src="https://img.shields.io/badge/release-v1.3.9--stable-007EC6?style=flat-square" alt="Release">
  </a>
  <a href="https://github.com/Advnirr/lufux/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/license-GPL--3.0-FF5722?style=flat-square" alt="License">
  </a>
</p>

---

## ⚙️ Возможности

* **Поддержка Windows:** Сама распознаёт образ Windows и выбирает разметку: GPT/FAT32 для UEFI или MBR/NTFS для Legacy BIOS.
* **Большие WIM-файлы:** Находит сжатые `.esd` и `.wim` больше 4 ГБ и на лету разбивает или конвертирует их, чтобы обойти ограничение FAT32.
* **Windows To Go:** Устанавливает Windows прямо на флешку, и она загружается как обычная система, а не как установщик. Lufux сам собирает хранилище BCD под GPT-идентификаторы накопителя. Проверено до экрана OOBE на настоящей флешке.
* **Выбор редакции:** Если в образе несколько редакций, Lufux покажет список, и Windows To Go поставит выбранную.
* **Проверка скорости:** Перед установкой Windows To Go замеряет последовательную запись и случайную запись блоками по 4 КБ. Если накопитель слишком медленный, Lufux предупредит.
* **Linux / Isohybrid:** Записывает образ побайтно через `dd`, поэтому дистрибутивы Linux загружаются так же, как с оригинального образа.
* **Нативный интерфейс:** GTK4/Adwaita.

## 📦 Зависимости

Для запуска Lufux нужны системные пакеты:
`python-gobject`, `gtk4`, `libadwaita`, `wimlib` (для wimlib-imagex), `rsync`, `parted`, `polkit` (для pkexec), `dosfstools` (для mkfs.vfat), `ntfs-3g` (для mkfs.ntfs). Для MBR/Legacy BIOS ещё нужен `grub` (`grub2-common` и `grub-pc-bin` на Debian/Ubuntu, `grub2-tools` и `grub2-pc-modules` на Fedora).

`udisks2` необязателен. С ним Lufux читает список редакций из образа без пароля. Без него Windows To Go ставит первую редакцию из образа.

## 🚀 Установка

### Arch Linux / CachyOS (Рекомендовано)

**Установка с помощью AUR Helper**

Пакет есть в AUR, его можно поставить через Yay:
```bash
yay -S lufux-git
```

**Установка с помощью PKGBUILD**

На Arch и производных (CachyOS, EndeavourOS и т.п.) можно собрать пакет из `PKGBUILD`:
```bash
git clone https://github.com/Advnirr/lufux.git
cd lufux
makepkg -si
```

### Debian / Ubuntu

Скачайте `lufux_<версия>_all.deb` со страницы [Releases](https://github.com/Advnirr/lufux/releases) и установите:
```bash
sudo apt install ./lufux_*_all.deb
```
Подходит для Debian 13 и Ubuntu 24.04 или новее.

### Fedora

Скачайте `.rpm` со страницы [Releases](https://github.com/Advnirr/lufux/releases) и установите:
```bash
sudo dnf install ./lufux-*.noarch.rpm
```

Пакеты можно собрать и самому через `tools/build-packages.sh`. Для этого нужны `dpkg-deb` и `rpmbuild`, готовые файлы появятся в `dist/`.

### Ручной запуск (Любой дистрибутив)
Lufux можно запустить прямо из исходников, без установки:
```bash
git clone https://github.com/Advnirr/lufux.git
cd lufux
python3 main.py
```
Перед запуском установите зависимости из списка выше.

## 🧪 Тесты

```bash
python3 -m unittest discover -s tests
```

Тесты проверяют то, что не требует флешки: BCD, который собирает Lufux,
чтение GUID из GPT, проверку объёма, поиск зависимостей и замер скорости.
Реальные диски они не трогают, root им не нужен.

## ⚠️ Предупреждения

* **Выбранный накопитель стирается полностью** в любом режиме. Перед началом проверьте имя устройства на странице сводки.
* **NVMe-диски в списке не показываются.** Поэтому не видны и коробки Thunderbolt / USB4: они подключают SSD как PCIe, а не как USB. Обычная коробка USB-C работает, для неё `lsblk -o NAME,TRAN` показывает `usb`. Фильтр нужен, чтобы в список не попал системный диск. Как отличить его от такой коробки, пока не понятно: нужен кто-то с этим железом, чтобы проверить.
* **Не вынимайте накопитель, пока не появится кнопка «Готово».** До этого Lufux ещё отмонтирует разделы. Закрыть программу во время записи можно, накопитель просто останется незаписанным.
* **Во время долгой записи окно кажется зависшим.** В лог пишутся только названия этапов, поэтому двигается только прогресс-бар.
* **Для Windows To Go нужен быстрый накопитель.** Запись занимает часы, а потом Windows работает прямо с него. Дешёвая флешка USB 2.0 плохо подходит и для того, и для другого. Lufux заранее замерит скорость и предупредит, если накопитель слишком медленный.
* **Если Windows To Go падает с ошибкой INACCESSIBLE_BOOT_DEVICE (0x7B), попробуйте другой порт USB.** Рабочий накопитель может не загрузиться через один контроллер и нормально загрузиться через другой. На какой шине накопитель, показывает `lsusb -t`. Какому контроллеру принадлежит шина, показывает `grep -H . /sys/bus/usb/devices/usb*/serial`.

## 💜 Поддержать

Если Lufux вам помог, можно поддержать разработку:

**USDT** · сеть TON

```
UQDFela8stCZykNL2cLw2erPkzjAgSf-GLXoJuiTEmEckTNB
```

## Лицензия
Проект распространяется по лицензии GNU General Public License v3.0 (GPL-3.0). Подробности в файле [LICENSE](LICENSE).
