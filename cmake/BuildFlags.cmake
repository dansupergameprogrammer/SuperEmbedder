# cmake/BuildFlags.cmake — the C14 build-configuration half (Claude/Plans/
# SuperEmbedder_Plan.md §1.3, §8 C14): every target this project compiles
# carries -ffp-contract=off (GCC/Clang/AppleClang) or /fp:precise (MSVC), and
# never fast-math (-ffast-math / /fp:fast). D-SLM3836: this is a constraint,
# not a build detail. §1.3 quantifies over EVERY target.
#
# TE-65 fix round, F-4 + F-5. The prior design required each target to call
# semb_require_precise_fp(<target>) to both apply the flag AND register
# itself for the later assertion — a target added the ordinary way
# (add_library/add_executable with no such call) was invisible to the
# assertion, which printed green while the new target compiled with no
# /fp:precise at all (reviewer's E-7). Separately, the assertion inspected
# only target-level COMPILE_OPTIONS, so -DCMAKE_CXX_FLAGS=/fp:fast produced a
# build whose compile line carried /fp:fast while the assertion reported
# "none carries /fp:fast" (E-8) — true only by MSVC's last-flag-wins
# accident for the two targets that happened to be registered, and not true
# at all on GCC/Clang, where -ffast-math's other effects
# (-funsafe-math-optimizations, -ffinite-math-only, -fno-signed-zeros,
# -freciprocal-math) survive a later -ffp-contract=off.
#
# The fix removes the registry. The flag is applied once, directory-wide,
# to every target this CMakeLists.txt declares from this point on — there is
# no per-target incantation left to forget. The assertion independently
# verifies three things a checklist-shaped design cannot silently drift out
# of sync with: (1) the directory default itself still carries the required
# flag, (2) CMAKE_CXX_FLAGS does not carry the forbidden one (E-8's own
# construction, closed at the level it actually operates on rather than
# relying on generator flag-ordering), and (3) every REAL target this
# directory declares (enumerated from CMake's own BUILDSYSTEM_TARGETS
# directory property, not a list this file maintains) does not carry the
# forbidden flag as a target-level override.

if(MSVC)
	set(SEMB_FP_REQUIRED_FLAG "/fp:precise")
	set(SEMB_FP_FORBIDDEN_FLAG "/fp:fast")
else()
	set(SEMB_FP_REQUIRED_FLAG "-ffp-contract=off")
	set(SEMB_FP_FORBIDDEN_FLAG "-ffast-math")
endif()

# SEMB_TEST_SKIP_FP_DIRECTIVE is a test-only escape hatch (never set in normal
# use) that withholds the directory-wide add_compile_options() call below, so
# semb_assert_precise_fp() can be proven able to fail (its own must-reject).
if(NOT SEMB_TEST_SKIP_FP_DIRECTIVE)
	add_compile_options(${SEMB_FP_REQUIRED_FLAG})
else()
	message(STATUS "SEMB TEST: withholding the directory-wide ${SEMB_FP_REQUIRED_FLAG} directive "
		"(-DSEMB_TEST_SKIP_FP_DIRECTIVE=1) to prove semb_assert_precise_fp() can fail.")
endif()

# Compiled target types only — INTERFACE_LIBRARY and UTILITY targets carry no
# compile line for this assertion to inspect.
set(SEMB_FP_COMPILABLE_TARGET_TYPES STATIC_LIBRARY SHARED_LIBRARY MODULE_LIBRARY OBJECT_LIBRARY EXECUTABLE)

function(semb_assert_precise_fp)
	# (1) The directory default itself.
	get_property(_semb_fp_dir_opts DIRECTORY PROPERTY COMPILE_OPTIONS)
	list(FIND _semb_fp_dir_opts "${SEMB_FP_REQUIRED_FLAG}" _semb_fp_dir_idx)
	if(_semb_fp_dir_idx EQUAL -1)
		message(FATAL_ERROR "SEMB_FP_CONTRACTION_UNGUARDED: the directory-wide compile options "
			"(${_semb_fp_dir_opts}) do not carry '${SEMB_FP_REQUIRED_FLAG}'. Every target in this "
			"directory inherits this default; without it, none of them is guarded. Floating-point "
			"contraction is a constraint, not a build detail (D-SLM3836).")
	endif()

	# (2) CMAKE_CXX_FLAGS — a global override that reaches the compile line
	#     independently of any target's or the directory's own COMPILE_OPTIONS
	#     (E-8: -DCMAKE_CXX_FLAGS=/fp:fast is invisible to a check that only
	#     reads COMPILE_OPTIONS).
	if(DEFINED CMAKE_CXX_FLAGS AND NOT CMAKE_CXX_FLAGS STREQUAL "")
		string(FIND "${CMAKE_CXX_FLAGS}" "${SEMB_FP_FORBIDDEN_FLAG}" _semb_fp_cxxflags_idx)
		if(NOT _semb_fp_cxxflags_idx EQUAL -1)
			message(FATAL_ERROR "SEMB_FP_FASTMATH_PRESENT: CMAKE_CXX_FLAGS ('${CMAKE_CXX_FLAGS}') "
				"carries the forbidden fast-math flag '${SEMB_FP_FORBIDDEN_FLAG}'. Whether a later "
				"per-target flag happens to win the argument is a property of one compiler's flag-"
				"resolution order, not a guarantee — refused outright.")
		endif()
	endif()

	# (3) Every real target this directory declares, read from CMake's own
	#     record of what was declared — not a list this file maintains, so a
	#     target added the ordinary way is not invisible to it.
	get_property(_semb_fp_targets DIRECTORY PROPERTY BUILDSYSTEM_TARGETS)
	set(_semb_fp_checked "")
	foreach(_semb_fp_t IN LISTS _semb_fp_targets)
		get_target_property(_semb_fp_type ${_semb_fp_t} TYPE)
		if(NOT _semb_fp_type IN_LIST SEMB_FP_COMPILABLE_TARGET_TYPES)
			continue()
		endif()
		list(APPEND _semb_fp_checked "${_semb_fp_t}")
		get_target_property(_semb_fp_opts ${_semb_fp_t} COMPILE_OPTIONS)
		if(NOT _semb_fp_opts)
			set(_semb_fp_opts "")
		endif()
		list(FIND _semb_fp_opts "${SEMB_FP_FORBIDDEN_FLAG}" _semb_fp_fidx)
		if(NOT _semb_fp_fidx EQUAL -1)
			message(FATAL_ERROR "SEMB_FP_FASTMATH_PRESENT: target '${_semb_fp_t}' carries the "
				"forbidden fast-math flag '${SEMB_FP_FORBIDDEN_FLAG}' as a target-level override.")
		endif()
	endforeach()
	if(NOT _semb_fp_checked)
		message(FATAL_ERROR "SEMB_FP_FLAG_ASSERTION_EMPTY: no compilable target exists in this "
			"directory at assertion time — a check with nothing to inspect is the same defect as a "
			"check that can never fail.")
	endif()

	message(STATUS "C14 build-configuration assertion: directory default carries "
		"${SEMB_FP_REQUIRED_FLAG}; CMAKE_CXX_FLAGS carries no ${SEMB_FP_FORBIDDEN_FLAG}; "
		"[${_semb_fp_checked}] carry no target-level override of it either")
endfunction()
