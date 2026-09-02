# tests/CMakeLists.txt -- TE-62 (U0 slice B): the red suite CMake wiring.
#
# READY FOR add_subdirectory(tests) FROM THE ROOT (TE-63's own wiring
# step -- CMakeLists.txt at the repository root is the builder's file,
# outside this seat's writable scope per
# Claude/Bach/briefs/te62-u0b-red-suite.md). When added that way, the
# `superembedder` target and `superslm::superslm` already exist in the
# parent scope and are used directly.
#
# ALSO STANDALONE-CONFIGURABLE, which is how this seat proved every cell
# below red without touching the root CMakeLists.txt: `cmake -S tests -B
# build/tests -DCMAKE_PREFIX_PATH=<engine install prefix>` imports the
# ALREADY-BUILT `superembedder` library from the sibling top-level build
# (default: ../build/semb/superembedder.lib and ../include; override with
# -DSEMB_PRODUCT_LIB=... -DSEMB_PRODUCT_INCLUDE=...).
cmake_minimum_required(VERSION 3.21)

if(NOT TARGET superembedder)
	project(superembedder_tests CXX)
	set(CMAKE_CXX_STANDARD 20)
	set(CMAKE_CXX_STANDARD_REQUIRED ON)

	if(NOT DEFINED SEMB_PRODUCT_LIB)
		set(SEMB_PRODUCT_LIB "${CMAKE_CURRENT_SOURCE_DIR}/../build/semb/superembedder.lib")
	endif()
	if(NOT DEFINED SEMB_PRODUCT_INCLUDE)
		set(SEMB_PRODUCT_INCLUDE "${CMAKE_CURRENT_SOURCE_DIR}/../include")
	endif()
	if(NOT DEFINED SEMB_PRODUCT_GENERATED_INCLUDE)
		set(SEMB_PRODUCT_GENERATED_INCLUDE "${CMAKE_CURRENT_SOURCE_DIR}/../build/semb/generated")
	endif()

	find_package(superslm CONFIG REQUIRED)

	add_library(superembedder STATIC IMPORTED GLOBAL)
	set_target_properties(superembedder PROPERTIES
		IMPORTED_LOCATION "${SEMB_PRODUCT_LIB}"
		INTERFACE_INCLUDE_DIRECTORIES "${SEMB_PRODUCT_INCLUDE};${SEMB_PRODUCT_GENERATED_INCLUDE}"
	)
	target_link_libraries(superembedder INTERFACE superslm::superslm)
endif()

enable_testing()
find_package(Python3 COMPONENTS Interpreter REQUIRED)

# The Python interpreter every subprocess-driven cell below invokes its
# oracle with, threaded through as a compile definition so
# subprocess_util.h's PythonExecutable() picks the SAME interpreter CMake
# configured with, not whatever "python" resolves to on a caller's PATH.
add_compile_definitions(SEMB_TEST_PYTHON_EXECUTABLE="${Python3_EXECUTABLE}")

# ---------------------------------------------------------------------------
# semb_add_cxx_test(<name> <sources...>) -- one C++ test executable, linked
# against the product library (and, transitively, the pinned engine), run
# from the REPOSITORY ROOT (so a relative path like "tests/oracle/
# ps1_reference.py" or "build/_scratch/..." resolves the same way whether
# this suite is add_subdirectory'd or configured standalone).
# ---------------------------------------------------------------------------
function(semb_add_cxx_test name)
	add_executable(${name} ${ARGN})
	# TE-80: linked directly (not only transitively through superembedder,
	# whose own link to it is PRIVATE and therefore does not propagate
	# include dirs to a downstream target) -- src/witness/witness_main.cpp
	# takes the identical direct link for the identical reason (it calls
	# superslm::Sha256/ToHex too). A test that does not itself include an
	# engine header pays nothing extra for this.
	target_link_libraries(${name} PRIVATE superembedder superslm::superslm)
	target_include_directories(${name} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
	add_test(NAME ${name} COMMAND ${name} WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/..")
endfunction()

# C1 -- PS-1 reference equality (synthetic corners + document arm) against
# tests/oracle/ps1_reference.py.
semb_add_cxx_test(c1_ps1_reference_test c1_ps1_reference_test.cpp)

# C3 -- accumulator bound, overflow-safe spread computed before any shift,
# the position-0 alignment population leg.
semb_add_cxx_test(c3_accumulator_bound_test c3_accumulator_bound_test.cpp)

# C14 -- the FP-contraction tripwire (the build-configuration half is
# cmake/BuildFlags.cmake's semb_assert_precise_fp(), already landed and
# cited, not re-authored here).
semb_add_cxx_test(c14_fp_contraction_tripwire_test c14_fp_contraction_tripwire_test.cpp)

# The W-A population (2,592 cases) against tests/oracle/w_a_population.py.
semb_add_cxx_test(w_a_pool_population_test w_a_pool_population_test.cpp)

# W-B's serialisation, pinned byte-for-byte against sec 4.4b.
semb_add_cxx_test(w_b_serialization_test w_b_serialization_test.cpp)

# C39's seam-digest half (the grep-able singleton half is the Python cell
# below).
semb_add_cxx_test(c39_seam_digest_test c39_seam_digest_test.cpp)

# C40 -- the chunk budget is inert to the output.
semb_add_cxx_test(c40_chunk_budget_inertness_test c40_chunk_budget_inertness_test.cpp)

# TE-80: the assertion for TE-76 review F-7 (kSembEncodeHiddenTooLarge
# fires on a real hidden_size > kSembWitnessMaxHidden, before any write).
# TE-83 (TE-81 review N-13): renamed from c_f7_hidden_too_large_test --
# a review finding ID means nothing outside its own casebook and this
# test is permanent, unlike the ID.
semb_add_cxx_test(seam_hidden_capacity_test seam_hidden_capacity_test.cpp)

# ---------------------------------------------------------------------------
# Python-driven cells, matching tools/ci/run_configure_matrix.py's own
# convention (a script that runs real checks and reports a leg table),
# registered the same way the existing pin_superslm_delete_ast_check.py
# cell is (a direct interpreter invocation, no C++ harness needed).
# ---------------------------------------------------------------------------
add_test(
	NAME c39_singleton_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/c39_singleton_check.py"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# TE-80: the owed assertion for TE-76 review F-4 (semb_assert_precise_fp()'s
# own printed target list must name a real test target, not merely be
# non-empty) -- runs its own fresh, throwaway configure of the real tree.
add_test(
	NAME c14_build_config_target_list_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/c14_build_config_target_list_check.py"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

add_test(
	# TE-80 F-6: the script's own build directory is now the REAL one
	# CMake/ctest is actually configured and run from (CMAKE_BINARY_DIR),
	# never a hardcoded "build/msvc" -- so a run from build/clang (or any
	# other directory) grades that build's own objects and binaries, not
	# whichever one happened to be hardcoded.
	NAME witness_structural_matrix
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/witness_structural_matrix.py"
		--build-dir "${CMAKE_BINARY_DIR}"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# The W-A/PS-1 oracle's own self-test and split-verification -- these are
# expected GREEN (the oracle is independently verified infrastructure, not
# a cell grading unimplemented product code); registered so a future CI
# run keeps proving the oracle itself before trusting anything compared
# against it.
add_test(
	NAME ps1_reference_oracle_selftest
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/oracle/ps1_reference.py" --selftest
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
add_test(
	NAME w_a_population_oracle_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/oracle/w_a_population.py"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
