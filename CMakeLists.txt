cmake_minimum_required(VERSION 3.8...3.19)
project(QuakEMBD C)
# The only assembly is the device's Thumb-2 code (winquake/*_arm.S); Simulator builds need no
# assembler (MSVC has none that CMake's generic ASM can use).
if(TOOLCHAIN STREQUAL "armgcc")
	enable_language(ASM)
endif()

# gnu11, whatever the compiler's default: GCC 15 and later default to C23, where Quake's
# unprototyped function pointers (void (*f)()) take no arguments, and the device's Arm GCC is gnu11.
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_EXTENSIONS ON)

if(BOARD_NAME STREQUAL "playdate")
	include(${CMAKE_CURRENT_LIST_DIR}/port/boards/playdate/platform.cmake)
endif()

add_compile_options(-fno-common)
add_definitions(-DWINQUAKE_ENABLE_LOGGING -DWINQUAKE_LOGGING_EXTERNAL)

add_subdirectory(port)
add_subdirectory(winquake)