"""The Mote editor of the qpe viewer: runs Mote (tools/qpe/mote: oh4_halftone.h by Eric Scrivner, the library of
https://mote.oh4.co) on a qpe picture and turns its 1-bit (or 4-level) result into qpe art.

Mote decides black or white for each pixel, or with 4 levels black, dark grey, light grey or white. The pixel then
gets a palette colour the Playdate draws as that level: for black and white one whose LCD luminance is exactly 0 or
255 (so the Playdate draws exactly Mote's pixels, at any dithering setting), for a grey one in the same step of the
4x4 Bayer dither and of the 3D view's 2x2 patterns as the grey's level (see lcd_class), so it makes the same pattern.
By default the colour is a shade of the pixel's own palette row (the picture keeps Quake's colours), else the closest
colour drawn as that level. With colours "grey" every pixel is from the grey row instead.

Every save records its settings for that picture in art/mote.json (settings(), remember()); batch() converts many
pictures with one set of settings.
"""
import base64
import ctypes
import json
import os
import subprocess
import sys
import threading
import time

from quakefmt import gamma_lut, png_write
import autoart
import qpemod

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "mote")
LIB = os.path.join(HERE, "out", "libmote" + (".dylib" if sys.platform == "darwin" else ".so"))

# gray mode 4 (added here, not in Mote): the luminance display.c dithers with (its curve brightens Quake's dark
# palette a lot), so that Mote starts from what the Playdate shows; done in Python, Mote then gets grey pixels
GRAY_LCD = 4

# mote.c's p[] order, with mote.oh4.co's defaults (but gray: the Playdate's luminance)
PARAMS = [("gray", GRAY_LCD), ("wr", 0.299), ("wg", 0.587), ("wb", 0.114),
          ("lift", 0.0), ("gain", 1.0), ("contrast", 1.0), ("gamma", 1.0), ("threshold", 128), ("invert", 0),
          ("sharpen", 0.0), ("radius", 1),
          ("edge", 0), ("edge_strength", 0.5),
          ("ordered", 0), ("bayer", 2), ("ordered_scale", 0.0),
          ("diffusion", 0), ("diffusion_strength", 1.0), ("serpentine", 1),
          ("levels", 2), ("dark", 64), ("light", 192)]     # qpe: 4 levels (black, dark grey, light grey, white)

SETTINGS = os.path.join(qpemod.ART, "mote.json")

_lock = threading.Lock()
_lib = None
_index = None
_pal = None


def build_lib():
    """(Re)build out/libmote when it is older than mote.c or oh4_halftone.h."""
    srcs = [os.path.join(SRC, f) for f in ("mote.c", "oh4_halftone.h")]
    if os.path.exists(LIB) and all(os.path.getmtime(LIB) > os.path.getmtime(s) for s in srcs):
        return
    os.makedirs(os.path.dirname(LIB), exist_ok=True)
    subprocess.check_call([os.environ.get("CC", "cc"), "-O2", "-shared", "-fPIC", "-o", LIB, srcs[0], "-lm"])


def lib():
    global _lib
    if _lib is None:
        build_lib()
        _lib = ctypes.CDLL(LIB)
        _lib.mote_run.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_float),
                                  ctypes.c_char_p]
        if _lib.mote_param_count() != len(PARAMS):
            raise RuntimeError("mote.c and moteart.PARAMS disagree")
    return _lib


def lcd_grey(rgba):
    """RGBA -> RGBA in grey, the luminance display.c dithers with."""
    g = gamma_lut()
    out = bytearray(rgba)
    for i in range(0, len(out), 4):
        v = g[(77 * out[i] + 151 * out[i + 1] + 28 * out[i + 2]) >> 8]
        out[i] = out[i + 1] = out[i + 2] = v
    return bytes(out)


def levels(params):
    """The LCD luminance of each output level: [0, 255], or with 4 levels [0, dark, light, 255] (as mote.c
    clamps them)."""
    if int(params.get("levels", 2)) != 4:
        return [0, 255]
    d = min(253, max(1, int(round(float(params.get("dark", 64))))))
    l = int(round(float(params.get("light", 192))))
    l = d + 1 if l <= d else min(254, l)
    return [0, d, l, 255]


def lcd_class(l):
    """What the Playdate draws for LCD luminance l: (how many of the 16 cells of the 4x4 Bayer tile are white,
    the 3D view's 2x2 pattern level), from display.c (bayer_tile = bayer4 * 16 + 8; lv = (lum * 4 + 128) >> 8).
    Colours of one class are drawn alike in the patterns and Bayer modes."""
    return (sum(1 for k in range(16) if l > 16 * k + 8), (l * 4 + 128) >> 8)


