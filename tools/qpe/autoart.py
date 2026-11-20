"""`qpe.py auto`: a first, automatic pass of the qpe art, made from the original pictures for the 1-bit LCD.

Every rule works on the luminance the Playdate dithers with (quakefmt.lcd_lum, display.c's curve): it decides the
LCD level of each pixel, and the pixel then gets the shade of its OWN palette row (16 shades of one colour) closest
to that level, so the pictures keep Quake's colours and only their brightness changes. For black, pure black
(index 48) may be used. A skin texel whose row cannot reach a level gets the row's closest shade; a UI pixel gets
the closest colour that does reach it (the UI must stay readable).

  font       the lit face of each letter -> its brightest shade, its shadow -> black (index 0 is transparent);
             the graphics glyphs (rows 0 and 8 of the sheet) -> the picture rule
  pictures   contrast stretch + unsharp mask, then 5 levels that the 4x4 Bayer dither draws as clean
             patterns (0, 25, 50, 75, 100 % white)
  backgrounds (status bar, console, tiles, box fill) -> mostly black with a sparse 25 % texture, so that what
             is drawn over them (numbers, text) stands out
  big numbers  NUM_*: bright digit on black; ANUM_* (low health/ammo): dark digit on a bright box
  --mono-ui  the UI rules above with any palette colour of the level, closest to the original, instead of the
             pixel's own row: a white font, grey-white digits (the first version of qpe)
  model skins  3x3 median (the speckle of the originals becomes noise on the LCD), contrast stretch, the darkest
             texels black, the rest lifted to the upper levels, each texel staying in its own palette row: the
             same colours as Quake, lit and patterned as before (a row that cannot reach a level gets its
             closest shade). --grey-skins puts every level in the grey row instead (one 2x2 pattern per level,
             grey in colour). Fullbright texels (glowing eyes etc.) are kept.
  --textures the textures of the maps, with the model skin rule (they are lit by the level the same way); not
             made without it, as hand-made level art is the slower part and a first pass of 582 textures would
             replace the whole look of the levels at once

The results are a starting point to edit by hand; `auto` only writes pictures that are not in art/ yet
(--force replaces them).
"""
import os

from quakefmt import lcd_lum, png_write
import qpemod

LEVELS5 = (0, 64, 128, 192, 255)    # 4x4 Bayer: 0, 4, 8, 12, 16 of 16 pixels white
BG = {"sbar", "ibar", "scorebar", "backtile", "conback", "box_mm", "box_mm2", "box_ml", "box_mr", "box_tm",
      "box_bm"}


class Pal:
    def __init__(self, pal):
        self.pal = pal
        self.lum = lcd_lum(bytes(c for rgb in pal for c in rgb))
        self.cache = {}

    def pick(self, target, orig, lo=0, hi=255, tol=10, same_ramp=False):
        """The index in [lo, hi) whose LCD luminance is within tol of target (else the closest luminance),
        closest in colour to orig; with same_ramp, orig's palette row is preferred."""
        key = (target, orig, lo, hi, tol, same_ramp)
        r = self.cache.get(key)
        if r is not None:
            return r
        o = self.pal[orig]
        cands = [i for i in range(lo, hi) if abs(self.lum[i] - target) <= tol]
        if not cands:
            d = min(abs(self.lum[i] - target) for i in range(lo, hi))
            cands = [i for i in range(lo, hi) if abs(self.lum[i] - target) == d]

        def cost(i):
            p = self.pal[i]
            c = 3 * (p[0] - o[0]) ** 2 + 4 * (p[1] - o[1]) ** 2 + 2 * (p[2] - o[2]) ** 2
            if same_ramp and (i >> 4) != (orig >> 4):
                c += 60000
            return c + 40 * abs(self.lum[i] - target) ** 2
        r = min(cands, key=cost)
        self.cache[key] = r
        return r


def percentile(vals, q):
    s = sorted(vals)
    if not s:
        return 0
    return s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))]


