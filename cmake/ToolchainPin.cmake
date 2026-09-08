# cmake/ToolchainPin.cmake -- TE-165 (N-4, D-SLM6386; D-SLM6390 item 5): the
# certified {compiler id, version} pairs this project's own CI records and
# clean-room rebuilds have actually verified are read from ONE committed
# file (cmake/toolchain-pin.json, never duplicated here) and enforced at
# configure time -- the same shape EngineGuards.cmake already uses for the
# engine pin: a committed fact, checked by name, refusing rather than
# silently accepting an uncertified toolchain.
#
# Before this file, S-1's finding (a bare `clang-cl.exe` configure line
# resolving, inside the VS developer shell, to the VS-bundled LLVM at
# 15.0.1 instead of the real, separately installed 18.1.8) survived three
# build rounds and a review with nothing in HEAD able to catch a repeat --
# N-4, D-SLM6386: "the wrong compiler was configured once and survived
# three rounds and a review, and the only thing standing between the
# project and the fourth is that someone remembers to type an absolute
# path."
#
# SEMB_TOOLCHAIN_UNPINNED=ON is the explicit escape hatch, never a default:
# configure proceeds against ANY compiler, and the override is written into
# the generated engine-pin header (SEMB_TOOLCHAIN_PIN_OVERRIDE) so every
# artifact built under it carries the fact -- never silent.

if(NOT DEFINED SEMB_TOOLCHAIN_PIN_FILE)
	set(SEMB_TOOLCHAIN_PIN_FILE "${CMAKE_SOURCE_DIR}/cmake/toolchain-pin.json")
endif()

if(NOT EXISTS "${SEMB_TOOLCHAIN_PIN_FILE}")
	message(FATAL_ERROR "SEMB_TOOLCHAIN_PIN_FILE_MISSING: ${SEMB_TOOLCHAIN_PIN_FILE} does not exist.")
endif()

file(READ "${SEMB_TOOLCHAIN_PIN_FILE}" _semb_tc_pin_json)

# The configured compiler's own identity, exactly as CMake resolved it for
# THIS configure -- never read back from a probe or a cache belonging to a
# different invocation (EngineGuards.cmake's own sec 4.1 reasoning,
# applied here: read what THIS configure produced, not a description of
# it). Available immediately after project(... LANGUAGES CXX) above.
set(_semb_tc_id "${CMAKE_CXX_COMPILER_ID}")
set(_semb_tc_version "${CMAKE_CXX_COMPILER_VERSION}")
set(_semb_tc_frontend "${CMAKE_CXX_COMPILER_FRONTEND_VARIANT}")

string(JSON _semb_tc_count ERROR_VARIABLE _semb_tc_len_err LENGTH "${_semb_tc_pin_json}" "certified")
if(_semb_tc_len_err)
	message(FATAL_ERROR "SEMB_TOOLCHAIN_PIN_FILE_MALFORMED: ${SEMB_TOOLCHAIN_PIN_FILE} could not be "
		"parsed as JSON, or has no 'certified' array (${_semb_tc_len_err}).")
endif()

set(_semb_tc_matched FALSE)
set(_semb_tc_certified_list "")
if(_semb_tc_count GREATER 0)
	math(EXPR _semb_tc_last "${_semb_tc_count} - 1")
	foreach(_semb_tc_i RANGE 0 ${_semb_tc_last})
		string(JSON _semb_tc_entry GET "${_semb_tc_pin_json}" "certified" ${_semb_tc_i})
		string(JSON _semb_tc_entry_id GET "${_semb_tc_entry}" "id")
		string(JSON _semb_tc_entry_version GET "${_semb_tc_entry}" "version")
		string(JSON _semb_tc_entry_frontend ERROR_VARIABLE _semb_tc_fe_err GET "${_semb_tc_entry}" "frontend")
		if(_semb_tc_fe_err)
			set(_semb_tc_entry_frontend "")
		endif()
		set(_semb_tc_certified_list
			"${_semb_tc_certified_list}[${_semb_tc_entry_id} ${_semb_tc_entry_version} frontend=${_semb_tc_entry_frontend}] ")
		if(_semb_tc_entry_id STREQUAL _semb_tc_id AND _semb_tc_entry_version STREQUAL _semb_tc_version)
			if(_semb_tc_entry_frontend STREQUAL "" OR _semb_tc_entry_frontend STREQUAL _semb_tc_frontend)
				set(_semb_tc_matched TRUE)
			endif()
		endif()
	endforeach()
endif()

option(SEMB_TOOLCHAIN_UNPINNED
	"Configure against an uncertified compiler/version. The override is recorded in the generated provenance header rather than silently accepted." OFF)

if(NOT _semb_tc_matched AND NOT SEMB_TOOLCHAIN_UNPINNED)
	message(FATAL_ERROR "SEMB_TOOLCHAIN_PIN_MISMATCH: configured compiler is "
		"${_semb_tc_id} ${_semb_tc_version} (frontend=${_semb_tc_frontend}), which is not one of the "
		"certified pairs in ${SEMB_TOOLCHAIN_PIN_FILE}: ${_semb_tc_certified_list}"
		"Pass -DSEMB_TOOLCHAIN_UNPINNED=ON to configure anyway; the override is recorded in the "
		"generated provenance header (SEMB_TOOLCHAIN_PIN_OVERRIDE) so every artifact built under it "
		"carries the fact.")
endif()

if(NOT _semb_tc_matched)
	# SEMB_TOOLCHAIN_UNPINNED is ON, or this branch would not be reached.
	set(SEMB_TOOLCHAIN_PIN_OVERRIDE_STRING
		"UNPINNED: ${_semb_tc_id} ${_semb_tc_version} (frontend=${_semb_tc_frontend}) is not a certified pair in ${SEMB_TOOLCHAIN_PIN_FILE}")
	message(STATUS "SEMB_TOOLCHAIN_UNPINNED: configuring against an uncertified compiler by explicit "
		"override -- ${SEMB_TOOLCHAIN_PIN_OVERRIDE_STRING}")
else()
	set(SEMB_TOOLCHAIN_PIN_OVERRIDE_STRING "")
	message(STATUS "Toolchain pin verified: ${_semb_tc_id} ${_semb_tc_version} (frontend=${_semb_tc_frontend})")
endif()
