#!/usr/bin/env python3
"""Quake: Playdate Edition (qpe): the mod's art pipeline and its side-by-side comparison tool.

    tools/qpe/qpe.py extract           original art -> mods/qpe/orig/ (reference, same layout as art/)
    tools/qpe/qpe.py auto [--force] [--textures] [filter ...]
                                       first automatic pass of the art -> mods/qpe/art/ (see autoart.py)
    tools/qpe/qpe.py build             mods/qpe/art/ -> port/boards/playdate/Source/qpe/ (what -game qpe loads)
    tools/qpe/qpe.py serve [--port N] [--no-browser]
                                       the comparison tool: http://127.0.0.1:8765/
    tools/qpe/qpe.py patch [-o FILE]   Source/qpe/ -> mods/qpe/qpe.qpatch: the mod without id's data, for
                                       tools/qpe/qpepatch.py to recreate it from anyone's Quake (see qpepatch.py)

`serve` runs the real engine twice (tools/qpe/viewer/qpeview.c): once on the original data and once with
-game qpe, and shows any pair of {original, qpe} x {full colour, Playdate LCD} side by side: levels (fly
around), every model (skins, frames, light), and the UI (menus, HUD, console, font, every picture).
Saving a PNG in mods/qpe/art/ rebuilds the mod and reloads it in the tool. Standard library only.
"""
import argparse
import collections
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import struct                                   # noqa: E402

import qpemod                                   # noqa: E402
import moteart                                  # noqa: E402
from quakefmt import Wad, Mdl, qpic_decode, spr_info, bsp_box, png_encode   # noqa: E402

OUTDIR = os.path.join(HERE, "out")
QPEVIEW = os.path.join(OUTDIR, "qpeview")
RUN = os.path.join(OUTDIR, "run")
WEB = os.path.join(HERE, "web")
FRAME_BYTES = 768 + 400 * 240 + 50 * 240


# --------------------------------------------------------------------------- the engines

class EngineError(Exception):
    pass