def run(rgba, w, h, params):
    """Mote on w*h RGBA pixels -> w*h bytes, the level index (0 black .. len(levels) - 1 white)."""
    params = dict(params)
    if int(params.get("gray", GRAY_LCD)) == GRAY_LCD:
        rgba = lcd_grey(rgba)
        params["gray"] = 0
    p = (ctypes.c_float * len(PARAMS))(*[float(params.get(k, d)) for k, d in PARAMS])
    out = ctypes.create_string_buffer(w * h)
    with _lock:
        if lib().mote_run(bytes(rgba), w, h, p, out) != 0:
            raise MemoryError("mote: out of memory")
    return out.raw


def _assets():
    global _index, _pal
    if _index is None:
        fs = qpemod.base_fs()
        _pal = autoart.Pal(qpemod.palette(fs)[0])
        _index = {p: (k, i) for p, k, i in qpemod.assets(fs)}
    return _index, _pal


def colour_range(kind):
    """The indices a picture of this kind may use: not its transparent index, no fullbrights on skins and map
    textures (only the pixels that glow in the original glow, see edit)."""
    return {"font": (1, 256), "skin": (0, 224), "texture": (0, 224)}.get(kind, (0, 255))


FULLBRIGHT = 224     # palette indices 224-255 glow: the same in every light level of the colormap (pdr_light.c)


def glow_kind(kind):
    """Skins and map textures are lit, so their fullbright colours glow; pictures of the UI are not lit."""
    return kind in ("skin", "texture")


def emissive_colour(P, orig, src, rgb):
    """The colour of a pixel that glows in the original: the source's own fullbright colour (art painted with
    one), the closest fullbright colour to an opened image's pixel (rgb), else the original's colour."""
    if src >= FULLBRIGHT:
        return src
    if rgb is None:
        return orig
    key = ("glow", rgb)
    r = P.cache.get(key)
    if r is None:
        r = P.cache[key] = min(range(FULLBRIGHT, 256), key=lambda i: sum((a - b) ** 2 for a, b in zip(P.pal[i], rgb)))
    return r


def exact_colour(P, target, orig, lo, hi, grey=False):
    """A colour the LCD draws as level target: LCD luminance exactly 0 / 255 for black / white, the same lcd_class
    for a grey. The shade of orig's palette row closest in colour to orig (the grey row with grey), else pure black
    (48), else the closest such colour of the palette, else the closest luminance."""
    key = ("exact", target, orig, lo, hi, grey)
    r = P.cache.get(key)
    if r is None:
        if target in (0, 255):
            ok = lambda i: P.lum[i] == target       # noqa: E731
        else:
            cls = lcd_class(target)
            ok = lambda i: lcd_class(P.lum[i]) == cls   # noqa: E731
        base = 0 if grey else orig & ~15
        ref = (target, target, target) if grey else P.pal[orig]
        dist = lambda i: sum((a - b) ** 2 for a, b in zip(P.pal[i], ref))  # noqa: E731
        row = [i for i in range(base, base + 16) if lo <= i < hi and ok(i)]
        if row:
            r = min(row, key=lambda i: (dist(i), abs(P.lum[i] - target)))
        elif target == 0 and lo <= 48 < hi:
            r = 48
        else:
            cands = [i for i in range(lo, hi) if ok(i)]
            r = min(cands, key=dist) if cands else P.pick(target, orig, lo, hi, tol=0)
        P.cache[key] = r
    return r


def source(path, src, image=None):
    """The picture Mote starts from -> (kind, w, h, rgba, indices): src 'orig' (id1's), 'art' (the qpe art, else
    the original) or 'image' (image: base64 RGBA of w*h pixels, e.g. a picture opened in the editor; its indices
    are the closest palette colours, for the colour rows)."""
    index, P = _assets()
    if path not in index:
        raise KeyError("no such picture: %s" % path)
    kind, info = index[path]
    w, h = info["w"], info["h"]
    trans = qpemod.transparent_index(kind)
    if src == "image":
        rgba = base64.b64decode(image)
        if len(rgba) != w * h * 4:
            raise ValueError("the image must be %dx%d RGBA" % (w, h))
        m = qpemod.Matcher(P.pal)
        rng = colour_range(kind)
        idx = bytes(m.nearest(tuple(rgba[i * 4:i * 4 + 3]), rng) for i in range(w * h))
        return kind, w, h, rgba, idx
    art = os.path.join(qpemod.ART, path)
    if src == "art" and os.path.isfile(art):
        idx, _ = qpemod.art_to_indices(art, kind, w, h, P.pal, qpemod.Matcher(P.pal))
    else:
        idx = qpemod.original_pixels(qpemod.base_fs(), kind, info)
    rgba = bytearray(w * h * 4)
    for i, c in enumerate(idx):
        rgba[i * 4:i * 4 + 3] = bytes(P.pal[c])
        rgba[i * 4 + 3] = 0 if c == trans else 255
    return kind, w, h, bytes(rgba), bytes(idx)


