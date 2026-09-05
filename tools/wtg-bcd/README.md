# Windows To Go BCD: writer and boot-test harness

The Windows To Go drive needs a BCD boot store. Windows builds one with
`bcdboot.exe`, which does not exist on Linux, and the `BCD-Template` inside a
Windows image is not a usable store on its own. `../../bcd_logic.py` writes one
from scratch; this directory is what verifies it.

## Status

Working and verified against a real `bootmgfw.efi`:

* `HiveWriter` produces a registry hive that bootmgr parses. A two-entry store
  rendered a real boot menu with our own entry descriptions.
* The BCD object graph is correct. With `winload.efi` placed on the ESP (the
  volume `device boot` names), bootmgr resolved `{default}`, found the device,
  loaded winload and handed off - it then failed on
  `\Windows\system32\config\system`, which is winload's own next step.

Not solved: the device element that names a **partition**. `device boot`
(device type 5) is reproduced byte for byte from a real BCD and works, but the
osloader needs to point at the NTFS partition instead of the ESP.

## What the oracle tells you

Boot the built image and read the status code:

| code | meaning |
|------|---------|
| `0xc0000001` | store not usable at all (this is what BCD-Template alone gives) |
| `0xc0000024` / `0xc000000d` | store parsed, device element rejected as malformed |
| `0xc000000e` | device element accepted, volume not found (`STATUS_NO_SUCH_DEVICE`) |
| `0xc0000002` | as above, but with the nested parent honoured |
| `File: \Windows\system32\config\system` | **success** - winload ran, device resolved |

## Device element format, as measured

Read out of the `{7619dcc9-...}` and `{b2721d73-...}` entries of a real
Windows 11 installer BCD (`dumpbcd.py` prints them):

```
[0:16]    options GUID   (zero unless the element references another BCD object)
[16:32]   <IIII>         device type, flags, length (counted from +16), pad
[32:..]   payload
```

* device type 5 = "boot device" (the volume the application was loaded from).
  72-byte descriptor, payload all zeros, flags 0.
* device type 0 = BlockIo. payload+0 is the subtype; 3 = RamDisk.
  For the ramdisk sample, flags is 1 and a **nested 72-byte parent descriptor**
  (a copy of the type-5 boot device) sits at **payload+36**, with the
  `\sources\boot.wim` path immediately after it at payload+108.

## What has been ruled out

For the osloader device, all with a nested parent at payload+36:

* subtype 6, and device type 8 ("locate") - rejected outright (`0xc0000024` / `0xc000000d`)
* subtypes 0, 1, 2 with the partition byte offset at payload+4 or payload+8 - `0xc000000e`
* subtype 0 with the GPT partition GUID at payload+4 - rejected
* subtype 0, offset at payload+8, **flags=1** - `0xc0000002`, a new code, so
  flags=1 does change how the nested parent is read

## Next thing to try

The partition offset is being passed in **bytes**. It is quite possibly
expected in **sectors** (LBA). In the test image partition 2 is at byte
68157440 = LBA 133120. Try that with flags=1 and subtypes 0/1/2 first.

## Running it

```sh
./build.sh <bcd-file> <disk.img>      # assemble a WTG-shaped GPT image, no root
./run.sh <disk.img> <label> [seconds] # boot it under OVMF, screenshot the console
```

`build.sh` expects `bootmgfw.efi` and `winload.efi` beside it; extract them
from a Windows image with:

```sh
wimlib-imagex extract install.esd 1 \
    /Windows/Boot/EFI/bootmgfw.efi /Windows/System32/winload.efi \
    --dest-dir=. --no-acls
```

Set `ESP_WINLOAD=1` to also place winload on the ESP - that is the control that
proves everything except partition addressing.

`run.sh` puts its monitor socket under `/tmp` because the scratchpad path
exceeds the 108-byte `AF_UNIX` limit.