def stretch(L, mask, lo_q=0.02, hi_q=0.98, out_lo=0, out_hi=255):
    vals = [L[i] for i in range(len(L)) if mask[i]]
    a, b = percentile(vals, lo_q), percentile(vals, hi_q)
    if b <= a:
        return list(L)
    return [min(255, max(0, out_lo + (v - a) * (out_hi - out_lo) / (b - a))) for v in L]


def unsharp(L, w, h, mask, amount):
    out = list(L)
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if not mask[i]:
                continue
            s = n = 0
            for dy in (-1, 0, 1):
                yy = y + dy
                if yy < 0 or yy >= h:
                    continue
                for dx in (-1, 0, 1):
                    xx = x + dx
                    if 0 <= xx < w and mask[yy * w + xx]:
                        s += L[yy * w + xx]
                        n += 1
            out[i] = min(255, max(0, L[i] + amount * (L[i] - s / n)))
    return out


def nearest_level(v, levels):
    return min(levels, key=lambda l: abs(l - v))


def ui_colour(P, target, orig, lo, hi, mono):
    """A UI pixel at LCD level target: a shade of its own colour (default; another colour only when its row cannot
    come within half a level of target), or with mono (--mono-ui) any palette colour of that level, closest to the
    original (which turns the font white, for one)."""
    if not mono:
        r = in_ramp(P, target, orig, lo, hi, black=True)
        if abs(P.lum[r] - target) <= 32:
            return r
        # the row cannot reach that level (the dark reds of the low-ammo digits stop at 96 of 255): the closest
        # colour that does, as the UI must stay readable on the LCD
    return P.pick(target, orig, lo, hi, tol=4 if target in (0, 255) else 8)


def dominant(pix, mask):
    """The most used palette row of the pixels in mask, as an index in the middle of that row."""
    n = {}
    for p, m in zip(pix, mask):
        if m:
            n[p >> 4] = n.get(p >> 4, 0) + 1
    return (max(n, key=n.get) << 4) + 8 if n else 8


def picture(P, w, h, pix, trans, name, mono=False):
    mask = [p != trans for p in pix] if trans is not None else [True] * len(pix)
    L = [P.lum[p] for p in pix]
    out = bytearray(pix)
    hi = 255 if trans == 255 else 256
    lo = 1 if trans == 0 else 0
    if name in BG:
        # mostly black, the brightest third of the texture as sparse dots
        S = stretch(L, mask)
        for i, p in enumerate(pix):
            if mask[i]:
                out[i] = ui_colour(P, 64 if S[i] > 150 else 0, p, lo, hi, mono)
        return bytes(out)
    if name.startswith("num_") or name.startswith("anum_"):
        S = stretch(L, mask, 0.0, 1.0)
        inv = name.startswith("anum_")
        box = dominant(pix, mask)       # the colour of the transparent pixels when they become the box
        for i, p in enumerate(pix):
            face = S[i] > 110 and mask[i]
            if inv:
                out[i] = ui_colour(P, 0 if face else 255, p if mask[i] else box, lo, hi, mono)
            elif mask[i]:
                out[i] = ui_colour(P, 255 if face else 0, p, lo, hi, mono)
        return bytes(out)
    S = unsharp(stretch(L, mask), w, h, mask, 0.6)
    for i, p in enumerate(pix):
        if mask[i]:
            out[i] = ui_colour(P, nearest_level(S[i], LEVELS5), p, lo, hi, mono)
    return bytes(out)


def font(P, pix, mono=False):
    out = bytearray(pix)
    L = [P.lum[p] for p in pix]
    for ch in range(256):
        cx, cy = (ch & 15) * 8, (ch >> 4) * 8
        graphic = (ch >> 4) in (0, 8)
        cell = [(cy + y) * 128 + cx + x for y in range(8) for x in range(8)]
        if graphic:
            sub = [pix[i] for i in cell]
            res = picture(P, 8, 8, sub, 0, "glyph", mono)
            for k, i in enumerate(cell):
                out[i] = res[k]
            continue
        lit = [L[i] for i in cell if pix[i]]
        if not lit:
            continue
        thr = (min(lit) + max(lit)) / 2
        for i in cell:
            if pix[i]:
                # face white, shadow black (48 = (0, 0, 0), since 0 is transparent); by default in the
                # letter's own colour: the grey letters stay grey-white, the gold ones gold
                out[i] = ui_colour(P, 255 if L[i] >= thr else 0, pix[i], 1, 256, mono)
    return bytes(out)