class Engine:
    """One qpeview process (tools/qpe/viewer/qpeview.c, protocol at the top of that file)."""

    def __init__(self, name, args):
        self.name = name
        self.args = args
        self.proc = None
        self.map = None
        self.spawn = None
        self.log = collections.deque(maxlen=300)

    def start(self):
        self.stop()
        self.proc = subprocess.Popen([QPEVIEW] + self.args, cwd=RUN, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        threading.Thread(target=self._stderr, args=(self.proc,), daemon=True).start()
        self.map = None
        self.spawn = None
        self._reply()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        self.proc = None

    def _stderr(self, proc):
        for line in proc.stderr:
            t = line.decode("latin-1").rstrip()
            if t:
                self.log.append(t)

    def _reply(self):
        while True:
            line = self.proc.stdout.readline()
            if not line:
                self.proc.wait()
                last = " | ".join(list(self.log)[-3:])
                self.proc = None
                raise EngineError("%s engine stopped (%s)" % (self.name, last))
            t = line.decode("latin-1").rstrip("\r\n")
            if t.startswith("FATAL"):
                self.proc.wait()
                self.proc = None
                raise EngineError("%s engine: %s" % (self.name, t[6:]))
            if t.startswith("FRAME "):
                n = int(t[6:])
                data = self.proc.stdout.read(n)
                if len(data) != n:
                    raise EngineError("%s engine: short frame" % self.name)
                return data
            if t == "OK":
                return None
            if t.startswith("OK "):
                return json.loads(t[3:])
            if t.startswith("ERR"):
                raise EngineError("%s engine: %s" % (self.name, t[4:]))
            self.log.append(t)

    def cmd(self, c):
        if not self.proc:
            self.start()
        try:
            self.proc.stdin.write((c + "\n").encode("latin-1"))
            self.proc.stdin.flush()
        except BrokenPipeError:
            pass
        return self._reply()


# --------------------------------------------------------------------------- assets for the browser

UI_SCREENS = [
    ("hud", "Status bar (full)"), ("hud_low", "Status bar (low health/ammo)"), ("hud_small", "Status bar (one row)"),
    ("console", "Console"), ("scores", "Scoreboard"), ("center", "Centre message"),
    ("chars", "Font sheet"), ("text", "Font sample"),
    ("menu_main", "Menu: main"), ("menu_singleplayer", "Menu: single player"), ("menu_load", "Menu: load"),
    ("menu_save", "Menu: save"), ("menu_multiplayer", "Menu: multiplayer"), ("menu_setup", "Menu: setup"),
    ("menu_options", "Menu: options"), ("menu_keys", "Menu: keys"), ("menu_video", "Menu: video"),
    ("menu_help", "Menu: help"), ("menu_quit", "Menu: quit"), ("menu_mods", "Menu: mods"),
]
HUD_ART = ["gfx.wad/sbar.png", "gfx.wad/ibar.png", "gfx.wad/conchars.png"]


def asset_list():
    fs = qpemod.base_fs()
    names = fs.listing()
    art = set()
    for root, _, files in os.walk(qpemod.ART):
        for fn in files:
            if fn.lower().endswith(".png"):
                art.add(os.path.relpath(os.path.join(root, fn), qpemod.ART).replace(os.sep, "/"))
    maps = [n[5:-4] for n in names if n.startswith("maps/") and n.endswith(".bsp") and not n.startswith("maps/b_")]
    models = []
    for n in names:
        if n.startswith("progs/") and n.endswith(".mdl"):
            m = Mdl(fs.read(n))
            fr = m.frames()
            lo = [min(f[1][i] for f in fr) for i in range(3)]
            hi = [max(f[2][i] for f in fr) for i in range(3)]
            skins = []
            for si, g in enumerate(m.skins):
                skins.append(["%s/skin%d%s.png" % (n, si, "_%d" % k if len(g) > 1 else "") for k in range(len(g))])
            models.append({"name": n, "kind": "mdl", "frames": [f[0] for f in fr], "skins": skins,
                           "mins": lo, "maxs": hi, "weapon": n.startswith("progs/v_")})
        elif n.startswith("progs/") and n.endswith(".spr"):
            nf, w, h = spr_info(fs.read(n))
            models.append({"name": n, "kind": "spr", "frames": ["frame%d" % i for i in range(nf)], "skins": [],
                           "mins": [0, -w / 2, -h / 2], "maxs": [0, w / 2, h / 2], "weapon": False})
        elif n.startswith("maps/b_") and n.endswith(".bsp"):
            lo, hi = bsp_box(fs.read(n))
            models.append({"name": n, "kind": "bsp", "frames": ["frame0"], "skins": [], "mins": lo, "maxs": hi,
                           "weapon": False})
    ui, pictures = [], []
    for key, label in UI_SCREENS:
        arts = HUD_ART if key.startswith("hud") else ["gfx.wad/conchars.png"]
        ui.append({"id": key, "label": label, "group": "Screens", "art": arts})
    for path, kind, info in qpemod.assets(fs):
        pictures.append({"path": path, "kind": kind, "size": [info["w"], info["h"]]})
        if kind == "wad":
            ui.append({"id": "pic:wad:" + info["lump"], "label": "gfx.wad: " + info["lump"].lower(),
                       "group": "gfx.wad", "art": [path], "size": [info["w"], info["h"]]})
        elif kind == "lmp":
            ui.append({"id": "pic:" + info["file"], "label": info["file"], "group": "gfx/*.lmp", "art": [path],
                       "size": [info["w"], info["h"]]})
    textures, anims = [], {}
    for path, info in qpemod.textures(fs):
        textures.append({"path": path, "name": info["name"], "size": [info["w"], info["h"]],
                         "maps": [os.path.basename(m)[:-4] for m in info["maps"]]})
        k = qpemod.anim_key(path)
        if k:
            anims.setdefault(k, []).append(path)
    # an animated texture (+0name .. +9name, and the alternate frames +aname .. +jname a switch shows): every frame
    # lists them all, in the order the game shows them
    for t in textures:
        k = qpemod.anim_key(t["path"])
        if k and len(anims[k]) > 1:
            t["anim"] = sorted(anims[k], key=qpemod.anim_order)
    _, pal = qpemod.palette(fs)
    return {"maps": maps, "models": models, "ui": ui, "textures": textures, "pictures": pictures,
            "art": sorted(art), "palette": list(pal)}


def texture_view(path, want=None, frames=True):
    """Where to look at a map texture: {map, cam: [x, y, z, pitch, yaw]} in front of the largest face that has it
    (in the map `want` if it has it, else the first), or {model} for one only on an item box. A frame of an
    animated texture no face starts with (+1name, ...) is looked at where its animation's first frame is."""
    fs = qpemod.base_fs()
    info = dict(qpemod.textures(fs)).get(path)
    if info is None:
        raise KeyError("no such texture: %s" % path)
    levels = [m for m in info["maps"] if not os.path.basename(m).startswith("b_")]
    if not levels:
        return {"model": info["maps"][0]}
    bsp = "maps/%s.bsp" % want if want and "maps/%s.bsp" % want in levels else levels[0]
    data = fs.read(bsp)
    ids = {i for i, n, w, h, pix in qpemod.bsp_textures(data) if n == info["name"] and pix == info["pix"]}
    lump = lambda n: struct.unpack_from("<ii", data, 4 + n * 8)     # noqa: E731
    pofs, _ = lump(1)
    vofs, _ = lump(3)
    tofs, _ = lump(6)
    fofs, flen = lump(7)
    eofs, _ = lump(12)
    sofs, _ = lump(13)
    best = None
    for f in range(flen // 20):
        plane, side, first, num, ti = struct.unpack_from("<hhihh", data, fofs + f * 20)
        if struct.unpack_from("<i", data, tofs + ti * 40 + 32)[0] not in ids:
            continue
        pts = []
        for k in range(num):
            se, = struct.unpack_from("<i", data, sofs + (first + k) * 4)
            v = struct.unpack_from("<HH", data, eofs + abs(se) * 4)[0 if se >= 0 else 1]
            pts.append(struct.unpack_from("<3f", data, vofs + v * 12))
        n = list(struct.unpack_from("<3f", data, pofs + plane * 20))
        if side:
            n = [-x for x in n]
        area = 0.0
        for k in range(1, num - 1):     # fan of triangles
            a = [pts[k][j] - pts[0][j] for j in range(3)]
            b = [pts[k + 1][j] - pts[0][j] for j in range(3)]
            c = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
            area += math.sqrt(sum(x * x for x in c)) / 2
        # the largest; of two sides of one surface (water is drawn from both), the upper one
        if best is None or area > best[0] + 1 or (abs(area - best[0]) <= 1 and n[2] > best[2][2]):
            best = (area, [sum(p[j] for p in pts) / num for j in range(3)], n)
    if best is None:
        key = qpemod.anim_key(path)
        if frames and key:
            for p in sorted((p for p, _ in qpemod.textures(fs) if qpemod.anim_key(p) == key), key=qpemod.anim_order):
                if p != path:
                    v = texture_view(p, want, frames=False)
                    if v.get("cam"):
                        return v
        return {"map": bsp[5:-4], "cam": None}
    area, c, n = best
    d = max(48.0, min(160.0, math.sqrt(area)))
    pos = [c[j] + n[j] * d for j in range(3)]
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, n[2]))))
    yaw = math.degrees(math.atan2(-n[1], -n[0])) if abs(n[2]) < 0.999 else 0.0
    return {"map": bsp[5:-4], "cam": [round(x, 1) for x in pos] + [round(pitch, 1), round(yaw, 1)]}


