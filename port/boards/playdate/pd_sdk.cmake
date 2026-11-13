# Finds the Playdate SDK: $PLAYDATE_SDK_PATH, else the SDKRoot line of ~/.Playdate/config
# (written by the SDK on macOS). Sets SDK to the path in CMake form, or stops with an error.
# Plain CMake, so it works the same on macOS, Linux and Windows; included from toolchain.cmake
# (device builds, before project()) and from platform.cmake.

set(_pd_sdk "$ENV{PLAYDATE_SDK_PATH}")
if(NOT _pd_sdk)
	foreach(_pd_home "$ENV{HOME}" "$ENV{USERPROFILE}")
		if(_pd_home AND EXISTS "${_pd_home}/.Playdate/config")
			file(STRINGS "${_pd_home}/.Playdate/config" _pd_root REGEX "^[ \t]*SDKRoot[ \t]" LIMIT_COUNT 1)
			string(REGEX REPLACE "^[ \t]*SDKRoot[ \t]+" "" _pd_sdk "${_pd_root}")
			string(STRIP "${_pd_sdk}" _pd_sdk)
			break()
		endif()
	endforeach()
endif()
file(TO_CMAKE_PATH "${_pd_sdk}" SDK)
if(NOT SDK OR NOT EXISTS "${SDK}/C_API/pd_api.h")
	message(FATAL_ERROR "Playdate SDK not found; set PLAYDATE_SDK_PATH to the SDK folder")
endif()
