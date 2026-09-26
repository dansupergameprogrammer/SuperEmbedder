# tests/c62_pin_step/CMakeLists.txt -- U2 cloud build, U2-9's C62: the
# adversary's must-reject (a) (te267 sec 5 U2-9, C62, P:2800-2802): "a real
# open, large on the decided quantity, through the production data path. The
# pin-step build's open reads 3,031.5 / 3,036.0 MiB at mc 1, over each bound
# by ~2,390 MiB. Only that build's open runs."
#
# C62's own process (tests/u2_9_c62_reader.cpp, u2_9_c62_process.cpp and its
# driver u2_9_c62_resident_memory_test.cpp, unchanged, from THIS tree) is
# compiled against the pin-step build's public header and linked with the
# pin-step build's shipped static library, so the only open that runs is the
# pin step's. Configured STANDALONE by tests/u2_9_c62_pin_step_must_reject.py,
# never add_subdirectory()'d:
#
#   cmake -S tests/c62_pin_step -B <scratch> -DCMAKE_PREFIX_PATH=<engine prefix>
#         -DSEMB_PIN_STEP_SOURCE_DIR=<pin step source> -DSEMB_PIN_STEP_LIBRARY=<its superembedder library>
cmake_minimum_required(VERSION 3.21)
project(semb_c62_pin_step CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(SEMB_PIN_STEP_SOURCE_DIR "" CACHE PATH "the pin-step build's source tree")
set(SEMB_PIN_STEP_LIBRARY "" CACHE FILEPATH "the pin-step build's shipped superembedder static library")
if(NOT EXISTS "${SEMB_PIN_STEP_SOURCE_DIR}/include/superembedder/semb.h" OR NOT EXISTS "${SEMB_PIN_STEP_LIBRARY}")
	message(FATAL_ERROR "C62 pin step: SEMB_PIN_STEP_SOURCE_DIR and SEMB_PIN_STEP_LIBRARY must name the pin-step tree and its library")
endif()
find_package(superslm CONFIG REQUIRED)
find_package(Threads REQUIRED)

set(_c62_tests "${CMAKE_CURRENT_LIST_DIR}/..")
add_library(semb_pin_step STATIC IMPORTED)
set_target_properties(semb_pin_step PROPERTIES IMPORTED_LOCATION "${SEMB_PIN_STEP_LIBRARY}")
add_executable(u2_9_c62_pin_step_process
	"${_c62_tests}/u2_9_c62_reader.cpp"
	"${_c62_tests}/u2_9_c62_process.cpp"
	"${_c62_tests}/u2_9_c62_resident_memory_test.cpp")
# The pin step's public header first: C62's process is compiled against the
# ABI of the library it links.
target_include_directories(u2_9_c62_pin_step_process BEFORE PRIVATE
	"${SEMB_PIN_STEP_SOURCE_DIR}/include" "${_c62_tests}")
target_link_libraries(u2_9_c62_pin_step_process PRIVATE semb_pin_step superslm::superslm Threads::Threads)
if(WIN32)
	target_link_libraries(u2_9_c62_pin_step_process PRIVATE psapi)
endif()
