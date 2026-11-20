"""The "Quake: Playdate Edition" (qpe) mod: where its art lives and how it becomes game files.

    mods/qpe/art/        the replacement art, PNG, edited by hand (git-ignored: derived from id's data)
    mods/qpe/orig/       the original art in the same layout, for reference (`qpe.py extract`, git-ignored)
    Source/qpe/          what the game loads with -game qpe (`qpe.py build`): gfx.wad, gfx/*.lmp, progs/*.mdl,
                         textures.dat

Art paths mirror the game file they replace:

    gfx.wad/<lump>.png           a picture in gfx.wad (conchars.png = the 128x128 font sheet)
    gfx/<name>.png               gfx/<name>.lmp
    progs/<model>.mdl/skin<N>.png            skin N of an alias model
    progs/<model>.mdl/skin<N>_<k>.png        picture k of skin group N
    textures/<name>.png          a texture of the maps (levels and item boxes), '*' written '#' (#water1.png)
    textures/<name>@<map>.png    the same name with other pixels in <map> and the maps that share them (sky4@dm3)

Textures go into textures.dat, not into copies of the maps (43 MB): Mod_LoadTextures (winquake/model.c) puts
their pixels over those of every map texture of the same name, size and original pixels. Only the full-size
picture is edited; build makes the three smaller mip levels the game draws further away (and at "Texture
detail: low", the Playdate default, everywhere: mip 1 is the most detail it draws).

A PNG is converted to palette indices as follows: an indexed PNG whose palette is Quake's (as written by
`extract` and `auto`) is used index for index; any other PNG is matched to the nearest palette colour.
Transparent pixels become the transparent index (0 in the font, 255 in pictures). Model skins never get
the fullbright colours 224-255 from colour matching (they would glow in the dark), only from an indexed PNG.
"""
import os

import struct

from quakefmt import GameFS, Wad, Mdl, qpic_decode, qpic_encode, png_read, png_write

TREE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SOURCE = os.path.join(TREE, "port", "boards", "playdate", "Source")
MOD = "qpe"
ART = os.path.join(TREE, "mods", MOD, "art")
ORIG = os.path.join(TREE, "mods", MOD, "orig")
OUT = os.path.join(SOURCE, MOD)
MANIFEST = "qpe-files.txt"      # in OUT: the files the last build wrote (removed by the next one)
TEXFILE = "textures.dat"        # in OUT: the replaced map textures (read by Mod_ReplaceTextures, model.c)

# gfx/*.lmp files that are not pictures
NOT_PICS = {"gfx/palette.lmp", "gfx/colormap.lmp", "gfx/pop.lmp"}     # pop.lmp: the registered check


def base_fs():
    return GameFS(SOURCE, ["id1"])


def palette(fs=None):
    fs = fs or base_fs()
    p = fs.read("gfx/palette.lmp")
    return [tuple(p[i * 3:i * 3 + 3]) for i in range(256)], p


# --------------------------------------------------------------------------- map textures

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
    """crc.c's CRC (CCITT, 0xffff start), which Mod_ReplaceTextures computes over a texture's pixels."""
    c = 0xffff
    t = _CRC
    for b in data:
        c = ((c << 8) & 0xffff) ^ t[(c >> 8) ^ b]
    return c


def bsp_textures(data):
    """The textures of a .bsp: [(index, name, w, h, mip0 pixels)]."""
    ofs, _ = struct.unpack_from("<ii", data, 4 + 2 * 8)        # LUMP_TEXTURES = 2
    count, = struct.unpack_from("<i", data, ofs)
    out = []
    for i in range(count):
        o, = struct.unpack_from("<i", data, ofs + 4 + 4 * i)
        if o == -1:
            continue
        mt = ofs + o
        name = data[mt:mt + 16].split(b"\0")[0].decode("latin-1")
        w, h = struct.unpack_from("<II", data, mt + 16)
        m0, = struct.unpack_from("<I", data, mt + 24)
        out.append((i, name, w, h, bytes(data[mt + m0:mt + m0 + w * h])))
    return out


def texture_file_name(name):
    return name.replace("*", "#")


_textures = {}


