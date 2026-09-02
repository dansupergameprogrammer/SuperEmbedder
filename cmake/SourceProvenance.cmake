# cmake/SourceProvenance.cmake — §8 C34: semb_source_sha, a digest over the
# `superembedder` library target's own covered source set (its declared .cpp
# sources plus every header found under the given header roots), baked into
# a generated header at configure time and re-verified against the REAL
# compiled closure (Ninja's own deps db) as a post-build step.
#
# semb_compute_source_provenance(<target>
#   SOURCES <src1> <src2> ...
#   HEADER_ROOTS <dir1> <dir2> ...
#   OUT_HEADER <path>)
#
# Call once, after the covered set is final and BEFORE add_library()/
# target_sources() so the generated header exists in time to be compiled in.

find_package(Python3 COMPONENTS Interpreter REQUIRED)

# Leg (a): SEMB_SOURCE_SHA is an OUTPUT of configure, never an input. A cache
# variable by that name means someone tried to override the computed value on
# the command line.
if(DEFINED CACHE{SEMB_SOURCE_SHA})
	message(FATAL_ERROR "SEMB_SOURCE_SHA_NOT_SETTABLE: SEMB_SOURCE_SHA is computed by configure from "
		"the library's own covered source set (§8 C34) — it is never a build input. Remove "
		"-DSEMB_SOURCE_SHA=... from the configure command.")
endif()

function(semb_compute_source_provenance target)
	cmake_parse_arguments(ARG "" "OUT_HEADER" "SOURCES;HEADER_ROOTS" ${ARGN})

	# Leg (b): every declared source must exist on disk before it is hashed —
	# checked here (not only inside the python helper) so the FATAL_ERROR
	# fires with this file's own name rather than a python traceback.
	foreach(_src IN LISTS ARG_SOURCES)
		if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/${_src}")
			message(FATAL_ERROR "SEMB_SOURCE_FILE_MISSING: '${_src}' is declared as a covered source "
				"for '${target}' but does not exist at ${CMAKE_CURRENT_SOURCE_DIR}/${_src}.")
		endif()
	endforeach()

	# Leg (c): SEMB_ENGINE_PATH is recorded on first configure and is an input
	# to semb_source_sha (it identifies which engine install the library was
	# hashed against). Changing it on a LATER configure of the same build
	# directory without a clean reconfigure would leave a stale digest
	# standing for a new engine path — refused rather than silently accepted.
	if(DEFINED CACHE{SEMB_ENGINE_PATH_RECORDED} AND NOT "${SEMB_ENGINE_PREFIX}" STREQUAL "${SEMB_ENGINE_PATH_RECORDED}")
		message(FATAL_ERROR "SEMB_ENGINE_PATH_CHANGED: this build directory recorded engine path "
			"'${SEMB_ENGINE_PATH_RECORDED}' on an earlier configure; this configure resolves "
			"'${SEMB_ENGINE_PREFIX}' instead. semb_source_sha was computed against the recorded path — "
			"remove the build directory and reconfigure from clean rather than changing the engine "
			"path in place.")
	endif()
	set(SEMB_ENGINE_PATH_RECORDED "${SEMB_ENGINE_PREFIX}" CACHE INTERNAL "engine path semb_source_sha was last computed against")

	set(_sidecar "${CMAKE_CURRENT_BINARY_DIR}/generated/semb_source_provenance.json")
	get_filename_component(_out_header_dir "${ARG_OUT_HEADER}" DIRECTORY)
	file(MAKE_DIRECTORY "${_out_header_dir}")

	set(_py_args
		configure
		--root "${CMAKE_CURRENT_SOURCE_DIR}"
		--engine-path "${SEMB_ENGINE_PREFIX}"
		--out-header "${ARG_OUT_HEADER}"
		--out-json "${_sidecar}"
	)
	foreach(_src IN LISTS ARG_SOURCES)
		list(APPEND _py_args --source "${_src}")
	endforeach()
	foreach(_hr IN LISTS ARG_HEADER_ROOTS)
		list(APPEND _py_args --header-root "${_hr}")
	endforeach()

	execute_process(
		COMMAND "${Python3_EXECUTABLE}" "${CMAKE_SOURCE_DIR}/tools/semb_source_hash.py" ${_py_args}
		OUTPUT_VARIABLE _semb_src_out
		RESULT_VARIABLE _semb_src_rc
	)
	if(NOT _semb_src_rc EQUAL 0)
		string(JSON _semb_src_err ERROR_VARIABLE _ignored GET "${_semb_src_out}" "error")
		if(_semb_src_err STREQUAL "SEMB_SOURCE_FILE_MISSING")
			message(FATAL_ERROR "SEMB_SOURCE_FILE_MISSING: a covered header under one of "
				"[${ARG_HEADER_ROOTS}] disappeared between the glob and the read. Output: ${_semb_src_out}")
		endif()
		message(FATAL_ERROR "SEMB_SOURCE_HASH_FAILED: tools/semb_source_hash.py configure exited "
			"${_semb_src_rc}. Output: ${_semb_src_out}")
	endif()
	message(STATUS "semb_source_sha computed for '${target}': ${_semb_src_out}")

	set(SEMB_SOURCE_PROVENANCE_SIDECAR "${_sidecar}" PARENT_SCOPE)
endfunction()

# semb_verify_source_provenance(<target> SIDECAR <path>) — call AFTER
# add_library(<target> ...). Registers a POST_BUILD step that re-derives the
# REAL compiled closure from Ninja's own dependency database and fails the
# build (SEMB_SOURCE_SET_DRIFT) if it disagrees with the digest baked at
# configure time.
function(semb_verify_source_provenance target)
	cmake_parse_arguments(ARG "" "SIDECAR" "" ${ARGN})
	if(NOT CMAKE_GENERATOR STREQUAL "Ninja")
		message(WARNING "SEMB_SOURCE_DRIFT_CHECK_SKIPPED: the post-build semb_source_sha "
			"re-verification needs the Ninja generator's own dependency database; generator is "
			"'${CMAKE_GENERATOR}'. Configure-time semb_source_sha is still computed and baked; only "
			"the post-build re-derivation is unavailable.")
		return()
	endif()
	find_program(SEMB_NINJA_EXECUTABLE NAMES ninja)
	if(NOT SEMB_NINJA_EXECUTABLE)
		message(WARNING "SEMB_SOURCE_DRIFT_CHECK_SKIPPED: ninja executable not found on PATH.")
		return()
	endif()
	add_custom_command(TARGET ${target} POST_BUILD
		COMMAND "${Python3_EXECUTABLE}" "${CMAKE_SOURCE_DIR}/tools/semb_source_hash.py" verify
			--root "${CMAKE_CURRENT_SOURCE_DIR}"
			--build "${CMAKE_BINARY_DIR}"
			--ninja "${SEMB_NINJA_EXECUTABLE}"
			--target "${target}"
			--sidecar "${ARG_SIDECAR}"
		COMMENT "semb_source_sha post-build re-verification (C34 depfile leg) for ${target}"
		VERBATIM
	)
endfunction()
