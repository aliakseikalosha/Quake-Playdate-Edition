# Toolchain file for the Playdate *device* build:
#   cmake -DCMAKE_TOOLCHAIN_FILE=../port/boards/playdate/toolchain.cmake \
#         -DBOARD_NAME=playdate ..
# Omit the toolchain file to build the Simulator library on the host instead.

include(${CMAKE_CURRENT_LIST_DIR}/pd_sdk.cmake)

# The SDK's arm.cmake finds arm-none-eabi-gcc on the PATH (the SDK installs it on macOS and
# Windows; on Linux install the distribution's gcc-arm-none-eabi or Arm's toolchain).
include(${SDK}/C_API/buildsupport/arm.cmake)
if(NOT CROSS_GCC_PATH)
	message(FATAL_ERROR "arm-none-eabi-gcc not found on the PATH")
endif()