def textures(fs):
    """Every texture of the maps: [(art path, info)], info {name, w, h, pix (full-size pixels), maps (the .bsp
    files that have these pixels under this name), crc}. Cached while the paks stay the same."""
    key = tuple((p, os.path.getmtime(p), os.path.getsize(p)) for k, p, _ in fs.layers if k == "pak")
    key += tuple(n for n in fs.listing() if n.endswith(".bsp"))
    r = _textures.get(key)
    if r is not None:
        return r
    by_name = {}            # name -> {pixels+size: info}
    for n in sorted(x for x in fs.listing() if x.startswith("maps/") and x.endswith(".bsp")):
        for _, name, w, h, pix in bsp_textures(fs.read(n)):
            v = by_name.setdefault(name, {})
            info = v.get((w, h, pix))
            if info is None:
                info = v[(w, h, pix)] = {"name": name, "w": w, "h": h, "pix": pix, "maps": []}
            if n not in info["maps"]:
                info["maps"].append(n)
    out = []
    for name in sorted(by_name, key=lambda x: x.lower()):
        # the pixels most maps have get the plain name, the others the first map that has them
        vs = sorted(by_name[name].values(), key=lambda i: (-len(i["maps"]), i["maps"][0]))
        for k, info in enumerate(vs):
            info["crc"] = quake_crc(info["pix"])
            base = texture_file_name(name)
            if k:
                base += "@" + os.path.basename(info["maps"][0])[:-4]
            out.append(("textures/%s.png" % base, info))
    _textures.clear()
    _textures[key] = out
    return out


def mip_levels(pal, w, h, pix):
    """Mip levels 1-3 of a texture (what the game draws further away), each from the full-size picture: per
    block, the average LCD luminance (so a block of black and white pixels becomes the grey the Playdate
    dithers), in the most used palette row of the block (Quake's colour stays); fullbright where most of the
    block glows."""
    import autoart
    P = autoart.Pal(pal) if not isinstance(pal, autoart.Pal) else pal
    out = bytearray()
    for lv in (1, 2, 3):
        s = 1 << lv
        for by in range(0, h, s):
            for bx in range(0, w, s):
                blk = [pix[y * w + x] for y in range(by, by + s) for x in range(bx, bx + s)]
                fb = [c for c in blk if c >= 224]
                if len(fb) * 2 > len(blk):
                    out.append(max(set(fb), key=fb.count))
                    continue
                lit = [c for c in blk if c < 224]
                rows = [c >> 4 for c in lit]
                row = max(set(rows), key=rows.count)
                lum = sum(P.lum[c] for c in blk) / len(blk)
                ref = [c for c in lit if c >> 4 == row][0]
                out.append(autoart.in_ramp(P, lum, ref, 0, 224, black=True))
    return bytes(out)


def texture_dat(entries):
    """entries [(name, w, h, crc, pixels of all 4 mip levels)] -> textures.dat (layout: Mod_ReplaceTextures)."""
    head = b"QTEX" + struct.pack("<i", len(entries))
    pos = len(head) + 32 * len(entries)
    dir_, data = bytearray(), bytearray()
    for name, w, h, crc, pix in entries:
        dir_ += name.encode("latin-1")[:16].ljust(16, b"\0") + struct.pack("<4i", w, h, crc, pos + len(data))
        data += pix
    return head + bytes(dir_) + bytes(data)


def read_texture_dat(data):
    """textures.dat -> {(name, w, h, crc): full-size pixels}."""
    out = {}
    if data[:4] != b"QTEX":
        return out
    n, = struct.unpack_from("<i", data, 4)
    for i in range(n):
        e = 8 + 32 * i
        name = data[e:e + 16].split(b"\0")[0].decode("latin-1")
        w, h, crc, pos = struct.unpack_from("<4i", data, e + 16)
        out[(name, w, h, crc)] = data[pos:pos + w * h]
    return out


# --------------------------------------------------------------------------- what can be replaced

def anim_key(path):
    """The animation a map texture's picture is a frame of, or None: Quake animates textures named +0name ..
    +9name and, for a switch's other state, +aname .. +jname (Mod_LoadTextures)."""
    if not path.startswith("textures/+") or len(path) < 12:
        return None
    c = path[10].lower()
    if not ("0" <= c <= "9" or "a" <= c <= "j"):
        return None
    return path[11:]


def anim_order(path):
    """Sort key of a frame: the +0.. frames, then the alternate +a.. frames."""
    c = path[10].lower()
    return (c >= "a", c)