def median3(L, w, h, mask):
    out = list(L)
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if not mask[i]:
                continue
            v = sorted(L[yy * w + xx] for yy in range(max(0, y - 1), min(h, y + 2))
                       for xx in range(max(0, x - 1), min(w, x + 2)) if mask[yy * w + xx])
            out[i] = v[len(v) // 2]
    return out


# grey ramp entries (palette row 0) for the 5 levels: the colormap darkens them evenly, and one ramp means one
# 2x2 pattern variant per level in the 3D view, so a model's areas read as areas instead of speckle
SKIN_GREYS = {0: 0, 64: 2, 128: 3, 192: 6, 255: 8}


SKIN_BLACK = 40


def in_ramp(P, target, orig, lo=0, hi=224, black=False):
    """The colour of orig's palette row (16 shades of one hue), within [lo, hi), whose LCD luminance is closest to
    target; of equal ones, the closest to orig. Staying in the row keeps the colour, how lighting darkens it, and
    the 2x2 pattern variant the 3D view picks per row. black: for target 0 pure black (index 48, (0, 0, 0)) may
    be picked too, for rows whose darkest shade is not black on the LCD."""
    key = ("ramp", target, orig, lo, hi, black)
    r = P.cache.get(key)
    if r is None:
        o = P.pal[orig]
        row = [i for i in range(orig & ~15, (orig & ~15) + 16) if lo <= i < hi]
        if black and target == 0:
            row.append(48)
        r = min(row, key=lambda i: (abs(P.lum[i] - target),
                                    sum((a - b) ** 2 for a, b in zip(P.pal[i], o))))
        P.cache[key] = r
    return r


def skin(P, w, h, pix, grey=False):
    mask = [p < 224 for p in pix]
    L = [P.lum[p] for p in pix]
    S = stretch(median3(L, w, h, mask), mask, 0.02, 0.98)
    out = bytearray(pix)
    for i, p in enumerate(pix):
        if mask[i]:
            # the darkest texels stay black (seams, eyes, folds: the drawing), the rest is lifted towards white,
            # since the lighting of a level darkens a skin by one or two levels anyway
            v = 0 if S[i] < SKIN_BLACK else 64 + (S[i] - SKIN_BLACK) * (255 - 64) / (255 - SKIN_BLACK)
            lv = nearest_level(v, LEVELS5)
            out[i] = SKIN_GREYS[lv] if grey else in_ramp(P, lv, p)
    return bytes(out)


def make(force=False, only=None, grey_skins=False, mono_ui=False, textures=False, log=print):
    fs = qpemod.base_fs()
    pal, palbytes = qpemod.palette(fs)
    P = Pal(pal)
    n = skipped = 0
    for path, kind, info in qpemod.assets(fs):
        if only and not any(o in path for o in only):
            continue
        if kind == "texture" and not textures:
            continue
        dest = os.path.join(qpemod.ART, path)
        if os.path.exists(dest) and not force:
            skipped += 1
            continue
        pix = qpemod.original_pixels(fs, kind, info)
        w, h = info["w"], info["h"]
        if kind == "font":
            new = font(P, pix, mono_ui)
        elif kind in ("skin", "texture"):
            new = skin(P, w, h, pix, grey_skins)
        else:
            name = os.path.splitext(os.path.basename(path))[0]
            new = picture(P, w, h, pix, 255, name, mono_ui)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        png_write(dest, w, h, new, palbytes, qpemod.transparent_index(kind))
        n += 1
    log("auto: %d pictures written to %s, %d already there (--force replaces them)" %
        (n, os.path.relpath(qpemod.ART, qpemod.TREE), skipped))
