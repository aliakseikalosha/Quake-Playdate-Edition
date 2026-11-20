"""Quake data formats for the QPE tools: PAK, WAD2, qpic/.lmp, MDL skins, SPR, and 8-bit PNG files.
Standard library only.

Every picture here is (width, height, bytes of palette indices), row-major.
"""
import os
import struct
import zlib

# --------------------------------------------------------------------------- game folders


class GameFS:
    """Quake's search path: the files of a game folder over those of the folders below it.

    `dirs` lowest priority first, e.g. ["id1"] or ["id1", "qpe"]. In each folder pak0.pak, pak1.pak, ...
    are read, and loose files beat every pak of the same folder, as in COM_AddGameDirectory.
    """

    def __init__(self, basedir, dirs):
        self.layers = []    # highest priority first: (kind, path, index)
        for d in dirs:
            path = os.path.join(basedir, d)
            paks = []
            i = 0
            while os.path.exists(os.path.join(path, "pak%d.pak" % i)):
                paks.append(os.path.join(path, "pak%d.pak" % i))
                i += 1
            for p in paks:
                self.layers.insert(0, ("pak", p, read_pak_index(p)))
            if os.path.isdir(path):
                self.layers.insert(0, ("dir", path, None))

    def find(self, name):
        for kind, path, index in self.layers:
            if kind == "pak":
                if name in index:
                    return (kind, path, index[name])
            else:
                f = os.path.join(path, name)
                if os.path.isfile(f):
                    return (kind, f, None)
        return None

    def read(self, name):
        r = self.find(name)
        if r is None:
            raise KeyError(name)
        kind, path, ent = r
        if kind == "dir":
            with open(path, "rb") as f:
                return f.read()
        with open(path, "rb") as f:
            f.seek(ent[0])
            return f.read(ent[1])

    def exists(self, name):
        return self.find(name) is not None

    def listing(self):
        names = set()
        for kind, path, index in self.layers:
            if kind == "pak":
                names.update(index)
            else:
                for root, _, files in os.walk(path):
                    for fn in files:
                        rel = os.path.relpath(os.path.join(root, fn), path).replace(os.sep, "/")
                        names.add(rel)
        return sorted(names)