def assets(fs):
    """Every replaceable picture: [(art path, kind, info)]; kind 'font' | 'wad' | 'lmp' | 'skin' | 'texture'."""
    out = []
    wad = Wad(fs.read("gfx.wad"))
    for name, typ, comp, data in wad.lumps:
        if name.lower() == "conchars":
            out.append(("gfx.wad/conchars.png", "font", {"lump": name, "w": 128, "h": 128}))
        elif typ == 0x42:
            w, h, _ = qpic_decode(data)
            out.append(("gfx.wad/%s.png" % name.lower(), "wad", {"lump": name, "w": w, "h": h}))
    names = fs.listing()
    for n in names:
        if n.startswith("gfx/") and n.endswith(".lmp") and n not in NOT_PICS:
            w, h, _ = qpic_decode(fs.read(n))
            out.append(("gfx/%s.png" % n[4:-4], "lmp", {"file": n, "w": w, "h": h}))
    for n in names:
        if n.startswith("progs/") and n.endswith(".mdl"):
            m = Mdl(fs.read(n))
            for si, g in enumerate(m.skins):
                for k in range(len(g)):
                    p = "%s/skin%d%s.png" % (n, si, "_%d" % k if len(g) > 1 else "")
                    out.append((p, "skin", {"file": n, "skin": si, "pic": k, "w": m.skinwidth, "h": m.skinheight}))
    for p, info in textures(fs):
        out.append((p, "texture", info))
    return out


def original_pixels(fs, kind, info):
    if kind == "texture":
        prev = getattr(fs, "texture", None)
        return (prev and prev(info)) or info["pix"]
    if kind == "font":
        return Wad(fs.read("gfx.wad")).get(info["lump"])[3][:128 * 128]
    if kind == "wad":
        return qpic_decode(Wad(fs.read("gfx.wad")).get(info["lump"])[3])[2]
    if kind == "lmp":
        return qpic_decode(fs.read(info["file"]))[2]
    m = Mdl(fs.read(info["file"]))
    return m.skins[info["skin"]][info["pic"]][1]


def transparent_index(kind):
    return {"font": 0, "wad": 255, "lmp": 255, "skin": None, "texture": None}[kind]


def extract(dest=ORIG, log=print):
    """Write the original art (indexed PNG, Quake palette) in the art layout."""
    fs = base_fs()
    _, pal = palette(fs)
    n = 0
    for path, kind, info in assets(fs):
        f = os.path.join(dest, path)
        os.makedirs(os.path.dirname(f), exist_ok=True)
        png_write(f, info["w"], info["h"], original_pixels(fs, kind, info), pal, transparent_index(kind))
        n += 1
    log("extract: %d pictures -> %s" % (n, os.path.relpath(dest, TREE)))


# --------------------------------------------------------------------------- PNG -> palette indices

class Matcher:
    def __init__(self, pal):
        self.pal = pal
        self.cache = {}

    def nearest(self, rgb, allowed):
        key = (rgb, allowed)
        r = self.cache.get(key)
        if r is not None:
            return r
        best, bd = 0, 1 << 30
        lo, hi = allowed
        for i in range(lo, hi):
            p = self.pal[i]
            dr, dg, db = rgb[0] - p[0], rgb[1] - p[1], rgb[2] - p[2]
            d = 3 * dr * dr + 4 * dg * dg + 2 * db * db
            if d < bd:
                best, bd = i, d
                if d == 0:
                    break
        self.cache[key] = best
        return best


def art_to_indices(path, kind, w, h, pal, matcher, previous=None):
    """-> (indices, as_is): as_is is False when the PNG does not show what the game will draw (it is not
    indexed with Quake's palette, or its transparency differs from the game's), so build rewrites it.
    previous: a function returning the picture's indices as last built (else id1's); of the palette's
    duplicate colours (black is 0 and 48, ...) a pixel keeps the index it had there, since an RGB file cannot
    say which one was meant (the palette row picks the dither pattern in the 3D view)."""
    pw, ph, mode, data, ppal, alpha = png_read(path)
    if (pw, ph) != (w, h):
        raise ValueError("%s is %dx%d, the original is %dx%d (the size must stay)" % (path, pw, ph, w, h))
    trans = transparent_index(kind)
    # colours colour-matching may pick: no transparent index, no fullbrights on skins
    if kind == "font":
        allowed = (1, 256)
    elif kind in ("skin", "texture"):
        allowed = (0, 224)
    else:
        allowed = (0, 255)
    out = bytearray(w * h)
    if mode == "P" and ppal and all(tuple(ppal[i]) == pal[i] for i in range(min(len(ppal), 256))):
        # indexed with Quake's palette: exact
        for i, c in enumerate(data):
            out[i] = trans if (trans is not None and alpha[c] < 128) else c
        # as drawn by the game: every pixel opaque, but the transparent index fully transparent
        as_is = out == data and all(alpha[c] == (0 if c == trans else 255) for c in set(data))
        return bytes(out), as_is
    if mode == "P":
        rgba = bytearray()
        for c in data:
            rgba += bytes(ppal[c]) + bytes((alpha[c],))
        data = bytes(rgba)
    exact = {pal[i]: i for i in range(255, -1, -1)}
    prev = previous() if previous else None
    for i in range(w * h):
        r, g, b, a = data[i * 4:i * 4 + 4]
        if trans is not None and a < 128:
            out[i] = trans
            continue
        e = exact.get((r, g, b))
        # a colour of the palette stays that index (a skin's fullbrights too: they were picked from the
        # palette or the original); only approximate colours are matched, and those never become fullbright
        if e is not None and prev is not None and pal[prev[i]] == (r, g, b) and prev[i] != trans:
            out[i] = prev[i]
        elif e is not None and e != trans:
            out[i] = e
        else:
            out[i] = matcher.nearest((r, g, b), allowed)
    return bytes(out), False