def original_png(path):
    fs = qpemod.base_fs()
    _, pal = qpemod.palette(fs)
    for p, kind, info in qpemod.assets(fs):
        if p == path:
            return png_encode(info["w"], info["h"], qpemod.original_pixels(fs, kind, info), pal,
                              qpemod.transparent_index(kind))
    return None


# --------------------------------------------------------------------------- the scene

class Viewer:
    def __init__(self):
        self.orig = Engine("original", [])
        self.qpe = Engine("qpe", ["-game", qpemod.MOD])
        self.lock = threading.Lock()
        self.generation = 0
        self.events = []        # (generation, message)
        self.cond = threading.Condition()
        self.assets = None
        self.models = {}
        self.quiet_until = 0     # the watcher waits until then (Mote batches)

    def notify(self, msg, reload=False):
        with self.cond:
            if reload:
                self.generation += 1
            self.events.append((self.generation, msg, time.time()))
            self.events = self.events[-50:]
            self.cond.notify_all()
        print(msg)

    def refresh_assets(self):
        self.assets = asset_list()
        self.models = {m["name"]: m for m in self.assets["models"]}

    def both(self, fn):
        """fn(engine) on both engines at once; returns [orig result, qpe result]."""
        res = [None, None]
        errs = []

        def run(i, e):
            try:
                res[i] = fn(e)
            except Exception as ex:     # noqa: BLE001
                errs.append(ex)
        ts = [threading.Thread(target=run, args=(i, e)) for i, e in enumerate((self.orig, self.qpe))]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        if errs:
            raise errs[0]
        return res

    def ensure_map(self, e, m):
        if e.map == m and e.proc:
            return
        e.spawn = e.cmd("load " + m)
        e.map = m

    def commands(self, e, st):
        s = st.get("settings", {})
        mode = st.get("mode", "level")
        lv = st.get("level", {})
        cmds = []
        cvars = {
            "pd_dither": int(s.get("dither", 1)), "r_lightlevels": int(s.get("lightlevels", 64)),
            "d_mipcap": int(s.get("mipcap", 1)), "r_maxdist": int(s.get("maxdist", 1024)),
            "r_interlace": 0, "cl_bob": 0, "cl_rollangle": 0, "v_kicktime": 0,
            "viewsize": 100 if lv.get("hud", True) else 120,
            "r_drawviewmodel": 1 if lv.get("gun", True) else 0,
            "r_clearcolor": 2,
        }
        reset = {"ui": "none", "pic": "off", "ent": "off", "solo": "0", "light": "off", "vmodel": "off",
                 "center": "off"}
        spawn = e.spawn or {}
        cam = lv.get("cam") if lv.get("map") == e.map else None
        if not cam and spawn:
            cam = spawn["origin"] + spawn["angles"][:2]
        if mode == "model":
            md = st.get("model", {})
            info = self.models.get(md.get("name"))
            if info:
                cz = (info["mins"][2] + info["maxs"][2]) / 2
                frame, skin = int(md.get("frame", 0)), int(md.get("skin", 0))
                dist = float(md.get("dist", 100))
                yaw, pitch = float(md.get("yaw", 0)), float(md.get("pitch", 0))
                height = float(md.get("height", 0))
                light = md.get("light")
                if md.get("weapon") and info["weapon"]:
                    reset["vmodel"] = "%s %d" % (info["name"], frame)
                    cvars["r_drawviewmodel"] = 1
                elif md.get("backdrop", "void") == "void" and spawn:
                    mins, maxs = spawn["mins"], spawn["maxs"]
                    ax, ay, az = maxs[0] + 3000, (mins[1] + maxs[1]) / 2, (mins[2] + maxs[2]) / 2
                    cam = [ax, ay, az, 0, 0]
                    reset["ent"] = "%s %d %d %g %g %g %g %g 0" % (info["name"], frame, skin, ax + dist, ay,
                                                                  az - cz + height, pitch, 180 + yaw)
                    reset["solo"] = "1"
                    reset["light"] = str(int(light if light is not None else 128))
                    cvars["r_clearcolor"] = int(md.get("bg", 0))
                    cvars["r_maxdist"] = 0
                    cvars["viewsize"] = 120
                    cvars["r_drawviewmodel"] = 0
                elif cam:
                    import math
                    y = math.radians(cam[4])
                    reset["ent"] = "%s %d %d %g %g %g %g %g 0" % (
                        info["name"], frame, skin, cam[0] + math.cos(y) * dist, cam[1] + math.sin(y) * dist,
                        cam[2] - cz + height, pitch, cam[4] + 180 + yaw)
                    if light is not None:
                        reset["light"] = str(int(light))
                    reset["solo"] = "1" if md.get("solo") else "0"
        elif mode == "ui":
            u = st.get("ui", {})
            item = u.get("item", "menu_main")
            bg = int(u.get("bg", 0))
            if item.startswith("hud"):
                cvars["viewsize"] = {"hud_small": 110}.get(item, 100)
                cvars["r_drawviewmodel"] = 1
                if item == "hud_low":
                    cmds.append("c impulse 9; give h 12; give s 4; give n 7; give r 2; give c 3")
                else:
                    cmds.append("c impulse 9; give h 100")
            elif item == "console":
                reset["ui"] = "console"
            elif item == "scores":
                reset["ui"] = "scores"
            elif item == "center":
                reset["center"] = "You need the silver key|to open this door"
            elif item in ("chars", "text"):
                reset["pic"] = None
                cmds.append("%s %d" % (item, bg))
            elif item.startswith("menu_"):
                cmds.append("c " + item)
                reset["ui"] = "menu"
            elif item.startswith("pic:"):
                reset["pic"] = "%s %d" % (item[4:], bg)
        out = ["c " + "; ".join("%s %s" % (k, v) for k, v in cvars.items()), "freeze %d" % (not s.get("animate"))]
        if cam:
            out.append("cam %g %g %g %g %g 0" % tuple(cam[:5]))
        else:
            out.append("cam off")
        for k, v in reset.items():
            if v is not None and not (k == "ui" and v == "menu"):
                out.append("%s %s" % (k, v))
        out += cmds
        if reset["ui"] == "menu":
            out.append("ui menu")
        return out

    def render(self, st):
        with self.lock:
            mode = st.get("mode", "level")
            m = st.get("level", {}).get("map") or "start"
            if mode == "ui" and st.get("ui", {}).get("map"):
                m = st["ui"]["map"]
            if mode == "model" and st.get("model", {}).get("backdrop", "void") == "void":
                m = st.get("level", {}).get("map") or "start"

            def go(e):
                self.ensure_map(e, m)
                for c in self.commands(e, st):
                    e.cmd(c)
                return e.cmd("frame %d" % (2 if not st.get("settings", {}).get("animate") else 1))
            frames = self.both(go)
            head = {"generation": self.generation, "map": m, "spawn": self.orig.spawn,
                    "log": {"original": list(self.orig.log)[-6:], "qpe": list(self.qpe.log)[-6:]}}
            return head, frames

    def restart_qpe(self):
        with self.lock:
            self.qpe.stop()

    # ----------------------------------------------------------------------- live reload

    def watch(self):
        def sig(root):
            out = {}
            for r, _, files in os.walk(root):
                for fn in files:
                    if root == qpemod.ART and not fn.lower().endswith(".png"):
                        continue        # mote.json: settings, not art
                    p = os.path.join(r, fn)
                    try:
                        st = os.stat(p)
                    except OSError:
                        continue
                    out[p] = (st.st_mtime_ns, st.st_size)
            return out
        art = sig(qpemod.ART)
        out = sig(qpemod.OUT)
        while True:
            time.sleep(0.4)
            if time.time() < self.quiet_until:
                continue                # a Mote batch is writing pictures: build once it is done
            a = sig(qpemod.ART)
            if a != art:
                time.sleep(0.3)         # let the editor finish writing
                a = sig(qpemod.ART)
                art = a
                msgs = []
                try:
                    qpemod.build(log=msgs.append)
                    art = sig(qpemod.ART)    # build may have rewritten RGB art as indexed: not a new edit
                    self.refresh_assets()
                    self.notify(" ".join(msgs))
                except Exception as ex:     # noqa: BLE001
                    self.notify("build failed: %s" % ex)
            o = sig(qpemod.OUT)
            if o != out:
                out = o
                self.restart_qpe()
                self.notify("reloaded the qpe mod", reload=True)


