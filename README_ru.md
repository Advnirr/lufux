# Lufus

<img src="lufux.svg" align="right" width="180" alt="Lufux Logo">

**[English](README.md) | Русский**

Минималистичный, универсальный и функциональный инструмент с графическим интерфейсом для создания загрузочных устройств на ОС Linux. Поддерживает как образы ISOHybrid, так и образы Windows. Основано на Python, GTK4, и Libadwaita.

<p align="left">
  <a href="https://github.com/Advnirr/lufux/releases">
    <img src="https://img.shields.io/badge/release-v1.2.0--stable-007EC6?style=flat-square" alt="Release">
  </a>
  <a href="https://github.com/Advnirr/lufux/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/license-GPL--3.0-FF5722?style=flat-square" alt="License">
  </a>
</p>

---

## ⚙️ Возможности

* **Поддержка Windows:** Автоматически определяет Windows ISO и применяет корректную схему разметки (GPT/FAT32 для UEFI, или MBR/NTFS для Legacy BIOS).
* **Обработка больших WIM-файлов:** Автоматически обнаруживает непрерывные `.esd` архивы и `.wim` файлы размером более 4ГБ, разделяя или преобразуя их на лету для обхода ограничений FAT32.
* **Поддержка Linux / Isohybrid:** Использует прямое побитовое копирование блоков с помощью команды `dd` для гарантированной загрузки дистрибутивов Linux.
* **Нативность:** Интерфейс GTK4/Adwaita.

## 📦 Зависимости

Для запуска Lufux, вам потребуются следующие системные пакеты:
`python-gobject`, `gtk4`, `libadwaita`, `wimlib` (для wimlib-imagex), `rsync`, `parted`, `polkit` (для pkexec), `libarchive` (для bsdtar).

## 🚀 Установка

### Arch Linux / CachyOS (Рекомендовано)

**Установка с помощью AUR Helper**

Пакет доступен на Arch User Repository, поэтому вы можете установить его используя Yay:
```bash
yay -S lufux-git
```

**Установка с помощью PKGBUILD**

Поскольку Lufux предоставляет `PKGBUILD`, установка на Arch и его производных дистрибутивах (CachyOS, EndeavourOS, т.п) следующая:
```bash
git clone https://github.com/Advnirr/lufux.git
cd lufux
makepkg -si
```

### Ручной запуск (Любой дистрибутив)
Вы можете запустить Lufux прямо из исходного кода без установки:
```bash
git clone https://github.com/Advnirr/lufux.git
cd lufux
python main.py
```
Внимание: Убедитесь, что вы установили все необходимые зависимости.

## Лицензия
Проект лицензирован GNU General Public License v3.0 (GPL-3.0). Ознакомьтесь с [LICENSE](LICENSE) для получения дополнительной информации.
