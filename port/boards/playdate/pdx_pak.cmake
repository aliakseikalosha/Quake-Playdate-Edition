# Chooses which game data ends up in a built .pdx.
#
#   cmake -DPDX=<game>.pdx -DRELEASE=<ON|OFF> -P pdx_pak.cmake
#
# Runs after pdc (POST_BUILD), which bundles everything in Source/, so Source/id1/ can hold both the
# full pak0.pak and the shareware pak0_demo.pak:
#   RELEASE on   pak0_demo.pak, if there is one, becomes id1/pak0.pak in the .pdx (replacing any
#                pak0.pak), the registered game's id1/pak1.pak (and any later pak) and id1/music/
#                are left out of it (the shareware has no music, and the
#                re-release's tracks are not redistributable), and so is every other game folder
#                (mods and mission packs in Source/: the mission packs are not redistributable),
#                except the qpe mod, cut down to what the shareware uses (tools/qpe/qpepatch.py, needs
#                Python 3); without a pak0_demo.pak the .pdx keeps whatever pak0.pak, music and game
#                folders Source/ has.
#   RELEASE off  pak0_demo.pak is dropped from the .pdx, so only pak0.pak ships.
# Any <game>/config.cfg is left out of the .pdx in every build. Source/id1/ itself is never touched.
if(NOT PDX)
	message(FATAL_ERROR "usage: cmake -DPDX=<dir> [-DRELEASE=ON] -P pdx_pak.cmake")
endif()

set(id1 "${PDX}/id1")
set(demo "${id1}/pak0_demo.pak")

# a config.cfg in Source/<game>/ (a PC install's) would be read on a fresh install instead of the
# port's defaults (winquake/defaultcfg.h); the game writes its own into Data on the first change
file(GLOB configs "${PDX}/*/config.cfg")
foreach(cfg ${configs})
	file(REMOVE "${cfg}")
	message(STATUS "${cfg} left out of the .pdx")
endforeach()

if(NOT EXISTS "${demo}")
	if(RELEASE)
		message(STATUS "release: no pak0_demo.pak, keeping id1/pak0.pak")
	endif()
	return()
endif()

if(RELEASE)
	file(REMOVE "${id1}/pak0.pak")
	file(RENAME "${demo}" "${id1}/pak0.pak")
	message(STATUS "release: pak0_demo.pak is id1/pak0.pak")
	# the registered episodes: with them the shareware pak0.pak would run as the full game
	file(GLOB later_paks "${id1}/pak[1-9]*.pak")
	foreach(pak ${later_paks})
		get_filename_component(name "${pak}" NAME)
		file(REMOVE "${pak}")
		message(STATUS "release: id1/${name} left out of the .pdx")
	endforeach()
	file(REMOVE_RECURSE "${id1}/music")
	message(STATUS "release: id1/music left out of the .pdx")
	# the qpe mod (this port's own): only what the shareware uses. Its files are made into a patch against
	# the full data (Source/id1) and the patch applied to the shareware pak0.pak now in the .pdx, which keeps
	# exactly the pictures, models and map textures whose originals the shareware has (tools/qpe/qpepatch.py)
	set(qpe_shareware "${PDX}.qpe-shareware")
	file(REMOVE_RECURSE "${qpe_shareware}")
	if(IS_DIRECTORY "${PDX}/qpe")
		find_program(python3_exe NAMES python3 python)
		if(NOT python3_exe)
			message(FATAL_ERROR "release: Python 3 is needed to keep the qpe mod's shareware part (tools/qpe/qpepatch.py)")
		endif()
		set(qpepatch "${CMAKE_CURRENT_LIST_DIR}/../../../tools/qpe/qpepatch.py")
		execute_process(COMMAND "${python3_exe}" "${qpepatch}" make --qpe "${PDX}/qpe"
				"${CMAKE_CURRENT_LIST_DIR}/Source/id1" -o "${PDX}.qpatch" RESULT_VARIABLE r)
		if(NOT r EQUAL 0)
			message(FATAL_ERROR "release: qpepatch.py make failed")
		endif()
		execute_process(COMMAND "${python3_exe}" "${qpepatch}" apply "${PDX}.qpatch" "${id1}" -o "${qpe_shareware}"
				RESULT_VARIABLE r)
		file(REMOVE "${PDX}.qpatch")
		if(NOT r EQUAL 0)
			message(FATAL_ERROR "release: qpepatch.py apply failed")
		endif()
	endif()
	# game folders as the Mods menu sees them (winquake/menu.c, M_ModsCheckEntry)
	file(GLOB entries LIST_DIRECTORIES true "${PDX}/*")
	foreach(dir ${entries})
		get_filename_component(name "${dir}" NAME)
		# (by path: in this script's policy a quoted "id1" would read the variable id1)
		if(NOT IS_DIRECTORY "${dir}" OR "${dir}" STREQUAL "${id1}")
			continue()
		endif()
		file(GLOB game_files "${dir}/*.pak" "${dir}/progs.dat" "${dir}/maps" "${dir}/progs" "${dir}/gfx" "${dir}/sound")
		if(game_files)
			file(REMOVE_RECURSE "${dir}")
			message(STATUS "release: ${name}/ left out of the .pdx")
		endif()
	endforeach()
	if(IS_DIRECTORY "${qpe_shareware}")
		file(RENAME "${qpe_shareware}" "${PDX}/qpe")
		message(STATUS "release: qpe/ is the shareware part of the qpe mod")
	endif()
else()
	file(REMOVE "${demo}")
	message(STATUS "pak0_demo.pak left out of the .pdx")
endif()
