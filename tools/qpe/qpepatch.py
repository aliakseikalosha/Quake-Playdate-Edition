#!/usr/bin/env python3
"""Quake: Playdate Edition as a patch: the qpe mod without any of id Software's data in it.

    python3 qpepatch.py apply [qpe.qpatch] <Quake's id1 folder, or pak files> [-o qpe]
    python3 qpepatch.py make --qpe <built qpe folder> <id1 folder or paks> -o qpe.qpatch

`apply` recreates the mod's folder (gfx.wad, gfx/*.lmp, progs/*.mdl, textures.dat: what the game loads with
-game qpe) from your own copy of Quake. Give it Quake's id1 folder (pak0.pak, pak1.pak, ...) or the pak files
themselves; copy the folder it writes next to id1 in the game's .pdx (or Data folder). It needs Python 3 and
nothing else.

The patch holds, for every file of the mod, the file XORed with the original it replaces (a model, a picture,
the UI's gfx.wad), compressed, and for every map texture its four mip levels XORed with the original's. Without
the original data it is noise. Every original and every result is checked by CRC-32: a file whose original is
missing (the shareware has no pak1.pak) or differs (another release of Quake) is skipped and reported, so
applying it to the shareware pak0.pak gives exactly the part of the mod the shareware game uses.

Only the standard library is used, so this file can be handed out on its own (tools/qpe/qpe.py patch makes the
patch from the tree's build).
"""
import argparse
import json
import lzma
import os
import struct
import sys
import zlib

MAGIC = b"QPEPATCH"
VERSION = 1
TEXFILE = "textures.dat"
MANIFEST = "qpe-files.txt"
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATCH = "qpe.qpatch"


# --------------------------------------------------------------------------- Quake's data

def read_pak(path):
    """A pak file -> {name: (offset, length)}."""
    with open(path, "rb") as f:
        head = f.read(12)
        if head[:4] != b"PACK":
            raise ValueError("%s is not a Quake pak file" % path)
        ofs, size = struct.unpack("<ii", head[4:])
        f.seek(ofs)
        d = f.read(size)
    out = {}
    for i in range(size // 64):
        e = d[i * 64:i * 64 + 64]
        name = e[:56].split(b"\0")[0].decode("latin-1").lower()
        out[name] = struct.unpack("<ii", e[56:64])
    return out


class Data:
    """Quake's files: pak files in the order given (later ones win, as pak1.pak over pak0.pak), and the loose
    files of a folder over its paks, as the game reads them."""

    def __init__(self, sources):
        self.layers = []        # highest priority first: ("pak", path, index) | ("dir", path, None)
        for s in sources:
            if os.path.isdir(s):
                i = 0
                while os.path.isfile(os.path.join(s, "pak%d.pak" % i)):
                    p = os.path.join(s, "pak%d.pak" % i)
                    self.layers.insert(0, ("pak", p, read_pak(p)))
                    i += 1
                self.layers.insert(0, ("dir", s, None))
            elif os.path.isfile(s):
                self.layers.insert(0, ("pak", s, read_pak(s)))
            else:
                raise FileNotFoundError(s)
        if not any(k == "pak" for k, _, _ in self.layers):
            raise FileNotFoundError("no pak files in %s" % ", ".join(sources))

    def read(self, name):
        for kind, path, index in self.layers:
            if kind == "pak":
                if name in index:
                    ofs, n = index[name]
                    with open(path, "rb") as f:
                        f.seek(ofs)
                        return f.read(n)
            else:
                p = os.path.join(path, name)
                if os.path.isfile(p):
                    with open(p, "rb") as f:
                        return f.read()
        return None

    def listing(self):
        names = set()
        for kind, path, index in self.layers:
            if kind == "pak":
                names.update(index)
        return sorted(names)


def _crc_table():
    t = []
    for i in range(256):
        c = i << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) if c & 0x8000 else (c << 1)
        t.append(c & 0xffff)
    return t


_CRC = _crc_table()


def quake_crc(data):
    """crc.c's CRC, which the game (Mod_ReplaceTextures) computes over a texture's full-size pixels."""
    c = 0xffff
    t = _CRC
    for b in data:
        c = ((c << 8) & 0xffff) ^ t[(c >> 8) ^ b]
    return c


