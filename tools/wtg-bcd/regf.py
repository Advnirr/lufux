"""Minimal read-only Windows registry hive (regf) walker - enough to dump a BCD."""
import struct, sys

class Hive:
    def __init__(self, data):
        self.d = data
        assert data[:4] == b"regf", "not a regf hive"
        self.root_off = struct.unpack_from("<I", data, 0x24)[0]
        self.base = 0x1000

    def cell(self, off):
        p = self.base + off
        size = struct.unpack_from("<i", self.d, p)[0]
        return p + 4, abs(size) - 4

    def nk(self, off):
        p, _ = self.cell(off)
        assert self.d[p:p+2] == b"nk", self.d[p:p+2]
        (flags, ) = struct.unpack_from("<H", self.d, p+2)
        subkeys, = struct.unpack_from("<I", self.d, p+0x14)
        sk_off, = struct.unpack_from("<I", self.d, p+0x1C)
        nvals, vl_off = struct.unpack_from("<II", self.d, p+0x24)
        name_len, = struct.unpack_from("<H", self.d, p+0x48)
        name = self.d[p+0x4C:p+0x4C+name_len]
        name = name.decode("latin1") if flags & 0x20 else name.decode("utf-16-le")
        return dict(name=name, subkeys=subkeys, sk_off=sk_off, nvals=nvals, vl_off=vl_off)

    def subkeys(self, nk):
        if nk["subkeys"] == 0 or nk["sk_off"] == 0xFFFFFFFF:
            return []
        p, _ = self.cell(nk["sk_off"])
        sig = self.d[p:p+2]
        out = []
        if sig in (b"lf", b"lh"):
            n, = struct.unpack_from("<H", self.d, p+2)
            for i in range(n):
                off, = struct.unpack_from("<I", self.d, p+4+i*8)
                out.append(off)
        elif sig == b"ri":
            n, = struct.unpack_from("<H", self.d, p+2)
            for i in range(n):
                off, = struct.unpack_from("<I", self.d, p+4+i*4)
                out.extend(self.subkeys({"subkeys": 1, "sk_off": off}))
        elif sig == b"li":
            n, = struct.unpack_from("<H", self.d, p+2)
            for i in range(n):
                off, = struct.unpack_from("<I", self.d, p+4+i*4)
                out.append(off)
        return out

    def values(self, nk):
        if nk["nvals"] == 0 or nk["vl_off"] == 0xFFFFFFFF:
            return []
        p, _ = self.cell(nk["vl_off"])
        out = []
        for i in range(nk["nvals"]):
            voff, = struct.unpack_from("<I", self.d, p + i*4)
            vp, _ = self.cell(voff)
            assert self.d[vp:vp+2] == b"vk"
            nlen, dlen, doff, vtype, vflags = struct.unpack_from("<HIIIH", self.d, vp+2)
            name = self.d[vp+0x14:vp+0x14+nlen]
            name = name.decode("latin1") if vflags & 1 else name.decode("utf-16-le")
            if dlen & 0x80000000:              # inline data
                raw = struct.pack("<I", doff)[:dlen & 0x7FFFFFFF]
            else:
                dp, _ = self.cell(doff)
                raw = self.d[dp:dp+dlen]
            out.append((name or "(default)", vtype, raw))
        return out

    def walk(self, off=None, path=""):
        off = self.root_off if off is None else off
        nk = self.nk(off)
        here = path + "\\" + nk["name"] if path else nk["name"]
        yield here, nk
        for s in self.subkeys(nk):
            yield from self.walk(s, here)
