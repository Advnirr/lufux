import struct, sys, uuid
sys.path.insert(0, "/home/mikhail/MyProjectsFolder/GitHub/lufux-linux")
sys.path.insert(0, "/tmp/claude-1000/-home-mikhail-MyProjectsFolder-GitHub-lufux-linux/9dbb24ea-fff3-45bd-9498-7f9835cf1539/scratchpad/qtest")
import bcd_logic as B, mkbcd

PART_GUID = uuid.UUID("62498900-bbd7-4d46-bddd-ede1f14a0573").bytes_le
PART_OFFSET = 68157440
PARENT = struct.pack("<IIII", 5, 0, 0x48, 0) + b"\x00" * 56

def dev(subtype, ident, ident_at, flags):
    p = bytearray(36)
    struct.pack_into("<I", p, 0, subtype)
    p[ident_at:ident_at + len(ident)] = ident
    payload = bytes(p) + PARENT
    return b"\x00"*16 + struct.pack("<IIII", 0, flags, 16 + len(payload), 0) + payload

OFF = struct.pack("<Q", PART_OFFSET)
CANDS = {
    "f1_p0off8":  lambda: dev(0, OFF, 8, 1),
    "f1_p2off8":  lambda: dev(2, OFF, 8, 1),
    "f1_p0guid8": lambda: dev(0, PART_GUID, 8, 1),
    "f1_p2guid8": lambda: dev(2, PART_GUID, 8, 1),
}
d = CANDS[sys.argv[1]]()
G = "{11111111-2222-3333-4444-555555555555}"
open(sys.argv[2], "wb").write(mkbcd.build([(G, "LUFUX WTG", d, d)], G, timeout=5))
print(f"  {sys.argv[1]}: {len(d)} bytes")