def settings(path=None):
    """The settings each picture was last saved with: {path: {params, colours, alpha, source, time}} (or one)."""
    try:
        with open(SETTINGS) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    return data.get(path) if path else data


def remember(paths, body):
    """Record body's settings as the ones paths were saved with."""
    with _lock:
        data = settings()
        rec = {"params": {k: body.get("params", {}).get(k, d) for k, d in PARAMS},
               "colours": body.get("colours", "quake"), "alpha": bool(body.get("alpha", True)),
               "source": body.get("picked") or body.get("source", "orig"),
               "time": time.strftime("%Y-%m-%d %H:%M:%S")}
        for p in paths:
            data[p] = rec
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        tmp = SETTINGS + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.replace(tmp, SETTINGS)


def edit(body, record=True):
    """/api/mote: body {path, source, image?, params, colours ('quake' | 'grey'), alpha (keep the transparent
    pixels), save, picked (the source as the editor shows it, for the record)}. -> (head, bits, opaque, indices):
    what the art would be, bits the level of each pixel; with save it is written to art/ and its settings to
    mote.json."""
    path = body["path"]
    src = body.get("source", "orig")
    kind, w, h, rgba, idx = source(path, src, body.get("image"))
    # the pixels that glow in the original keep glowing (whatever the source): fullbright colours on lit pictures
    orig = None
    if glow_kind(kind):
        orig = idx if src == "orig" else qpemod.original_pixels(qpemod.base_fs(), kind, _assets()[0][path][1])
    params = body.get("params", {})
    bits = run(rgba, w, h, params)
    values = levels(params)
    _, P = _assets()
    trans = qpemod.transparent_index(kind)
    keep_alpha = body.get("alpha", True) and trans is not None
    grey = body.get("colours") == "grey"
    lo, hi = colour_range(kind)
    out = bytearray(w * h)
    opaque = bytearray(w * h)      # 0 transparent, 1 a level of the result, 2 a glowing pixel kept as it is
    glowing = 0
    for i in range(w * h):
        if keep_alpha and rgba[i * 4 + 3] < 128:
            out[i] = trans
            continue
        opaque[i] = 1
        c = idx[i]
        if orig is not None and orig[i] >= FULLBRIGHT:
            out[i] = emissive_colour(P, orig[i], c, tuple(rgba[i * 4:i * 4 + 3]) if src == "image" else None)
            opaque[i] = 2
            glowing += 1
            continue
        level = values[bits[i]]
        if c == trans or not lo <= c < hi:
            c = 15                      # the transparent index as a visible pixel: from the grey row
        out[i] = exact_colour(P, level, c, lo, hi, grey)
    head = {"w": w, "h": h, "kind": kind, "saved": False, "levels": values, "glowing": glowing}
    if body.get("save"):
        dest = os.path.join(qpemod.ART, path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        png_write(dest, w, h, bytes(out), qpemod.palette()[1], trans)
        head["saved"] = True
        if record:
            remember([path], body)
    return head, bits, bytes(opaque), bytes(out)


def batch(body):
    """/api/mote/batch: body {paths, source ('orig' | 'art': the qpe art where there is one), params, colours,
    alpha}: converts and saves every picture with these settings. -> {saved: [paths], errors: {path: message}}."""
    saved, errors = [], {}
    for path in body.get("paths", []):
        one = dict(body, path=path, save=True, image=None, picked=body.get("source", "orig"))
        try:
            edit(one, record=False)
            saved.append(path)
        except (KeyError, ValueError, MemoryError) as ex:
            errors[path] = str(ex)
    if saved:
        remember(saved, dict(body, picked=body.get("source", "orig")))
    return {"saved": saved, "errors": errors}
