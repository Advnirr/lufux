# Windows To Go BCD: writer and boot-test harness

The Windows To Go drive needs a BCD boot store. Windows builds one with
`bcdboot.exe`, which does not exist on Linux, and the `BCD-Template` inside a
Windows image is not a usable store on its own. `../../bcd_logic.py` writes one
from scratch; this directory is what verifies it, by running the real
`bootmgfw.efi` against the store under QEMU/OVMF.

## Status

Solved and verified end to end. A 15 GiB drive deployed by
`windows_togo_logic.py` boots Windows 11 under OVMF/KVM as a USB mass-storage
device, runs the specialize pass to completion and reaches OOBE.

The store has to satisfy two very different readers, and each rejects different
things:

* **bootmgr** only cares about the object graph and the device elements. It
  ignores the hive's security descriptor and the `Description` key entirely.
* **Windows** loads the same file through the registry. sysprep's specialize
  pass opens it, and anything wrong there fails the pass - which surfaces on
  first boot as "Windows Setup could not configure Windows to run on this
  computer's hardware", *after* the desktop has already appeared. Two things
  were needed for that: a security descriptor with a real owner (an ownerless
  one is `STATUS_INVALID_OWNER`, 0xc000005a), and `Description\System` = 1.

The `System` requirement is not guesswork: `spbcd.dll`'s mark step reads
`Description\System` and writes `Description\TreatAsSystem` = 1 next to it when
that is set, and its "is this the system store" predicate then requires both to
be non-zero. Neither the `BCD-Template` in a Windows image nor the BCD on an
installer ISO carries `System`, because neither is a system store, so there is
no sample to copy it from - `objdump -d` on `spbcd.dll` is the source.

## The device element

A `device`/`osdevice` element is a zero options GUID followed by a 72-byte
descriptor. Offsets below are into the descriptor, i.e. 16 past the start of
the element:

```
+0   device type: 5 = the volume this application was loaded from ("boot"),
                  6 = a partition
+4   flags
+8   descriptor length, 0x48
+12  -
+16  partition identifier: GPT partition GUID, or an 8-byte MBR byte offset
+32  containing device: 0 = a local hard disk
+36  its partitioning: 0 = GPT, 1 = MBR
+40  disk identifier: GPT disk GUID, or a 4-byte MBR disk signature
```

Both GUIDs are the raw bytes as they sit in the GPT (mixed endian,
`uuid.UUID.bytes_le`), not the printed form. `{bootmgr}` keeps type 5, which
names whichever ESP the firmware booted; only the osloader needs type 6.

The layout was measured from real stores - type 5 byte for byte out of a
Windows 11 installer BCD (`dumpbcd.py` prints it), type 6 from the annotated
dumps at <http://www.mistyprojects.co.uk/documents/BCDEdit/files/device_partition.htm>
\- and then confirmed by booting it. Two long detours are worth not repeating:
device type 0 (BlockIo) with a nested parent descriptor is the *ramdisk* shape,
not the partition shape, and the partition offset is never what a GPT entry is
addressed by.

## What the oracle tells you

Boot the built image and read the status code on the console:

| code | meaning |
|------|---------|
| `0xc0000001` | store not usable at all (this is what BCD-Template alone gives) |
| `0xc0000024` / `0xc000000d` | store parsed, device element rejected as malformed |
| `0xc000000e` | device element accepted, volume not found |
| `0xc0000225` | element well-formed, but no partition on the disk matches it |
| `0xc000000f` on `winload.efi` | partition resolved, winload not on it |
| `File: \Windows\system32\config\system` | winload ran (in a stub test image, this is as far as it goes) |
| nothing at all, then a reset | also success: bootmgr handed off silently |

That last row is the normal outcome for a single-entry store, because bootmgr
only brings up the text console when it has a menu to draw, and without that
console its error screens are invisible. Two ways to get a readable failure:
build a two-entry store with `mkbcd.py` (the menu forces the console up, and
errors after the selection are drawn), or lean on the fact that a *bad* element
does print - a store built with a wrong partition GUID shows `0xc0000225`, so a
black screen where the bogus twin shows an error is itself the evidence.

## Running it

```sh
./build.sh <bcd-file> disk.img          # assemble a WTG-shaped GPT image, no root
python3 mkstore.py disk.img real.bcd    # the store lufux actually ships
./boot_bcd.sh real.bcd real 25 45       # boot it, screenshot at 25s and 45s
```

`build.sh` expects `bootmgfw.efi` and `winload.efi` beside it; extract them
from a Windows image with:

```sh
wimlib-imagex extract install.esd 1 \
    /Windows/Boot/EFI/bootmgfw.efi /Windows/System32/winload.efi \
    --dest-dir=. --no-acls
```

`boot_bcd.sh` writes `shot_<label>_<seconds>.png` plus `lbl_<label>_*.png`
cropped to the console text. Under TCG a boot takes about a minute, so
screenshot after 20s at the earliest. `run.sh` puts its monitor socket under
`/tmp` because the scratchpad path exceeds the 108-byte `AF_UNIX` limit.

## Testing a real deployment

The stub image above only proves the boot chain. To exercise everything Windows
itself checks, deploy for real into a file and boot that:

```sh
truncate -s 15G disk.img
sudo losetup -P --find --show disk.img          # /dev/loopN
sudo bash <the script windows_togo_logic.py generates> <windows.iso> /dev/loopN
sudo losetup -d /dev/loopN
qemu-img create -f qcow2 -b disk.img -F raw run.qcow2   # keep disk.img pristine
```

Boot `run.qcow2` with `-device qemu-xhci -device usb-storage` so the drive is
seen the way it will be in real use, and give it 8-10 minutes: OOBE is the
success condition, not the desktop. When Setup fails, the reason is in
`\Windows\Panther\setuperr.log` on the NTFS partition, which is worth reading
before changing anything - it names the failing sysprep module and its NTSTATUS.

`mkntfs` cannot read the geometry of a loop partition and warns that Windows
will not boot from it. That only concerns the NTFS boot sector's hidden-sectors
field, which nothing in a UEFI boot reads; the drive still boots. On a real
block device the warning does not appear.