# --------------------------------------------------------------------------- HTTP

VIEWER = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass        # the page dropped the request (an animated card moved on to the next frame)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                with open(os.path.join(WEB, "index.html"), "rb") as f:
                    return self.send(200, f.read(), "text/html; charset=utf-8")
            if u.path == "/api/assets":
                VIEWER.refresh_assets()
                return self.send(200, VIEWER.assets)
            if u.path == "/api/png":
                path = q.get("path", [""])[0]
                if ".." in path:
                    return self.send(400, "bad path", "text/plain")
                if q.get("src", ["orig"])[0] == "art":
                    f = os.path.join(qpemod.ART, path)
                    if not os.path.isfile(f):
                        return self.send(404, "no art", "text/plain")
                    with open(f, "rb") as fh:
                        return self.send(200, fh.read(), "image/png")
                data = original_png(path)
                return self.send(200, data, "image/png") if data else self.send(404, "none", "text/plain")
            if u.path == "/api/texview":
                try:
                    return self.send(200, texture_view(q.get("path", [""])[0], q.get("map", [""])[0]))
                except KeyError as ex:
                    return self.send(404, {"error": str(ex)})
            if u.path == "/api/events":
                return self.events(int(q.get("since", ["0"])[0]))
            if u.path == "/api/mote/settings":
                path = q.get("path", [""])[0]
                return self.send(200, {"settings": moteart.settings(path) if path else moteart.settings()})
            return self.send(404, "not found", "text/plain")
        except Exception as ex:     # noqa: BLE001
            traceback.print_exc()
            return self.send(500, {"error": str(ex)})

    def events(self, since):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        seen = time.time() if since == 0 else since
        try:
            while True:
                with VIEWER.cond:
                    VIEWER.cond.wait(timeout=15)
                    new = [e for e in VIEWER.events if e[2] > seen]
                if new:
                    seen = new[-1][2]
                    for g, m, _t in new:
                        self.wfile.write(("data: %s\n\n" % json.dumps({"generation": g, "message": m})).encode())
                else:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        try:
            if u.path == "/api/render":
                try:
                    head, frames = VIEWER.render(body)
                except EngineError as ex:
                    return self.send(500, {"error": str(ex)})
                hj = json.dumps(head).encode()
                payload = len(hj).to_bytes(4, "little") + hj + frames[0] + frames[1]
                return self.send(200, payload, "application/octet-stream")
            if u.path == "/api/mote":
                path = body.get("path", "")
                if ".." in path or not path.endswith(".png"):
                    return self.send(400, {"error": "bad path"})
                # saving a selection picture by picture: "more" keeps the watcher quiet until the last one
                if body.get("save"):
                    VIEWER.quiet_until = time.time() + (30 if body.get("more") else 0)
                try:
                    head, bits, opaque, pix = moteart.edit(body)
                except (KeyError, ValueError) as ex:
                    return self.send(400, {"error": str(ex)})
                hj = json.dumps(head).encode()
                return self.send(200, len(hj).to_bytes(4, "little") + hj + bits + opaque + pix,
                                 "application/octet-stream")
            if u.path == "/api/mote/batch":
                paths = body.get("paths", [])
                if any(".." in p or not p.endswith(".png") for p in paths):
                    return self.send(400, {"error": "bad path"})
                VIEWER.quiet_until = time.time() + 3600
                try:
                    return self.send(200, moteart.batch(body))
                finally:
                    VIEWER.quiet_until = time.time() + (2.0 if body.get("more") else 0)
            if u.path == "/api/edit":
                path = body.get("path", "")
                if ".." in path or not path.endswith(".png"):
                    return self.send(400, {"error": "bad path"})
                f = os.path.join(qpemod.ART, path)
                if not os.path.exists(f):
                    data = original_png(path)
                    if not data:
                        return self.send(404, {"error": "no such picture"})
                    os.makedirs(os.path.dirname(f), exist_ok=True)
                    with open(f, "wb") as fh:
                        fh.write(data)
                editor = os.environ.get("QPE_EDITOR")
                subprocess.Popen((["open", "-a", editor] if editor else ["open"]) + [f])
                return self.send(200, {"file": os.path.relpath(f, qpemod.TREE)})
            if u.path == "/api/revert":
                path = body.get("path", "")
                if ".." in path or not path.endswith(".png"):
                    return self.send(400, {"error": "bad path"})
                f = os.path.join(qpemod.ART, path)
                if os.path.exists(f):
                    os.remove(f)
                return self.send(200, {"removed": os.path.relpath(f, qpemod.TREE)})
            return self.send(404, {"error": "not found"})
        except Exception as ex:     # noqa: BLE001
            traceback.print_exc()
            return self.send(500, {"error": str(ex)})


