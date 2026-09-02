# cmake/BuildFlags.cmake — the C14 build-configuration half (Claude/Plans/
# SuperEmbedder_Plan.md §1.3, §8 C14): every target this project compiles
# carries -ffp-contract=off (GCC/Clang/AppleClang) or /fp:precise (MSVC), and
# never fast-math (-ffast-math / /fp:fast). D-SLM3836: this is a constraint,
# not a build detail.
#
# semb_require_precise_fp(<target>) applies the flag AND registers the target
# for semb_assert_precise_fp(), which is called once, after every target is
# declared, and independently INSPECTS each registered target's actual
# COMPILE_OPTIONS — it does not trust that the apply step ran correctly, so a
# target that acquired the flag through some other, unregistered path is not
# silently credited, and a registered target that lost it (SEMB_TEST_STRIP_FP_
# FLAG_FROM, or a future edit that forgets to call this function) is caught.

set_property(GLOBAL PROPERTY SEMB_FP_GUARDED_TARGETS "")

if(MSVC)
	set(SEMB_FP_REQUIRED_FLAG "/fp:precise")
	set(SEMB_FP_FORBIDDEN_FLAG "/fp:fast")
else()
	set(SEMB_FP_REQUIRED_FLAG "-ffp-contract=off")
	set(SEMB_FP_FORBIDDEN_FLAG "-ffast-math")
endif()

function(semb_require_precise_fp target)
	if(DEFINED SEMB_TEST_STRIP_FP_FLAG_FROM AND SEMB_TEST_STRIP_FP_FLAG_FROM STREQUAL "${target}")
		message(STATUS "SEMB TEST: withholding ${SEMB_FP_REQUIRED_FLAG} from '${target}' "
			"(-DSEMB_TEST_STRIP_FP_FLAG_FROM=${target}) to prove semb_assert_precise_fp() can fail.")
	else()
		target_compile_options(${target} PRIVATE ${SEMB_FP_REQUIRED_FLAG})
	endif()
	set_property(GLOBAL APPEND PROPERTY SEMB_FP_GUARDED_TARGETS "${target}")
endfunction()

function(semb_assert_precise_fp)
	get_property(_semb_fp_targets GLOBAL PROPERTY SEMB_FP_GUARDED_TARGETS)
	list(REMOVE_DUPLICATES _semb_fp_targets)
	if(NOT _semb_fp_targets)
		message(FATAL_ERROR "SEMB_FP_FLAG_ASSERTION_EMPTY: no target was registered with "
			"semb_require_precise_fp() before the assertion ran — a check with nothing to inspect is "
			"the same defect as a check that can never fail.")
	endif()
	foreach(_semb_fp_t IN LISTS _semb_fp_targets)
		if(NOT TARGET ${_semb_fp_t})
			message(FATAL_ERROR "SEMB_FP_FLAG_ASSERTION_STALE_TARGET: '${_semb_fp_t}' was registered "
				"with semb_require_precise_fp() but no such target exists at assertion time.")
		endif()
		get_target_property(_semb_fp_opts ${_semb_fp_t} COMPILE_OPTIONS)
		if(NOT _semb_fp_opts)
			set(_semb_fp_opts "")
		endif()
		list(FIND _semb_fp_opts "${SEMB_FP_REQUIRED_FLAG}" _semb_fp_idx)
		if(_semb_fp_idx EQUAL -1)
			message(FATAL_ERROR "SEMB_FP_CONTRACTION_UNGUARDED: target '${_semb_fp_t}' does not carry "
				"'${SEMB_FP_REQUIRED_FLAG}' in its COMPILE_OPTIONS (has: [${_semb_fp_opts}]). "
				"Floating-point contraction is a constraint, not a build detail (D-SLM3836) — every "
				"target compiles with this flag, never fast-math.")
		endif()
		list(FIND _semb_fp_opts "${SEMB_FP_FORBIDDEN_FLAG}" _semb_fp_fidx)
		if(NOT _semb_fp_fidx EQUAL -1)
			message(FATAL_ERROR "SEMB_FP_FASTMATH_PRESENT: target '${_semb_fp_t}' carries the "
				"forbidden fast-math flag '${SEMB_FP_FORBIDDEN_FLAG}'.")
		endif()
	endforeach()
	message(STATUS "C14 build-configuration assertion: [${_semb_fp_targets}] all carry "
		"${SEMB_FP_REQUIRED_FLAG}, none carries ${SEMB_FP_FORBIDDEN_FLAG}")
endfunction()