def map_textures(data, wanted):
    """The original textures of every map: {(name, w, h, quake crc): pixels of all 4 mip levels}, only for
    the (name, w, h) in wanted (the crc is slow in Python)."""
    out = {}
    crcs = {}           # pixels -> crc (many maps share a texture)
    for n in data.listing():
        if not (n.startswith("maps/") and n.endswith(".bsp")):
            continue
        b = data.read(n)
        ofs, _ = struct.unpack_from("<ii", b, 4 + 2 * 8)        # LUMP_TEXTURES
        count, = struct.unpack_from("<i", b, ofs)
        for i in range(count):
            o, = struct.unpack_from("<i", b, ofs + 4 + 4 * i)
            if o == -1:
                continue
            mt = ofs + o
            name = b[mt:mt + 16].split(b"\0")[0].decode("latin-1")
            w, h = struct.unpack_from("<II", b, mt + 16)
            if (name, w, h) not in wanted:
                continue
            offs = struct.unpack_from("<4I", b, mt + 24)
            mips = b"".join(b[mt + offs[k]:mt + offs[k] + (w >> k) * (h >> k)] for k in range(4))
            crc = crcs.get(mips[:w * h])
            if crc is None:
                crc = crcs[mips[:w * h]] = quake_crc(mips[:w * h])
            out.setdefault((name, w, h, crc), mips)
    return out


def read_texture_dat(b):
    """textures.dat -> [(name, w, h, crc, pixels of all 4 mip levels)] in file order."""
    if b[:4] != b"QTEX":
        raise ValueError("not a textures.dat")
    n, = struct.unpack_from("<i", b, 4)
    out = []
    for i in range(n):
        e = 8 + 32 * i
        name = b[e:e + 16].split(b"\0")[0].decode("latin-1")
        w, h, crc, pos = struct.unpack_from("<4i", b, e + 16)
        size = sum((w >> k) * (h >> k) for k in range(4))
        out.append((name, w, h, crc, b[pos:pos + size]))
    return out


def texture_dat(entries):
    """[(name, w, h, crc, pixels of all 4 mip levels)] -> textures.dat (layout: Mod_ReplaceTextures, model.c)."""
    head = b"QTEX" + struct.pack("<i", len(entries))
    pos = len(head) + 32 * len(entries)
    dir_, body = bytearray(), bytearray()
    for name, w, h, crc, pix in entries:
        dir_ += name.encode("latin-1")[:16].ljust(16, b"\0") + struct.pack("<4i", w, h, crc, pos + len(body))
        body += pix
    return head + bytes(dir_) + bytes(body)


def xor(a, b):
    n = len(a)
    return (int.from_bytes(a, "little") ^ int.from_bytes(b, "little")).to_bytes(n, "little")


def crc32(b):
    return zlib.crc32(b) & 0xffffffff


# --------------------------------------------------------------------------- make

def make(qpe_dir, data, out_path, log=print):
    """The built mod in qpe_dir, over the originals in data -> the patch file."""
    man = os.path.join(qpe_dir, MANIFEST)
    if os.path.isfile(man):
        names = [l for l in open(man).read().split("\n") if l]
    else:
        names = sorted(os.path.relpath(os.path.join(r, f), qpe_dir).replace(os.sep, "/")
                       for r, _, fs in os.walk(qpe_dir) for f in fs)
    head = {"version": VERSION, "files": [], "textures": []}
    blobs = bytearray()

    def blob(b):
        z = lzma.compress(b, preset=9)
        at = len(blobs)
        blobs.extend(z)
        return at, len(z)

    for name in names:
        if name == MANIFEST or name == TEXFILE:
            continue
        with open(os.path.join(qpe_dir, name), "rb") as f:
            new = f.read()
        orig = data.read(name)
        if orig is None:
            raise ValueError("%s: no original %s in the data" % (qpe_dir, name))
        if len(orig) != len(new):
            raise ValueError("%s is %d bytes, the original %d: the patch needs the same size" % (name, len(new), len(orig)))
        at, n = blob(xor(new, orig))
        head["files"].append({"name": name, "size": len(new), "base_crc32": crc32(orig), "crc32": crc32(new),
                              "at": at, "len": n})
    if TEXFILE in names:
        with open(os.path.join(qpe_dir, TEXFILE), "rb") as f:
            entries = read_texture_dat(f.read())
        origs = map_textures(data, {(e[0], e[1], e[2]) for e in entries})
        for name, w, h, crc, pix in entries:
            orig = origs.get((name, w, h, crc))
            if orig is None:
                raise ValueError("textures.dat: no original texture %s %dx%d (crc %04x) in the maps" % (name, w, h, crc))
            at, n = blob(xor(pix, orig))
            head["textures"].append({"name": name, "w": w, "h": h, "crc": crc, "base_crc32": crc32(orig),
                                     "crc32": crc32(pix), "at": at, "len": n})
    hj = json.dumps(head, separators=(",", ":")).encode()
    tmp = out_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(MAGIC + struct.pack("<II", VERSION, len(hj)) + hj + bytes(blobs))
    os.replace(tmp, out_path)
    log("patch: %d files and %d map textures -> %s (%.1f MB)" % (len(head["files"]), len(head["textures"]), out_path,
                                                               os.path.getsize(out_path) / 1e6))
    return head