def build_viewer():
    """(Re)build tools/qpe/out/qpeview when it is older than the viewer or any engine source it is made of."""
    srcs = [os.path.join(HERE, "viewer", "qpeview.c"), os.path.join(HERE, "viewer", "build.sh")]
    for d in ("winquake", "port", os.path.join("port", "fio"), os.path.join("port", "boards", "playdate")):
        p = os.path.join(qpemod.TREE, d)
        srcs += [os.path.join(p, f) for f in os.listdir(p) if f.endswith((".c", ".h"))]
    if os.path.exists(QPEVIEW) and all(os.path.getmtime(QPEVIEW) > os.path.getmtime(s) for s in srcs):
        return
    print("building the viewer engine ...")
    subprocess.check_call([os.path.join(HERE, "viewer", "build.sh")])


def setup_run_dir():
    """tools/qpe/out/run: id1 with links to the game's paks (and a copy of config.cfg, so nothing the engine
    writes ends up in Source/), and qpe linked to Source/qpe."""
    src_id1 = os.path.join(qpemod.SOURCE, "id1")
    id1 = os.path.join(RUN, "id1")
    os.makedirs(id1, exist_ok=True)
    for fn in os.listdir(src_id1):
        if fn.lower().startswith("pak") and fn.lower().endswith(".pak") and fn != "pak0_demo.pak":
            dst = os.path.join(id1, fn)
            if os.path.lexists(dst):
                os.remove(dst)
            os.symlink(os.path.join(src_id1, fn), dst)
    cfg = os.path.join(src_id1, "config.cfg")
    dst = os.path.join(id1, "config.cfg")
    if os.path.lexists(dst):
        os.remove(dst)
    if os.path.exists(cfg):
        shutil.copy(cfg, dst)
    os.makedirs(qpemod.OUT, exist_ok=True)
    link = os.path.join(RUN, qpemod.MOD)
    if not os.path.islink(link):
        if os.path.exists(link):
            shutil.rmtree(link)
        os.symlink(qpemod.OUT, link)


