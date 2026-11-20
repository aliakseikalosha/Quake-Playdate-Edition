# Quake: Playdate Edition (`qpe`)

[← Documentation index](../README.md) · [Source index](../source-index.md)

**Quake: Playdate Edition** (folder `qpe`) is this port's own mod: Quake with its pictures redrawn for the Playdate's
1-bit screen. It changes no game rules and no level geometry, only art:

| Replaced | Files | Why |
| --- | --- | --- |
| The font | `gfx.wad` lump `conchars` | The original letters are gold and grey with a soft shadow, which the dither turns into grey dashes |
| UI pictures | the other pictures of `gfx.wad` (status bar, numbers, faces, icons) and `gfx/*.lmp` (menus, help screens, console background) | Mid-tones of brown and red dither into noise behind the HUD and menu text |
| Model skins | `progs/*.mdl` | Skin speckle becomes per-pixel noise on the LCD, which hides a monster's shape against the walls |
| Map textures | the walls, floors, sky and liquids of every level and the item boxes (`maps/*.bsp`), through `textures.dat` | The same: a texture's speckle and mid-tones become noise that hides the level's shapes |

It is a normal Quake game folder next to `id1`: pick **Quake: Playdate Edition** in the main menu's [Mods](mods.md) screen
(the title comes from `COM_GameTitle` in [`common.c`](../../winquake/common.c)), or start with `-game qpe`. **It is the game the
port starts in** until another is picked in Mods (`DEFAULT_GAME` in [`main.c`](../../port/boards/playdate/main.c); picking Quake there
is remembered as `id1`, holding B at start-up plays plain Quake once). Its saved games and `config.cfg` are in `Data/.../qpe/`, so
games saved in plain Quake show up only there. It also runs on the
shareware data: this engine's `COM_CheckRegistered` counts every game as registered, so it never refuses a mod. The shareware demo
release ships the part of the mod the shareware uses (see [The shareware part and the patch](#the-shareware-part-and-the-patch)).

The art is made and checked with [`tools/qpe/`](../../tools/qpe/): an asset pipeline (PNG ↔ game files) and a viewer that shows
the original game and the mod side by side, in full colour and exactly as the Playdate shows them.

## Where things are

```
mods/qpe/art/                     the mod's pictures, PNG, edited by hand             (git-ignored, see below)
mods/qpe/orig/                    the original pictures in the same layout, reference (git-ignored, `qpe.py extract`)
port/boards/playdate/Source/qpe/  what the game loads: gfx.wad, gfx/*.lmp, progs/*.mdl, textures.dat
                                  (git-ignored, `qpe.py build`)
tools/qpe/                        the tools (in git)
```

An art path names the game file it replaces:

| Art file | Replaces |
| --- | --- |
| `gfx.wad/conchars.png` | the 128×128 font sheet (16×16 characters of 8×8) |
| `gfx.wad/<lump>.png` | a picture in `gfx.wad`, e.g. `gfx.wad/sbar.png`, `gfx.wad/num_5.png`, `gfx.wad/face1.png` |
| `gfx/<name>.png` | `gfx/<name>.lmp`, e.g. `gfx/mainmenu.png`, `gfx/conback.png` |
| `progs/<model>.mdl/skin<N>.png` | skin *N* of a model, e.g. `progs/ogre.mdl/skin0.png` |
| `progs/<model>.mdl/skin<N>_<k>.png` | picture *k* of an animated skin group |
| `textures/<name>.png` | a texture of the maps, e.g. `textures/city4_6.png`; `*` is written `#` (`textures/#water1.png`), animated frames keep their `+` (`textures/+0light01.png`) |
| `textures/<name>@<map>.png` | a texture whose name other maps use for different pixels: the version first in `<map>` (and every map with the same pixels), e.g. `textures/sky4@dm3.png` |

**Map textures.** 582 textures: 573 names, 9 of which (`sky4`, `*water1`, `plat_top1`, `door04_1`, `window03`, `metal5_2`,
`metal5_4`, `metal5_8`, `rock3_8`) have two versions in different maps. They are not written into copies of the maps (43 MB of
`.bsp`): `build` puts the changed ones into one file, `textures.dat`, and `Mod_ReplaceTextures` in
[`model.c`](../../winquake/model.c) puts its pixels over every texture a map loads with the same name, size and original pixels
(a CRC of them), so the two versions of a name stay apart. A texture is the same picture in every map that has it. Only the
full-size picture is drawn; `build` makes the three smaller mip levels the game draws further away from it, and the Playdate's
default *Texture detail: low* never draws the full size at all (mip 1 is the most it draws). Each block of a mip level gets the
average LCD luminance of its pixels (black and white become the grey the LCD dithers) in the block's most used palette row;
mostly fullbright blocks stay fullbright. The game loads `textures.dat` from any game folder, but only as a loose file, not from a `.pak`.

Only what is in `art/` is replaced; delete a PNG and the original is used again. `gfx/palette.lmp`, `gfx/colormap.lmp` and
`gfx/pop.lmp` (the data of the registered check) are not pictures and cannot be replaced.

**Why git-ignored.** Every picture is derived from id Software's game data, which this repository does not distribute
(`Source/*/` is ignored for the same reason). Keep `mods/qpe/art/` backed up some other way, or decide to track it in a private
repository.

## Workflow

```shell
tools/qpe/qpe.py extract        # the original pictures -> mods/qpe/orig/ (indexed PNG, Quake palette)
tools/qpe/qpe.py auto           # a first automatic pass -> mods/qpe/art/ (only pictures not there yet; --force replaces;
                                #   --grey-skins / --mono-ui for the black-and-white variants; a filter redoes part of it,
                                #   e.g. `auto --force .mdl/` only the skins, `auto --force gfx` only the UI;
                                #   map textures only with --textures, e.g. `auto --textures textures/city`)
tools/qpe/qpe.py serve          # the viewer at http://127.0.0.1:8765/ ; rebuilds and reloads on every save in art/
tools/qpe/qpe.py build          # art/ -> Source/qpe/ (serve does this too)
```

Then build the game as usual: every build copies `Source/qpe/` into the `.pdx`, the shareware demo release only its shareware part
(below; see also [Mods → installing one](mods.md#installing-one)). It is about 9.3 MB (2026-11-19, 580 map textures): a full `gfx.wad` and every replaced `.lmp` and `.mdl` (a model file
carries its frames too, not just its skins), plus `textures.dat`: 85/64 of a texture's pixels each (5.4 KB for a 64×64 texture, about
4.7 MB if every map texture were replaced). An art texture identical to the original gets no entry.

`auto` takes about 10 s and `build` about 1 s for all 298 pictures. Building the *original* pictures (`orig/` as `art/`)
reproduces the original files byte for byte (checked for all 134 files, `gfx.wad` lump by lump), so a PNG round trip loses nothing.

## The shareware part and the patch

The mod's files are made from id Software's data, so they are not in git. [`qpepatch.py`](../../tools/qpe/qpepatch.py) turns them
into a patch that holds none of it, and back:

```
tools/qpe/qpe.py patch                                   # build, then Source/qpe/ -> mods/qpe/qpe.qpatch (2.8 MB; VS Code task "qpe: build patch")
python3 qpepatch.py apply qpe.qpatch <Quake's id1 folder> -o qpe     # anyone's Quake -> the qpe folder
python3 qpepatch.py apply qpe.qpatch pak0.pak pak1.pak -o qpe        # or the pak files themselves
python3 qpepatch.py make --qpe Source/qpe Source/id1 -o qpe.qpatch   # what `qpe.py patch` runs
```

- **What it holds:** for every file of the mod (`gfx.wad`, `gfx/*.lmp`, `progs/*.mdl`), the file XORed with the original of the same
  name, and for every entry of `textures.dat`, its four mip levels XORed with the original texture's (found in the maps by name, size
  and the game's CRC, as `Mod_ReplaceTextures` does). Each is compressed with LZMA, with the CRC-32 of the original and of the result,
  behind a JSON header (`QPEPATCH`, version 1). Without the originals it is noise. The mod's files have the same sizes as the
  originals, which the patch needs.
- **Applying it:** `qpepatch.py` is a single file that needs Python 3 and nothing else, so it can be handed out with the patch (the
  patch next to it is the default). It reads the paks (later ones win, loose files over paks, as the game does), checks every original
  and every result by CRC-32, and writes the folder with `qpe-files.txt` (an earlier apply's files that are no longer made are
  removed, nothing else). A file whose original is missing or another version is skipped and listed; `--all` fails unless everything
  was applied.
- **The shareware part:** Quake 1.06's registered `pak0.pak` is the shareware one (byte for byte, also in this tree), so applying the
  patch to the shareware `pak0.pak` alone gives exactly the files whose originals the shareware has: all of `gfx.wad`, 116 of the 134
  files (all `gfx/*.lmp`, the models of episode 1) and 328 of the 580 map textures, 6.1 MB. The 18 models of `pak1.pak` (the episode 2-4
  monsters, the runes' end models, the keys' `b_*` boxes) are left out. The demo release (`scripts/release-device.sh demo`) does this
  in `pdx_pak.cmake`: it makes a patch from the `.pdx`'s `qpe/` against `Source/id1`, applies it to the shareware `pak0.pak` now in the
  `.pdx` and puts the result in place of `qpe/` (the other game folders are still left out). That needs Python 3 for the release.

## Drawing for the LCD

The Playdate shows Quake's 8-bit picture through [`display.c`](playdate.md#displayc): each palette colour becomes a
luminance (`(77 r + 151 g + 28 b) >> 8`, stretched from 4–120 to 0–255, gamma 0.8) that is dithered against a threshold tile. What that means for art:

- **Half the palette is white.** Anything brighter than a luma of about 120 is pure white on the LCD (57 of the 256 colours,
  e.g. 8–15 of the grey ramp). Only 0, 48, 64 and 65 are pure black.
- **Five levels dither cleanly.** With the 4×4 Bayer tile, luminances 0, 64, 128, 192 and 255 become solid black, 25 %, 50 %
  (a checkerboard), 75 % and solid white; anything in between is an irregular mix. The 3D view (default *patterns* dithering)
  uses 2×2 blocks with exactly these 5 levels, and picks the variant of a level by palette row (`index >> 4`), so two colours
  of the same brightness from different rows still look different there.
- **Models are lit.** A skin texel goes through the colormap (the light level) before it is shown, so in a dark corridor
  a texel drops by one or two levels. Fullbright colours (224–255) ignore the light.
- **Transparency.** Index 0 is transparent in the font (so the font's black is index 48), index 255 in pictures. Skins have none.
- **Sizes are fixed.** A picture must keep the size of the original; `build` stops on a PNG of another size.

**PNG → palette.** An indexed PNG with Quake's palette (what `extract` and `auto` write; in Aseprite, keep the sprite in
*Indexed* mode) is used index for index. Any other PNG (RGB, greyscale, another palette) is converted:
- **Exact palette colours** keep their index, a skin's fullbrights included.
- **The palette's 12 duplicate colours** (black is both 0 and 48, for one) keep the index they had in the previous build, since an
  RGB file cannot say which was meant and on skins the palette row picks the 3D dither pattern.
- **Other colours** get the nearest palette colour. For skins that is never a fullbright, so nothing starts glowing by accident.

`build` then **rewrites such a PNG as an indexed PNG with Quake's palette**, so the file shows the colours the game draws, and logs
`rewritten as an indexed PNG`. Your editor may then ask to reload the file. An RGB export of unchanged art comes back with exactly
its old indices.

## What `auto` does

[`autoart.py`](../../tools/qpe/autoart.py) makes the first version of every picture from the original. The rules below decide the LCD level of each pixel (in the luminance above);
the pixel then gets the shade of **its own palette row** (16 shades of one colour) closest to that level, so the pictures keep Quake's colours
and only their brightness changes. Pure black (index 48) may stand in for a row's darkest shade. When a UI pixel's row cannot come within half a
level of the target (the dark red of the low-ammo digits stops at 96 of 255), it gets the closest colour that can; skin texels keep their row.

| Pictures | Rule |
| --- | --- |
| Font | each letter's lit face → its brightest shade (grey-white letters stay grey-white, gold ones gold; both are white on the LCD), its shadow → black (48, since 0 is transparent); rows 0 and 8 of the sheet (bars, slider, arrows) → the picture rule |
| Most pictures | contrast stretch (2–98 %), unsharp mask, then the 5 clean levels |
| Backgrounds: `sbar`, `ibar`, `scorebar`, `backtile`, `conback`, the `box_*` fill | black with a sparse 25 % texture, so the numbers, icons and text drawn over them stand out (in colour: the darkest shades of their brown) |
| `num_*` (big status bar digits) | bright digit on black (gold in colour) |
| `anum_*` (digits shown when health, armour or ammo is low) | dark digit on a bright box: the warning is visible at a glance (a light tan box in colour, the closest colour to their red that is white on the LCD) |
| Model skins, and map textures with `--textures` | 3×3 median (removes the speckle), contrast stretch, the darkest texels black (seams, eyes, folds), the rest lifted to the 4 upper levels. Each texel stays in its own palette row (16 shades of one colour): the skins keep Quake's colours, the colormap lights them as before, and the 3D view keeps its pattern per row. A row that cannot reach a level (the browns stop at about 40 % on the LCD) gets its closest shade. Fullbright texels are kept. `auto --grey-skins` puts every level in the grey row instead: grey in the colour view, one 2×2 pattern per level. |

In the colour view the skins look like Quake's, with more contrast. Compared on `e1m1` at 70 units, the ogre's arms and chainsaw and the knight's
sword read as shapes instead of noise, almost as clearly as with `--grey-skins` (which leaves a little less speckle on the knight); the soldier
improves least. These are starting points to redraw by hand, not finished art.

Map textures are left out unless `--textures` is given: drawn by hand they are the bigger job, and a first pass of all 582 would change the
look of every level at once. With it they get the skin rule, since a level lights them the same way.

`auto --mono-ui` gives the first version of the UI rules: any palette colour of the wanted level, closest to the original, which makes the
font and digits white and the status bar grey-black in colour. On the LCD the two versions look alike.

## The viewer (`qpe.py serve`)

```shell
tools/qpe/qpe.py serve [--port 8765] [--no-browser]
QPE_EDITOR=Aseprite tools/qpe/qpe.py serve       # "Open in editor" uses that app (default: the system's PNG app)
```

It opens a page with two pictures (or all four with *Layout: all 4*), each one of:

| | Full colour | Playdate LCD |
| --- | --- | --- |
| **Original** (`id1`) | Quake's 8-bit picture with its palette | the 1-bit LCD image `display.c` makes of it |
| **QPE** (`-game qpe`) | the same with the mod's pictures | the same, as the Playdate shows it |

The pictures are not an imitation: they come from the real engine, the real Playdate renderer and the real `display.c`, run on
the computer (as the [host check](../tools.md#toolshostcheckhostcheckc) does), so they match the device pixel for pixel at the same settings.
The header has the Options menu's picture settings (dithering, light levels, texture detail, draw distance); interlacing is always off,
since a still picture is the same either way. *Animate* lets the game's clock run; otherwise the game is paused (Quake's own `pause`) and both
sides show the same moment.

| Tab | Shows | Controls |
| --- | --- | --- |
| **Levels** | every map, from any point | click a picture, then W A S D to move, Q / E down and up, arrows to turn, Shift for speed, drag to look; status bar and weapon on or off |
| **Textures** | every map texture: the panes look at the largest face that has it (in the current level if it has it, else the first map; *In* picks another), from where you can fly on as in *Levels*; the item boxes' textures show that box as a model. The list starts with the current level's textures | the map, *Look again*, the *Levels* controls; the card lists every map with the texture (click one to go there) |
| **Models** | every `progs/*.mdl`, the sprites and the item boxes (`maps/b_*.bsp`) | skin, frame (or *Play*), light 0–255, drag to turn, wheel for distance; on a plain background colour or in the level in front of the *Levels* camera (with the level's light, alone or with everything else); weapons (`v_*.mdl`) also *in hand*, as in first person |
| **UI** | the status bar (full, one row, low health and ammo), console, scoreboard, centre message, the font sheet and a text sample, every menu (shown over a level), and every picture of `gfx.wad` and `gfx/*.lmp` alone on a background colour | background colour, the level behind menus |

Under the pictures, the pictures of the current item are shown as files (in *Levels*: all textures of the level, each with *Show*,
which opens it in *Textures*): the original, the mod's version, **Open in editor**
(copies the original into `art/` first if the mod has none) and **Use the original** (deletes the mod's PNG).

**Edit in Mote** opens that picture in the Mote editor, inside the same page (see below). For a map texture, the editor's in-game view
looks at it (in the current level, when that has it). A texel that glows in the original keeps glowing (below).

### The Mote editor

[Mote](https://mote.oh4.co) is Eric Scrivner's 1-bit dithering tool; its library, `oh4_halftone.h` (public domain), is in
[`tools/qpe/mote/`](../../tools/qpe/mote/) unchanged. The editor adds a 4-level mode (black, dark grey, light grey, white), settings
saved with each picture, applying one set of settings to many pictures, and animated textures. The viewer has an editor that looks like mote.oh4.co, built into the page in place of
the list and the pictures (Esc or *Back to the viewer* returns):

- **Sidebar.** Mote's settings:
  - Levels (added here): *2* (black, white: Mote's 1 bit) or *4* (the default: black, dark grey, light grey, white), with the greys'
    brightness: 25% (64), 33% (85) or 50% (128) white for dark grey, 50%, 67% (170) or 75% (192) for light grey.
  - Animation (added here, only for an animated texture or a model's skin group): *All frames* converts, shows and saves every frame
    with the same settings; *Play* cycles them at the game's 10 frames a second.
  - Adjustments: lift, gain, contrast, gamma, threshold, invert.
  - Pre-processing: sharpen, radius.
  - Grayscale.
  - Edge detection.
  - Threshold bias: Bayer 2–32, blue/white noise, IGN, halftone, diagonal, H/V line.
  - Dithering: the 10 error-diffusion kernels, strength, serpentine.
  - View: zoom, preserve alpha.
  - Output colors.
  - Plus *Source* and *Save*, and the buttons *Copy settings*, *Paste settings* and *Apply to pictures…* (below).

  Double-click a slider to reset it.
- **Top:** Mote's result (every frame side by side for an animation), in the colours that will be saved, or in Mote's view tints
  (Black & White, Playdate LCD, Amber, Green Phosphor, Custom; a grey as the tint's grey). Added here:
  - *Playdate 3D view* (the default): the 3D view is drawn at half resolution, so each picture pixel becomes a 2×2 block of LCD pixels
    in one of display.c's 5 patterns (0–4 white) by its colour's LCD luminance, the variant picked by its palette row. The result is
    drawn that way, twice the size in LCD pixels, in the page's LCD tint: dark grey is 1 white pixel of 4, light grey 3 of 4.
  - *Playdate LCD dither*: a grey as its 4×4 Bayer pattern, the way the game draws pictures outside the 3D view (menus, status bar).
- **Bottom:** the source, and the game (any of the four views; drag it to turn a model). Drag the line between them to resize.
- **Source:** the Quake original, the qpe art (read once, when picked, so that saving does not feed the result back in), or an image
  opened with *Open Image* or dropped on the page, scaled to the picture's size.
- **Grayscale *Playdate LCD (display.c)*** (added here, the default): the luminance the Playdate dithers with. Its curve brightens Quake's dark
  palette a lot, so Mote's own luminance modes make most pictures nearly black at threshold 128.

**Save to qpe** writes the picture to `mods/qpe/art/`, and the game picture reloads it like any other edit (*Save on every change* does that
after each change). Mote decides black or white for each pixel (or one of the 4 levels). [`moteart.py`](../../tools/qpe/moteart.py) then gives the pixel a palette colour
the Playdate draws as exactly that level. For black and white the colour's LCD luminance is **exactly** 0 or 255. For a grey it is in the same
step of the 4×4 Bayer tile (`bayer4 * 16 + 8`) and of the 3D view's 2×2 patterns (`(lum * 4 + 128) >> 8`) as the grey's level
(`lcd_class`), so it makes the same pattern; 10 to 12 of the 14 colour rows have such a shade for 64 and 128, 8 for 192. The colour is:
- **Own palette row** (the default): the shade of the pixel's own row closest to its colour, so the picture keeps Quake's colours.
- **Grey row:** the grey row instead.
- **Fallback:** pure black (48) when the row has no black, else the closest colour drawn as that level.

**Glowing pixels.** Palette colours 224–255 are fullbright: every light level of the colormap keeps them as they are
(`pdr_light.c`), so they glow in the dark (eyes, lava, lights, muzzle flashes). On skins and map textures a pixel that is fullbright in the
original always stays fullbright and takes no level: it keeps the original's colour, the qpe art's own fullbright colour when it has one
there (picked from the source *qpe art*), or, from an opened image, the fullbright colour closest to the image's pixel. No other pixel
becomes fullbright. Such a pixel shows its own LCD brightness in every preview, and the result's caption counts them. UI pictures are not
lit, so this does not apply to them. Pixels that are transparent in the source stay transparent with *Preserve Alpha*. So
the Playdate draws exactly Mote's pixels: for a UI picture the game's LCD image matched Mote's result pixel for pixel in all four
dithering modes (1-bit; a grey is drawn as its pattern, which depends on where on the screen it is). In the 3D view, textures and
skins are also darkened by the level's lighting, so there a grey is the level only where the light is full.

**Saved settings.** Each save records the settings with the picture in `mods/qpe/art/mote.json` (path → settings, colours, alpha,
source, time; git-ignored with the art, not watched). Opening the picture in Mote again loads them; the sidebar says when it was saved.

**Many pictures.** *Copy settings* / *Paste settings* carry the settings from one picture to another. *Apply to pictures…* lists
every picture (font, gfx.wad, gfx/*.lmp, skins, map textures; filter, tick a group or one by one, *This picture's frames*) and
converts and saves the ticked ones with the current settings, starting from each one's qpe art (or the original where it has
none) or from the originals. The server converts them 24 at a time (`POST /api/mote/batch`, `moteart.batch`) and the watcher
waits until the last is written, so the game is rebuilt once. All 880 pictures take about 40 s, plus about 40 s to build.

**Several pictures at once.** In the *Textures*, *Models* and *UI* tabs, Cmd/Ctrl-click adds an item to the selection (or removes
it) and Shift-click selects a range; the cards then show every selected item's pictures (all skins of a model), each with a tick box,
and selecting an item ticks its pictures. In the *Levels* tab one map is shown and its texture cards are ticked by hand. An animated
texture's card ticks all its frames. A bar above the cards counts the ticked pictures (also those of other tabs; a plain click in the list
starts over) and *Edit the ticked in Mote* opens them as one: Mote shows them all, in rows as wide as the pane, converts each with the
same settings, *Play* steps through them and *Save* writes each (the game rebuilds once, after the last: `/api/mote` takes `more`). The
settings come from the first picture's record; clicking another picture in the result makes it the edited one (the sidebar shows its
record, *Open Image* goes to it). *Edit in Mote* on a single card opens just that picture.

**Animated textures.** Quake animates a texture named `+0name` … `+9name` (and a switch's other state, `+aname` … `+jname`). The
*Textures* tab lists such a texture once (*+name (animated)*, with its frame count); its cards start with one that plays the original
and the qpe frames at the game's 10 a second (the alternate frames as a second animation), then every frame. Mote edits all frames
together (above). Each frame is a texture of its own in `textures.dat`, so the engine needed nothing more. A frame no face starts
with is shown where its animation's first frame is.

`qpe.py serve` builds the library as `tools/qpe/out/libmote.dylib` (`.so` on Linux) with `cc` from
[`mote.c`](../../tools/qpe/mote/mote.c). That file runs the steps in mote.oh4.co's order: grayscale, adjust, invert, sharpen, edges, then
ordered bias plus diffusion. With 4 levels, `dither_levels` replaces Mote's last step: a pixel between two levels is thresholded,
biased and its error diffused within that gap, as Mote does between black and white. The noise matrices come from a fixed seed, so the preview and the saved picture are the same. A picture takes
20–170 ms.

**Live reload.** The server watches `mods/qpe/art/`. When a PNG is saved it runs `build`, restarts the QPE engine (which reloads
`gfx.wad`, the pictures and the models) and the page draws again: about 3 s from saving to the new picture. A build error (a PNG of the
wrong size, say) is shown on the page. It also reloads when `Source/qpe/` changes from outside (a `qpe.py build` in a terminal).

### How it works

[`tools/qpe/viewer/qpeview.c`](../../tools/qpe/viewer/qpeview.c) is the engine half: the engine files of the Playdate build
(new renderer, `PD_LOWRES_3D`, 400×240, the device's 10 MB heap) plus `display.c`, linked into a program that reads commands on stdin
and answers on stdout. [`build.sh`](../../tools/qpe/viewer/build.sh) renames four functions at compile time so that `qpeview.c` can wrap them without
any change to the engine:

| Renamed | Wrapped to |
| --- | --- |
| `R_RenderView` (`pdr_main.c`) | set the camera, hide everything but the shown model (*solo*), add the shown model to the entity list, swap the weapon in hand |
| `PDR_LightPoint` (`pdr_light.c`) | give the shown model a fixed light |
| `VID_Update` (`vid_port.c`) | draw a picture, the font sheet or the text sample over the whole screen |
| `qembd_fillrect` and the rest of `display.c`'s interface | make the LCD image, then expand the half-resolution view rows into the 8-bit picture for the colour view |

For a level the camera also moves the player there (noclip, god, notarget), so the server sends the entities that can be seen from the camera.
A model on a plain background is drawn 3000 units beyond the level's bounding box, looking away from it, with the background colour as
`r_clearcolor`: no world face is in front of the camera there.

The protocol (one command per line; answers `OK`, `OK {json}`, `ERR …`, or `FRAME <n>` and *n* bytes: 768 bytes of palette, 400×240 bytes of
picture, 240×50 bytes of LCD) is listed at the top of `qpeview.c`. [`qpe.py`](../../tools/qpe/qpe.py) runs two of them (`-game qpe` and not),
sends both the same commands, and serves [`web/index.html`](../../tools/qpe/web/index.html). A frame pair takes about 3 ms; loading a level
about 30 ms. The run folder is `tools/qpe/out/run/` (links to `Source/id1`'s paks, a copy of its `config.cfg`, and `qpe` linked to `Source/qpe`),
so nothing the engine writes lands in `Source/`.

Files: [`qpe.py`](../../tools/qpe/qpe.py) (commands, server), [`qpemod.py`](../../tools/qpe/qpemod.py) (layout, PNG → game files),
[`quakefmt.py`](../../tools/qpe/quakefmt.py) (PAK, WAD2, qpic, MDL, SPR, PNG; standard library only),
`texture_view` in `qpe.py` finds the face to look at (the BSP's faces, texinfo, planes, edges), [`autoart.py`](../../tools/qpe/autoart.py),
[`moteart.py`](../../tools/qpe/moteart.py) and [`mote/`](../../tools/qpe/mote/) (the Mote editor).

## What was checked

- Map textures: a texture saved from Mote (`city4_6` in `start`) is drawn by the qpe engine and not by the original, at mip 0 and mip 1;
  the mip levels keep the picture's LCD brightness (53.5, 52.7, 51.9, 51.4 of 255); a changed `sky4` changes `dm2`'s sky and not the other
  `sky4` of `dm3`; removing the art removes `textures.dat`. `model.c` and `common.c` compile for the device (`arm-none-eabi-gcc`, the
  `build-dev` flags); not run on it.

- The Mote editor: every section, opening an image, the qpe art source, a skin, saving and the reload; a picture saved from Mote is drawn
  by the game exactly as Mote made it (all four dithering modes).
- 4 levels (2026-11-19): every picture but the font converted with *Apply to pictures* (4 levels, greys 64 / 192, no dithering, from
  the Quake originals). Converting from the earlier qpe art gave 1-bit pictures again, since all of it was black and white; the font
  keeps that art, as its 1-pixel strokes break up when grey outside the 3D view. Levels from the originals (black / dark / light / white):
  textures 10 / 67 / 20 / 2%, skins 42 / 39 / 12 / 7%, gfx.wad 4 / 68 / 18 / 10%. Every saved pixel is on one of the 4 levels; the
  settings are recorded and reopening a picture loads them. In the *Playdate 3D view* preview every dark-grey pixel is 1 white LCD pixel
  of its 2×2 block and every light-grey one 3 (checked over the 7 frames of `+slip`). That conversion kept a glowing texel only where it
  came out white, and then in a white fullbright colour that was not its own. Afterwards (glowing pixels, same day) the 87 skins and map
  textures that glow somewhere had their 177,716 glowing pixels set back to the original's colour (84,375 had lost the glow, 10,767 had
  another fullbright colour), touching no other pixel. All 663 lit pictures then match a fresh Mote conversion with their recorded
  settings, byte for byte. The art before that is in `mods/qpe/art-before-emissive/` (72 files). The animated `+shoot` (4 frames + 1 alternate) and
  `+slip` (7 frames) play in the cards and convert together in Mote. The art before it is in `mods/qpe/art-before-4colour/`.
- Several pictures (2026-11-19, in the page): Cmd-click and Shift-click (in the list's shown order) in the *Models* tab tick the selected
  models' skins, unticking a card and an animated card's box (all its frames) update the count, *Edit the ticked in Mote* opens them as
  one group, clicking the second picture makes it the edited one, and *Save* wrote both skins of a 2-picture group (same settings as
  recorded, so the files stayed byte-identical; both records updated).
- The build round trip (above), the live reload (a PNG edited on disk shows up in the QPE picture), every tab in the viewer, and the Mods
  screen listing *Quake: Playdate Edition* (in the viewer's engine).
- The patch (2026-11-19): `apply` with the full paks (as an id1 folder, and as two pak files) recreates `Source/qpe/` byte for byte (134
  files, 580 textures, with `--all`); with the shareware `pak0.pak` it writes 116 files and 328 textures. `pdx_pak.cmake` was run on a
  stand-in `.pdx` (the paks linked, music, `qpe/`, a mission pack): it left `id1/pak0.pak` = the shareware pak, no `pak1.pak`, music
  or mission pack, and a `qpe/` identical to the shareware apply. With only the shareware pak and that `qpe/`, the host check
  (`HARGS="-game qpe" HMAPS=1`) loaded and played `start` and `e1m1`-`e1m8`, and all 3050 frames of the three demos differ from the
  same run without the mod. A real `release-device.sh demo` was not run (it hands out a build number).
- **On the device (2026-11-19, build 159, SDK 3.1.2):** the pdx (with `qpe/`, 9.3 MB) installed over build 156 by copying only
  `pdex.*`, `pdxinfo` and `qpe/` (the other folders matched by name and size), `Data/com.aliakseikalosha.quake/game.txt` set to `qpe`, launched
  with `pdutil run`. The title demo ran with the qpe pictures (4-level status bar and map textures, read back over USB serial with the
  `screen` command) and the menus opened. Only a first look: no level played through, no memory or frame-time numbers, and the
  Simulator not tried.