# --------------------------------------------------------------------------- build

class _Built:
    """The files of the previous build in out, over id1 (read like a GameFS)."""

    def __init__(self, out, fs):
        self.out, self.fs = out, fs
        self.tex = None

    def texture(self, info):
        """A map texture's pixels as last built, or None."""
        if self.tex is None:
            p = os.path.join(self.out, TEXFILE)
            self.tex = read_texture_dat(open(p, "rb").read()) if os.path.isfile(p) else {}
        return self.tex.get((info["name"], info["w"], info["h"], info["crc"]))

    def read(self, name):
        p = os.path.join(self.out, name)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                return f.read()
        return self.fs.read(name)


def build(art=ART, out=OUT, log=print):
    """mods/qpe/art -> Source/qpe. Returns the list of files written (relative to out)."""
    fs = base_fs()
    pal, palbytes = palette(fs)
    matcher = Matcher(pal)
    built = _Built(out, fs)
    index = {p: (k, i) for p, k, i in assets(fs)}
    arts = []
    for root, _, files in os.walk(art):
        for fn in files:
            if fn.lower().endswith(".png"):
                rel = os.path.relpath(os.path.join(root, fn), art).replace(os.sep, "/")
                arts.append(rel)
    arts.sort()
    wad = None
    lmps = {}
    mdls = {}
    texs = []
    unknown = []
    rewritten = []
    for rel in arts:
        if rel not in index:
            unknown.append(rel)
            continue
        kind, info = index[rel]
        src = os.path.join(art, rel)
        pix, as_is = art_to_indices(src, kind, info["w"], info["h"], pal, matcher,
                                    lambda: original_pixels(built, kind, info))
        if not as_is:
            # saved as RGB (or with another palette or alpha) by an editor: write it back as the game will
            # draw it, indexed with Quake's palette, so the file shows the colours the game uses
            png_write(src, info["w"], info["h"], pix, palbytes, transparent_index(kind))
            rewritten.append(rel)
        if kind in ("font", "wad"):
            if wad is None:
                wad = Wad(fs.read("gfx.wad"))
            lump = wad.get(info["lump"])
            lump[3] = pix + lump[3][len(pix):] if kind == "font" else qpic_encode(info["w"], info["h"], pix)
        elif kind == "lmp":
            lmps[info["file"]] = qpic_encode(info["w"], info["h"], pix)
        elif kind == "texture":
            if pix != info["pix"]:      # (an unchanged copy of the original needs no entry)
                texs.append((info["name"], info["w"], info["h"], info["crc"],
                             pix + mip_levels(pal, info["w"], info["h"], pix)))
        else:
            m = mdls.get(info["file"])
            if m is None:
                m = mdls[info["file"]] = Mdl(fs.read(info["file"]))
            g = m.skins[info["skin"]]
            g[info["pic"]] = (g[info["pic"]][0], pix)
    files = {}
    if wad is not None:
        files["gfx.wad"] = wad.to_bytes()
    files.update(lmps)
    for n, m in mdls.items():
        files[n] = m.to_bytes()
    if texs:
        files[TEXFILE] = texture_dat(texs)

    # replace the previous build's files, nothing else in the folder
    os.makedirs(out, exist_ok=True)
    man = os.path.join(out, MANIFEST)
    if os.path.exists(man):
        for line in open(man).read().split("\n"):
            if line and line not in files:
                p = os.path.join(out, line)
                if os.path.isfile(p):
                    os.remove(p)
    for n, data in files.items():
        p = os.path.join(out, n)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if os.path.exists(p) and open(p, "rb").read() == data:
            continue
        tmp = p + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, p)
    with open(man, "w") as f:
        f.write("\n".join(sorted(files)) + "\n")
    for r in rewritten:
        log("build: %s rewritten as an indexed PNG with Quake's palette (the colours the game draws)" % r)
    for u in unknown:
        log("build: %s replaces nothing (no such picture in id1), skipped" % u)
    log("build: %d pictures -> %d files in %s%s" % (len(arts) - len(unknown), len(files), os.path.relpath(out, TREE),
                                                 " (%d map textures)" % len(texs) if texs else ""))
    return sorted(files)
