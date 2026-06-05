import os

# Locals, idk
def get_locale_dict():
    lang = os.environ.get('LANG', '')
    if lang.startswith('ru'):
        return {
# russian locals
            "unmount": "Отмонтирование...",
            "copy": "Копирование образа (dd)...",
            "sync": "Синхронизация ввода-вывода (sync)...",
        }
    return {
# english locals
        "unmount": "Unmounting...",
        "copy": "Copying image (dd)...",
        "sync": "Syncing I/O (sync)...",
    }

def get_linux_script():
    # iso/dev come in as $1/$2, not interpolated, so a bad file name can't inject
    T = get_locale_dict()

    script = f"""#!/bin/bash
set -e

ISO_PATH="$1"
DEV_PATH="$2"

# ISO size in bytes
SIZE=$(stat -c%s "$ISO_PATH")

echo "STATUS: {T['unmount']}"
umount "$DEV_PATH"* 2>/dev/null || true
wipefs -a "$DEV_PATH"

echo "STATUS: {T['copy']}"
# Progress parsing
dd if="$ISO_PATH" of="$DEV_PATH" bs=4M status=progress 2>&1 | tr '\\r' '\\n' | while read -r line; do
    if [[ $line == *" bytes "* ]]; then
        BYTES=$(echo "$line" | awk '{{print $1}}')
        PCT=$(awk -v b="$BYTES" -v s="$SIZE" 'BEGIN {{printf "%.1f", (b/s)*100}}')
        echo "${{PCT}}%"
    fi
done

echo "STATUS: {T['sync']}"
sync

echo "STATUS: DONE"
"""
    return script