def read_pak_index(path):
    with open(path, "rb") as f:
        magic, ofs, ln = struct.unpack("<4sii", f.read(12))
        if magic != b"PACK":
            raise ValueError("%s: not a pak" % path)
        f.seek(ofs)
        d = f.read(ln)
    out = {}
    for i in range(ln // 64):
        name, pos, size = struct.unpack_from("<56sii", d, i * 64)
        out[name.split(b"\0")[0].decode("latin-1")] = (pos, size)
    return out


# --------------------------------------------------------------------------- palette / LCD luminance

# port/boards/playdate/display.c: luminance = (77 r + 151 g + 28 b) >> 8, stretched from
# BLACK_POINT..WHITE_POINT to 0..255, then gamma 0.8. Keep in step with display.c.
BLACK_POINT = 4.0
WHITE_POINT = 120.0
GAMMA = 0.8


def gamma_lut():
    out = []
    for i in range(256):
        v = (i - BLACK_POINT) / (WHITE_POINT - BLACK_POINT)
        v = 0.0 if v < 0 else (1.0 if v > 1 else v)
        out.append(int(255.0 * v ** GAMMA + 0.5))
    return out


def lcd_lum(palette):
    """Palette (768 bytes) -> the 256 luminances display.c dithers with."""
    g = gamma_lut()
    return [g[(77 * palette[i * 3] + 151 * palette[i * 3 + 1] + 28 * palette[i * 3 + 2]) >> 8] for i in range(256)]


# --------------------------------------------------------------------------- WAD2 (gfx.wad)

TYP_QPIC = 0x42


class Wad:
    def __init__(self, data):
        magic, n, ofs = struct.unpack_from("<4sii", data, 0)
        if magic != b"WAD2":
            raise ValueError("not a WAD2 file")
        self.lumps = []     # [name, type, compression, bytes]
        for i in range(n):
            pos, disk, size, typ, comp, _, _, name = struct.unpack_from("<iiibbbb16s", data, ofs + i * 32)
            self.lumps.append([name.split(b"\0")[0].decode("latin-1"), typ & 0xff, comp, data[pos:pos + disk]])

    def get(self, name):
        for l in self.lumps:
            if l[0].lower() == name.lower():
                return l
        return None

    def to_bytes(self):
        body = bytearray(b"\0" * 12)
        infos = []
        for name, typ, comp, data in self.lumps:
            pos = len(body)
            body += data
            while len(body) % 4:
                body += b"\0"
            infos.append(struct.pack("<iiibbbb16s", pos, len(data), len(data), typ if typ < 128 else typ - 256,
                                     comp, 0, 0, name.encode("latin-1")))
        ofs = len(body)
        for i in infos:
            body += i
        struct.pack_into("<4sii", body, 0, b"WAD2", len(infos), ofs)
        return bytes(body)


def qpic_decode(data):
    w, h = struct.unpack_from("<ii", data, 0)
    return w, h, bytes(data[8:8 + w * h])


def qpic_encode(w, h, pix):
    return struct.pack("<ii", w, h) + bytes(pix)


# --------------------------------------------------------------------------- MDL skins

MDL_HEADER = struct.Struct("<4si3f3ff3f8if")    # ident ... flags, size: 84 bytes


class Mdl:
    """Skins of an alias model; everything after them is kept as it was."""

    def __init__(self, data):
        h = MDL_HEADER.unpack_from(data, 0)
        if h[0] != b"IDPO" or h[1] != 6:
            raise ValueError("not an IDPO v6 model")
        self.head = bytearray(data[:MDL_HEADER.size])
        self.scale = h[2:5]
        self.translate = h[5:8]
        self.radius = h[8]
        self.numskins, self.skinwidth, self.skinheight, self.numverts, self.numtris, self.numframes = h[12:18]
        self.flags = h[19]
        p = MDL_HEADER.size
        n = self.skinwidth * self.skinheight
        self.skins = []     # each: list of (interval or None, pixels); a group has several
        for _ in range(self.numskins):
            t, = struct.unpack_from("<i", data, p)
            p += 4
            if t == 0:
                self.skins.append([(None, bytes(data[p:p + n]))])
                p += n
            else:
                cnt, = struct.unpack_from("<i", data, p)
                p += 4
                iv = struct.unpack_from("<%df" % cnt, data, p)
                p += 4 * cnt
                g = []
                for k in range(cnt):
                    g.append((iv[k], bytes(data[p:p + n])))
                    p += n
                self.skins.append(g)
        self.rest = bytes(data[p:])
        self._frames = None

    def to_bytes(self):
        out = bytearray(self.head)
        for g in self.skins:
            if len(g) == 1 and g[0][0] is None:
                out += struct.pack("<i", 0) + g[0][1]
            else:
                out += struct.pack("<ii", 1, len(g))
                out += struct.pack("<%df" % len(g), *[iv if iv is not None else 0.1 for iv, _ in g])
                for _, pix in g:
                    out += pix
        return bytes(out + self.rest)

    def frames(self):
        """[(name, mins, maxs)] for every frame (the first frame of a group stands for it)."""
        if self._frames is not None:
            return self._frames
        d = self.rest
        p = self.numverts * 12 + self.numtris * 16
        nv = self.numverts
        out = []

        def box(lo, hi):
            return ([lo[i] * self.scale[i] + self.translate[i] for i in range(3)],
                    [hi[i] * self.scale[i] + self.translate[i] for i in range(3)])
        for _ in range(self.numframes):
            t, = struct.unpack_from("<i", d, p)
            p += 4
            if t == 0:
                lo, hi = d[p:p + 3], d[p + 4:p + 7]
                name = d[p + 8:p + 24].split(b"\0")[0].decode("latin-1")
                p += 24 + nv * 4
                out.append((name, *box(lo, hi)))
            else:
                cnt, = struct.unpack_from("<i", d, p)
                lo, hi = d[p + 4:p + 7], d[p + 8:p + 11]
                p += 12 + 4 * cnt
                first = None
                for _k in range(cnt):
                    name = d[p + 8:p + 24].split(b"\0")[0].decode("latin-1")
                    first = first or name
                    p += 24 + nv * 4
                out.append((first + "*", *box(lo, hi)))
        self._frames = out
        return out


def spr_info(data):
    """(numframes, maxwidth, maxheight) of a sprite."""
    ident, ver, typ, radius, mw, mh, nframes = struct.unpack_from("<4siif2ii", data, 0)
    return nframes, mw, mh


def bsp_box(data):
    """mins, maxs of a brush model's first submodel."""
    ver, = struct.unpack_from("<i", data, 0)
    ofs, ln = struct.unpack_from("<ii", data, 4 + 14 * 8)    # LUMP_MODELS = 14
    v = struct.unpack_from("<6f", data, ofs)
    return list(v[0:3]), list(v[3:6])


# --------------------------------------------------------------------------- PNG

def _chunk(t, d):
    return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)


