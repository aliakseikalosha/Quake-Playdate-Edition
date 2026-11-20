#!/bin/bash
# Builds tools/qpe/viewer/qpeview.c (the engine half of the QPE comparison tool) against this tree
# -> tools/qpe/out/qpeview. Needs clang and the Playdate SDK (PLAYDATE_SDK_PATH) for pd_api.h only.
# The same engine files and defines as tools/hostcheck/build.sh with NEW=1 (the Playdate renderer),
# with four functions renamed at compile time so that qpeview.c can wrap them:
#   R_RenderView (pdr_main.c), PDR_LightPoint (pdr_light.c), VID_Update (vid_port.c),
#   and display.c's qembd_* entry points (as the hostcheck does).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
TREE=$(cd "$HERE/../../.." && pwd)
SDK=${PLAYDATE_SDK_PATH:-$(egrep '^\s*SDKRoot' "$HOME/.Playdate/config" 2>/dev/null | head -n 1 | cut -c9-)}
[ -f "$SDK/C_API/pd_api.h" ] || { echo "Playdate SDK not found; set PLAYDATE_SDK_PATH"; exit 1; }
OUT=$HERE/../out
O=$OUT/obj_qpeview
rm -rf "$O"; mkdir -p "$O"

DEFS=(-DWINQUAKE_ENABLE_LOGGING -DWINQUAKE_LOGGING_EXTERNAL -DQEMBD_PLAYDATE=1 -DTARGET_SIMULATOR=1
      -DTARGET_EXTENSION=1 -DPD_LOWRES_3D=1 -DPD_RENDER_WIDTH=400 -DPD_RENDER_HEIGHT=240
      -DPD_REFRESH_RATE=30 "-DDEFAULT_MEM_SIZE=(10*1024*1024)" "-DDEFAULT_MIN_MEM_SIZE=(4*1024*1024)"
      -DPD_NEW_RENDERER=1)
[ -f "$TREE/winquake/pd_stack.h" ] && DEFS+=(-DPD_STACK=1 "-DPD_STACK_BUDGET=(64*1024)")
INC=(-I"$TREE/include" -I"$TREE/winquake" -I"$TREE/port/boards/playdate" -I"$SDK/C_API")
CFLAGS=(${OPT:--O2} -g -w -fno-common -fcommon "${DEFS[@]}" "${INC[@]}")

WQ="chase cmd common console crc cvar draw host host_cmd keys mathlib menu model nonintel screen sbar zone view wad world
    cl_demo cl_input cl_main cl_parse cl_tent net_loop net_main pr_cmds pr_edict pr_exec r_efrag r_part
    sv_main sv_phys sv_move sv_user net_none pdr_main pdr_world pdr_span pdr_light pdr_alias pdr_sprite pdr_lowres"
pids=()
for f in $WQ; do
  extra=()
  [ $f = pdr_main ] && extra=(-DR_RenderView=real_R_RenderView)
  [ $f = pdr_light ] && extra=(-DPDR_LightPoint=real_PDR_LightPoint)
  clang "${CFLAGS[@]}" "${extra[@]}" -c "$TREE/winquake/$f.c" -o "$O/$f.o" & pids+=($!)
done
clang "${CFLAGS[@]}" -DVID_Update=real_VID_Update -c "$TREE/port/vid_port.c" -o "$O/vid_port.o" & pids+=($!)
for f in sys_port in_port cd_null; do clang "${CFLAGS[@]}" -c "$TREE/port/$f.c" -o "$O/$f.o" & pids+=($!); done
clang "${CFLAGS[@]}" -c "$TREE/port/fio/fio_posix.c" -o "$O/fio_posix.o" & pids+=($!)
clang "${CFLAGS[@]}" -c "$TREE/port/boards/playdate/weapons.c" -o "$O/weapons.o" & pids+=($!)
ren="-Dqembd_fillrect=tree_fillrect -Dqembd_vidinit=tree_vidinit -Dqembd_get_width=tree_get_width -Dqembd_get_height=tree_get_height -Dqembd_refresh=tree_refresh -Dqembd_display_invalidate=tree_display_invalidate"
clang "${CFLAGS[@]}" $ren -c "$TREE/port/boards/playdate/display.c" -o "$O/display.o" & pids+=($!)
clang "${CFLAGS[@]}" -c "$HERE/qpeview.c" -o "$O/qpeview.o" & pids+=($!)
for p in "${pids[@]}"; do wait $p || exit 1; done
clang -o "$OUT/qpeview" "$O"/*.o -lm
echo "built $OUT/qpeview"