def serve(port, browser):
    global VIEWER
    build_viewer()
    moteart.build_lib()
    setup_run_dir()
    if os.path.isdir(qpemod.ART):
        qpemod.build()
    VIEWER = Viewer()
    VIEWER.refresh_assets()
    VIEWER.both(lambda e: e.start())
    threading.Thread(target=VIEWER.watch, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    url = "http://127.0.0.1:%d/" % port
    print("QPE viewer: %s  (art: %s, Ctrl-C to stop)" % (url, os.path.relpath(qpemod.ART, qpemod.TREE)))
    if browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        VIEWER.orig.stop()
        VIEWER.qpe.stop()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("extract", help="original art -> mods/qpe/orig/")
    a = sub.add_parser("auto", help="automatic first pass of the art -> mods/qpe/art/")
    a.add_argument("--force", action="store_true", help="replace pictures that are already in art/")
    a.add_argument("--grey-skins", action="store_true", help="model skins in the grey palette row instead of their own colours")
    a.add_argument("--mono-ui", action="store_true", help="UI pictures and font in any colour of the wanted level (white font) instead of their own colours")
    a.add_argument("--textures", action="store_true", help="also the textures of the maps (not made without it)")
    a.add_argument("only", nargs="*", help="only art paths containing one of these")
    sub.add_parser("build", help="mods/qpe/art/ -> Source/qpe/")
    s = sub.add_parser("serve", help="the side-by-side comparison tool")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    p = sub.add_parser("patch", help="Source/qpe/ -> a patch that recreates it from Quake's paks (qpepatch.py)")
    p.add_argument("-o", "--out", default=os.path.join(qpemod.TREE, "mods", qpemod.MOD, "qpe.qpatch"))
    args = ap.parse_args()
    if args.cmd == "extract":
        qpemod.extract()
    elif args.cmd == "auto":
        import autoart
        autoart.make(force=args.force, only=args.only, grey_skins=args.grey_skins, mono_ui=args.mono_ui,
                     textures=args.textures)
    elif args.cmd == "build":
        qpemod.build()
    elif args.cmd == "serve":
        serve(args.port, not args.no_browser)
    elif args.cmd == "patch":
        import qpepatch
        qpemod.build()
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        qpepatch.make(qpemod.OUT, qpepatch.Data([os.path.join(qpemod.SOURCE, "id1")]), args.out)


if __name__ == "__main__":
    main()