# --------------------------------------------------------------------------- apply

def load(path):
    with open(path, "rb") as f:
        b = f.read()
    if b[:8] != MAGIC:
        raise ValueError("%s is not a qpe patch" % path)
    ver, hl = struct.unpack_from("<II", b, 8)
    if ver != VERSION:
        raise ValueError("%s is patch version %d, this program reads %d" % (path, ver, VERSION))
    head = json.loads(b[16:16 + hl])
    return head, memoryview(b)[16 + hl:]


def apply(patch_path, data, out_dir, log=print):
    """-> (files written, files skipped {name: why}, textures applied, textures in the patch)."""
    head, blobs = load(patch_path)

    def unpack(e):
        return lzma.decompress(blobs[e["at"]:e["at"] + e["len"]])

    files, skipped = {}, {}
    for e in head["files"]:
        orig = data.read(e["name"])
        if orig is None:
            skipped[e["name"]] = "not in this data"
        elif len(orig) != e["size"] or crc32(orig) != e["base_crc32"]:
            skipped[e["name"]] = "another version of the file"
        else:
            new = xor(unpack(e), orig)
            if crc32(new) != e["crc32"]:
                raise ValueError("%s came out wrong (the patch is damaged)" % e["name"])
            files[e["name"]] = new
    texs = []
    if head["textures"]:
        origs = map_textures(data, {(t["name"], t["w"], t["h"]) for t in head["textures"]})
        for t in head["textures"]:
            orig = origs.get((t["name"], t["w"], t["h"], t["crc"]))
            if orig is None or crc32(orig) != t["base_crc32"]:
                continue
            new = xor(unpack(t), orig)
            if crc32(new) != t["crc32"]:
                raise ValueError("texture %s came out wrong (the patch is damaged)" % t["name"])
            texs.append((t["name"], t["w"], t["h"], t["crc"], new))
    if texs:
        files[TEXFILE] = texture_dat(texs)

    # write the files; remove what an earlier apply wrote and this one does not (nothing else in the folder)
    os.makedirs(out_dir, exist_ok=True)
    man = os.path.join(out_dir, MANIFEST)
    if os.path.isfile(man):
        for line in open(man).read().split("\n"):
            p = os.path.join(out_dir, line)
            if line and line not in files and os.path.isfile(p):
                os.remove(p)
    for name, b in files.items():
        p = os.path.join(out_dir, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b)
    with open(man, "w") as f:
        f.write("\n".join(sorted(files)) + "\n")
    nfiles = len(files) - (1 if texs else 0)
    log("qpe: %d of %d files and %d of %d map textures written to %s" % (
        nfiles, len(head["files"]), len(texs), len(head["textures"]), out_dir))
    for name in sorted(skipped):
        log("  skipped %s: %s" % (name, skipped[name]))
    return nfiles, skipped, len(texs), len(head["textures"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("apply", help="recreate the qpe folder from your Quake data")
    a.add_argument("args", nargs="+", metavar="[patch] data",
                   help="the patch (default: %s next to this program), then Quake's id1 folder or its pak files" % DEFAULT_PATCH)
    a.add_argument("-o", "--out", default="qpe", help="the folder to write (default: qpe)")
    a.add_argument("--all", action="store_true", help="fail unless every file and texture of the patch was applied")
    m = sub.add_parser("make", help="make the patch from a built qpe folder")
    m.add_argument("--qpe", required=True, help="the built mod (Source/qpe)")
    m.add_argument("data", nargs="+", help="the original data: id1 folder or pak files")
    m.add_argument("-o", "--out", default=DEFAULT_PATCH)
    o = ap.parse_args(argv)
    try:
        if o.cmd == "make":
            make(o.qpe, Data(o.data), o.out)
            return 0
        args = o.args
        if args[0].endswith(".qpatch") or (len(args) > 1 and os.path.isfile(args[0]) and not args[0].lower().endswith(".pak")):
            patch, srcs = args[0], args[1:]
        else:
            patch, srcs = os.path.join(HERE, DEFAULT_PATCH), args
        if not srcs:
            ap.error("give Quake's id1 folder or its pak files")
        n, skipped, t, tn = apply(patch, Data(srcs), o.out)
        if n == 0 and t == 0:
            print("nothing applied: is this Quake's data?", file=sys.stderr)
            return 1
        if o.all and (skipped or t != tn):
            print("not everything applied (--all)", file=sys.stderr)
            return 1
        return 0
    except (OSError, ValueError, lzma.LZMAError) as ex:
        print("qpepatch: %s" % ex, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
