import sys, struct
sys.path.insert(0, "/tmp/claude-1000/-home-mikhail-MyProjectsFolder-GitHub-lufux-linux/9dbb24ea-fff3-45bd-9498-7f9835cf1539/scratchpad")
from regf import Hive

TYPE = {0x10100002: "Windows Boot Manager", 0x10200003: "Windows OS Loader",
        0x10400008: "Memory Diagnostic", 0x20100000: "settings"}

h = Hive(open(sys.argv[1], "rb").read())
# rebuild paths ignoring the root key's own (unparsed) name
objs, cur = {}, None
def walk(off, parts):
    nk = h.nk(off)
    yield parts, nk
    for s in h.subkeys(nk):
        yield from walk(s, parts + [h.nk(s)["name"]])

for parts, nk in walk(h.root_off, []):
    if len(parts) >= 2 and parts[0] == "Objects":
        g = parts[1]
        o = objs.setdefault(g, {"type": None, "elems": {}})
        if len(parts) == 3 and parts[2] == "Description":
            for n, t, raw in h.values(nk):
                if n == "Type" and len(raw) == 4:
                    o["type"] = struct.unpack("<I", raw)[0]
        if len(parts) == 4 and parts[2] == "Elements":
            for n, t, raw in h.values(nk):
                if n == "Element":
                    o["elems"][parts[3]] = (t, raw)

print(f"objects: {len(objs)}\n")
for g, o in sorted(objs.items(), key=lambda kv: -(kv[1]["type"] or 0)):
    print(f"--- {g}   [{TYPE.get(o['type'], hex(o['type'] or 0))}]  Type=0x{o['type']:08x}")
    for eid in sorted(o["elems"]):
        vt, raw = o["elems"][eid]
        if vt == 1:   v = repr(raw.decode("utf-16-le").rstrip("\x00"))
        elif vt == 7: v = repr([x for x in raw.decode("utf-16-le").split("\x00") if x])
        elif vt == 3: v = f"BINARY[{len(raw)}] " + raw.hex()
        else:         v = f"type{vt}[{len(raw)}] " + raw.hex()
        print(f"    {eid} = {v}")
    print()
