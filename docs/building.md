# Building

[← Documentation index](README.md) · [Source index](source-index.md)

How to build the game for the Simulator and the device, where the game data and music go, and the CMake options that matter most. Every `PD_*` option and the CMake files themselves are described in the [build system](build-system.md) page.

Requires the [Playdate SDK](https://play.date/dev/) (`PLAYDATE_SDK_PATH` set), CMake and a GCC or Clang host compiler, and, for the device, the Arm toolchain (`arm-none-eabi-gcc` on the `PATH`; the SDK installs it on macOS and Windows). Builds on macOS, Linux and Windows (MinGW-w64), see [Linux and Windows](#linux-and-windows).

Game data is not included. Copy your `pak0.pak` (the freely distributable shareware one is fine) to
`port/boards/playdate/Source/id1/pak0.pak` before building, or into the game's Data folder at `id1/`.
If you also put the shareware pak there as `Source/id1/pak0_demo.pak`, the demo build
(`scripts/release-device.sh`, without `full`) ships it as `id1/pak0.pak` in place of your `pak0.pak`; every other build leaves it out.
The shareware pak and the 2021 re-release's `pak0.pak` both work. The re-release's has no `default.cfg`, so the engine
falls back to a built-in copy (`winquake/defaultcfg.h`) and the D-pad and buttons are bound; its QuakeC also needs a
`campaign` cvar and `MOVETYPE_BOUNCEMISSILE` for gibs, and a large level could crash the renderer's model cache.
All of that is handled; see [Game data](port/game-data.md).

Mods and the mission packs go in folders next to `id1` (in `Source/` or the Data folder) and are picked in the main menu's **Mods**;
see [Mods and mission packs](port/mods.md). The demo build leaves them out of the `.pdx`.

Music is optional: the CD tracks as `Quake02.wav` ... `Quake11.wav` (the re-release's names) in `port/boards/playdate/Source/id1/music/`
play as the levels' music, streamed from the `.pdx`. As PCM the ten tracks are about 590 MB; as IMA ADPCM they are about 150 MB (27-54 dB signal-to-noise against the PCM),
see [`cd_pd.c`](port/playdate.md#cd_pdc) for the `ffmpeg` command.
The demo build leaves the music out together with the full `pak0.pak` and `pak1.pak`.

```shell
git clone https://github.com/aliakseikalosha/quake-playdate && cd quake-playdate

# Simulator
mkdir build-sim && cd build-sim
cmake -DBOARD_NAME=playdate .. && make          # -> quake.pdx
cd ..

# Device
mkdir build-dev && cd build-dev
cmake -DCMAKE_TOOLCHAIN_FILE=../port/boards/playdate/toolchain.cmake -DBOARD_NAME=playdate .. && make
```

### Linux and Windows

The CMake build is the same on every host the SDK supports; only the compiler and the CMake generator differ.

- **Linux**: install the Linux SDK, set `PLAYDATE_SDK_PATH`, and install `cmake`, a host `gcc` (or `clang`) and, for the device, `arm-none-eabi-gcc` on the `PATH` (e.g. Debian/Ubuntu `gcc-arm-none-eabi`). The commands above work as they are; the Simulator loads `pdex.so`.
- **Windows**: the SDK installer sets `PLAYDATE_SDK_PATH` and installs the Arm toolchain. The Simulator library has to be built with **MinGW-w64 GCC** (e.g. from [MSYS2](https://www.msys2.org/): `pacman -S mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-cmake`), not MSVC: the engine uses GCC extensions (`__attribute__((packed))`, `__builtin_clz`, `-include`), and configuring with MSVC stops with an error. Pass a Makefile generator explicitly, since CMake picks Visual Studio by default:

  ```shell
  cmake -G "MinGW Makefiles" -DBOARD_NAME=playdate ..                     # Simulator -> quake.pdx with pdex.dll
  cmake -G "MinGW Makefiles" -DCMAKE_TOOLCHAIN_FILE=../port/boards/playdate/toolchain.cmake -DBOARD_NAME=playdate ..  # device
  cmake --build .
  ```

  The DLL needs only `KERNEL32` and the Universal C Runtime (Windows 10 and later), and exports only `eventHandler`.
  It can also be cross-compiled on macOS or Linux (`brew install mingw-w64`, or the distribution's `mingw-w64` package) with a toolchain file that sets `CMAKE_SYSTEM_NAME Windows` and `CMAKE_C_COMPILER x86_64-w64-mingw32-gcc`.
  `scripts/release-device.sh` needs a POSIX shell with `zip` (Git Bash or MSYS2).
- **macOS only**: `scripts/install-device.sh`, `scripts/pd-bench.sh` (they use `/Volumes/PLAYDATE`, `diskutil` and `/dev/cu.usbmodem*`) and the VS Code launch configuration (see [VS Code](#vs-code)). On other hosts install a `.pdx` with the Simulator's *Upload Game to Device* or by copying it to the device's data disk.

Release builds, clean and optimised, each as a `.pdx` and a `.zip` ready to sideload or upload (also the VS Code tasks **Playdate: demo build (device)** and **Playdate: release build (device)**):

```shell
scripts/release-device.sh        # build-release/Quake-<version>-demo.pdx, .zip: the shareware, the one to share
scripts/release-device.sh full   # build-release-full/Quake-<version>-full.pdx, .zip: everything in Source/
```

`<version>` is the `version=` line of `Source/pdxinfo`. Details in [Scripts and tools](tools.md#scriptsrelease-devicesh).

### VS Code

Open the repository folder in VS Code and run the builds from **Terminal > Run Task...** ([`.vscode/tasks.json`](../.vscode/tasks.json)); they run the same `cmake` commands as above, from the repository root:

| Task | What it does | Output |
| --- | --- | --- |
| **Playdate: build (simulator, debug)** | The default build task (Cmd/Ctrl+Shift+B). Configures a Debug Simulator build first, then builds; it touches `port/boards/playdate/main.c` so every run relinks and runs `pdc` again, picking up changes in `Source/`. | `build-sim-debug/quake.pdx` |
| **Playdate: configure (simulator, debug)** | Only the `cmake` configure step of the task above. | `build-sim-debug/` |
| **Playdate: clean (simulator)** | Deletes `build-sim/`, `build-sim-debug/` and the `pdex.dylib` / `.so` / `.dll` the Simulator build copies into `Source/`. Device builds are untouched. | |
| **Playdate: build (device)** | Configures and builds the device build. | `build-dev/quake_DEVICE.pdx` |
| **Playdate: clean build (device)** | Deletes `build-dev/` and every `Source/pdex.*` (which `pdc` would otherwise bundle into the `.pdx`), then builds the device build from scratch. | `build-dev/quake_DEVICE.pdx` |
| **Playdate: demo build (device)** | `scripts/release-device.sh demo`: the shareware release, see above. | `build-release/Quake-<version>-demo.pdx`, `.zip` |
| **Playdate: release build (device)** | `scripts/release-device.sh full`: the full release, see above. | `build-release-full/Quake-<version>-full.pdx`, `.zip` |
| **Playdate: clean all builds** | Deletes every build tree (`build/`, `build-*/`, including earlier releases' `.pdx` and `.zip`) and every `Source/pdex.*`. The game data in `Source/` is untouched. | |
| **Playdate: clean all, release full and demo** | Runs **Playdate: clean all builds**, **Playdate: release build (device)** and **Playdate: demo build (device)** one after the other; a failure stops the rest. Each release gets its own new build number. | `build-release-full/Quake-<version>-full.pdx`, `.zip`; `build-release/Quake-<version>-demo.pdx`, `.zip` |
| **qpe: build patch** | `tools/qpe/qpe.py patch`: rebuilds the [qpe mod](port/qpe.md#the-shareware-part-and-the-patch) from `mods/qpe/art/`, then makes the patch that recreates it from anyone's Quake paks (needs `Source/id1`'s paks and Python 3). | `Source/qpe/`, `mods/qpe/qpe.qpatch` |
| **Install on device (USB)** | Runs **Playdate: clean build (device)**, then `scripts/install-device.sh` copies the `.pdx` to a Playdate on USB and starts it (macOS only). | |

Compiler errors and warnings from the build tasks show up in the **Problems** panel.

To debug the Simulator build, install the [CodeLLDB](https://marketplace.visualstudio.com/items?itemName=vadimcn.vscode-lldb) extension and press F5 (**Playdate Simulator: Quake** in [`.vscode/launch.json`](../.vscode/launch.json)). It runs **Playdate: build (simulator, debug)** first, then starts the Playdate Simulator on `build-sim-debug/quake.pdx`; breakpoints in the engine and in `port/boards/playdate/` take effect once the Simulator has loaded the game. The SDK has no debugger for the device.

On other hosts:

- The launch configuration starts the Simulator from inside its macOS `.app`. On Linux, point `program` at the SDK's Linux Simulator binary in `bin/`; on Windows, at `bin/PlaydateSimulator.exe`, using a debugger that reads MinGW's GDB/DWARF debug info (CodeLLDB does).
- The tasks are POSIX shell commands (`rm -rf`, `touch`, `./scripts/*.sh`). On Windows, set Git Bash or MSYS2 as VS Code's integrated terminal shell (`terminal.integrated.defaultProfile.windows`). Also set the environment variable `CMAKE_GENERATOR` to `MinGW Makefiles` before starting VS Code: the configure commands pass no `-G`, and CMake would otherwise pick Visual Studio (MSVC), which this build does not support.

Every build gets the next build number: after `pdc`, `port/boards/playdate/pdx_buildnumber.cmake` writes it into the built `.pdx`'s `pdxinfo` (`buildNumber=`). The last number handed out is kept in `port/boards/playdate/.build_number` (not in git, shared by the device, simulator and profiling build directories), so `Source/pdxinfo` stays untouched; the count continues from whichever is larger, that file or the `buildNumber` in `Source/pdxinfo`. A build with nothing to recompile keeps its number.

`-DPD_RENDER_WIDTH=400 -DPD_RENDER_HEIGHT=240` renders at full panel resolution (default 320x200, scaled, for speed).

Performance knobs (device build, pass to `cmake`):

- `-DPD_NEW_RENDERER=ON` (default) draws the 3D view with the renderer written for the Playdate (`winquake/pdr_*.c`, see [Renderer](renderer.md)); `OFF` builds Quake's original software refresh (`r_*.c`, `d_*.c`). The `PD_FAST_*`, `PD_ASM` and `PD_STACK` options below only apply to the original renderer.

- `-DPD_REFRESH_RATE=30` frames per second the system asks for (max 50, `0` = as fast as possible). Raise it if lighter scenes have headroom.
- `-DPD_OPT=-O3` optimisation level. Measured on a device: `-O2` is the same as `-O3` and `-Os` is no faster, so there is little to gain here; compare with the profiling build ([Profiling on the device](profiling.md)).
- `-DPD_FAST_EDGES=ON` (default) array-based edge scan, about 6 ms per frame faster in the demos with identical output; it also keeps each surface's span list head on the stack while scanning. `OFF` uses the original linked-list version.
- `-DPD_FAST_ALIAS=ON` (default) alias models (monsters, weapon) are drawn with their per-triangle state in locals instead of ~50 globals plus a span buffer, with the two-buffer pixel stores split into separate runs, and their per-entity setup shares work (transform reused between the bbox check and the draw, `R_LightPoint` remembers where its trace landed for an exact origin). Identical output; `OFF` uses the original code.
- `-DPD_FAST_FACES=ON` (default) world faces keep their edge-emission scratch state and the traversal's bookkeeping (`edge_p`, `surface_p`, keys) on the stack, and world surface visibility is one bit per surface instead of a stamp in every `msurface_t`. Identical output; `OFF` uses the original code.
- `-DPD_FAST_SURFACES=ON` (default) surface cache bitmaps are built row by row (each row is one run of stores instead of sixteen 16-byte segments), and a surface that R_MarkLights flagged as dynamically lit but whose lightmap no light would actually change keeps its cache instead of being rebuilt (48% of the dynamic-light rebuilds in the demos; a rebuild would give the same texels). Identical output; `OFF` uses the original code.
- `-DPD_ASM=ON` (default, device build only) hand-written Thumb-2 assembly for the Cortex-M7 in the hottest CPU-bound loops, each with its C twin kept as the reference: the textured span drawer (`winquake/d_scan_arm.S`) and the edge scan's per-line span generation and active edge table upkeep (`winquake/r_edge_arm.S`). 4-5 ms per frame faster in the demos (demo1 -3.9 ms, demo2 -4.7, demo3 -5.2; 7-9%) with identical output; `OFF` uses the C.
- `-DPD_STACK=ON` (default) puts scratch data on the fast stack instead of in slow static memory, where writing it and reading it back cost ~26 ns per byte plus a miss per line: the per-surface span drawing parameters (gradients, texture adjustments; they used to be a dozen globals written for every surface), a surface cache build's lightmap, an alias model's projected vertices (models up to ~180 vertices: weapons, ogres, zombies, soldiers; not players or dogs) and the alias clipper's scratch polygon. A buffer only goes on the stack while the call chain stays within 6.5 KB of the frame start (`winquake/pd_stack.h`), and the edge scan now returns before the surfaces are drawn so the ~3 KB of scan arrays are off the stack by then. 2.6-3.6 ms per frame faster in the demos (5-7%) with identical output; `OFF` uses the static buffers.
- `-DPD_LOWRES_3D=ON` (default) renders the 3D view at half resolution; the display layer dithers it straight from the half-resolution buffer and only expands the rows that the console, menu or HUD text draw over.
