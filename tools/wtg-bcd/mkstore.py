"""Write the store that lufux ships, for the disk image built by build.sh.

    ./build.sh dummy.bcd disk.img
    python3 mkstore.py disk.img real.bcd
    ./boot_bcd.sh real.bcd real 25 45
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import bcd_logic

img, out = sys.argv[1], sys.argv[2]
part_guid, disk_guid = bcd_logic.gpt_guids(img, 2)
open(out, "wb").write(bcd_logic.build_bcd(part_guid, disk_guid, "Windows To Go"))
print(f"{out}: partition {part_guid.hex()} on disk {disk_guid.hex()}")