def png_write(path, w, h, pix, palette, transparent=None):
    """8-bit indexed PNG with the Quake palette; `transparent`: the index to mark fully transparent."""
    out = png_encode(w, h, pix, palette, transparent)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(out)
    os.replace(tmp, path)


def png_encode(w, h, pix, palette, transparent=None):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += pix[y * w:(y + 1) * w]
    out = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0))
    out += _chunk(b"PLTE", bytes(palette[:768]))
    if transparent is not None:
        out += _chunk(b"tRNS", b"\xff" * transparent + b"\x00")
    out += _chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + _chunk(b"IEND", b"")
    return out


def png_read(path):
    """-> (w, h, mode, data, palette, trns): mode 'P' (data = indices, palette = list of (r,g,b), trns =
    list of alpha per index) or 'RGBA' (data = 4 bytes per pixel)."""
    with open(path, "rb") as f:
        b = f.read()
    if b[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("%s: not a PNG" % path)
    p = 8
    idat = bytearray()
    plte = None
    trns = None
    while p < len(b):
        n, = struct.unpack_from(">I", b, p)
        t = b[p + 4:p + 8]
        d = b[p + 8:p + 8 + n]
        p += 12 + n
        if t == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", d)
        elif t == b"PLTE":
            plte = [tuple(d[i:i + 3]) for i in range(0, len(d), 3)]
        elif t == b"tRNS":
            trns = d
        elif t == b"IDAT":
            idat += d
        elif t == b"IEND":
            break
    if interlace:
        raise ValueError("%s: interlaced PNGs are not supported (save it without interlacing)" % path)
    chans = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    if depth == 16:
        bpp = chans * 2
    elif depth == 8:
        bpp = chans
    else:
        if ctype not in (0, 3):
            raise ValueError("%s: unsupported bit depth" % path)
        bpp = 1
    stride = (w * chans * depth + 7) // 8
    raw = zlib.decompress(bytes(idat))
    rows = []
    prev = bytearray(stride)
    q = 0
    for y in range(h):
        ft = raw[q]
        line = bytearray(raw[q + 1:q + 1 + stride])
        q += 1 + stride
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            c = prev[i - bpp] if i >= bpp else 0
            up = prev[i]
            if ft == 1:
                line[i] = (line[i] + a) & 255
            elif ft == 2:
                line[i] = (line[i] + up) & 255
            elif ft == 3:
                line[i] = (line[i] + ((a + up) >> 1)) & 255
            elif ft == 4:
                pa, pb, pc = abs(up - c), abs(a - c), abs(a + up - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (up if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        rows.append(line)
        prev = line

    def samples(line):
        if depth == 8:
            return line
        if depth == 16:
            return line[0::2]
        per = 8 // depth
        mask = (1 << depth) - 1
        out = bytearray()
        for byte in line:
            for k in range(per):
                out.append((byte >> (8 - depth * (k + 1))) & mask)
        return out[:w * chans]

    if ctype == 3:
        data = bytearray()
        for r in rows:
            data += samples(r)[:w]
        alpha = [255] * 256
        if trns:
            for i, a in enumerate(trns):
                alpha[i] = a
        return w, h, "P", bytes(data), plte, alpha
    data = bytearray()
    scale = 255 // ((1 << depth) - 1) if depth < 8 else 1
    tkey = None
    if trns and ctype == 0:
        tkey = struct.unpack(">H", trns[:2])[0]
    if trns and ctype == 2:
        tkey = struct.unpack(">HHH", trns[:6])
    for r in rows:
        s = samples(r)
        for x in range(w):
            if ctype == 0:
                g = s[x]
                data += bytes((g * scale,) * 3 + ((0 if tkey == g else 255),))
            elif ctype == 4:
                data += bytes((s[2 * x],) * 3 + (s[2 * x + 1],))
            elif ctype == 2:
                px = tuple(s[3 * x:3 * x + 3])
                data += bytes(px + ((0 if tkey == px else 255),))
            else:
                data += bytes(s[4 * x:4 * x + 4])
    return w, h, "RGBA", bytes(data), None, None
