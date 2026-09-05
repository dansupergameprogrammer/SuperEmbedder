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
# Use CMake-style slashes before embedding the path in a C++ string literal;
# raw Windows backslashes otherwise become C++ escape sequences (for example
# `\d`), silently producing an executable name with every separator removed.
file(TO_CMAKE_PATH "${Python3_EXECUTABLE}" SEMB_TEST_PYTHON_EXECUTABLE_CMAKE)
add_compile_definitions(SEMB_TEST_PYTHON_EXECUTABLE="${SEMB_TEST_PYTHON_EXECUTABLE_CMAKE}")

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
		--engine-prefix "${SEMB_ENGINE_PREFIX}"
		--ninja-executable "${CMAKE_MAKE_PROGRAM}"
		--python-executable "${Python3_EXECUTABLE}"
		--cxx-compiler "${CMAKE_CXX_COMPILER}"
		--rc-compiler "${CMAKE_RC_COMPILER}"
		--mt-executable "${CMAKE_MT}"
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
		--cmake-executable "${CMAKE_COMMAND}"
		--ninja-executable "${CMAKE_MAKE_PROGRAM}"
		--python-executable "${Python3_EXECUTABLE}"
		--cxx-compiler "${CMAKE_CXX_COMPILER}"
		--rc-compiler "${CMAKE_RC_COMPILER}"
		--mt-executable "${CMAKE_MT}"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# TE-86 (U0 slice C, C31(iv)/C36(e)): the structural absence check,
# standalone -- witness_structural_matrix.py's own C31(iv)/C36(e) legs
# import and call the same run_construction(), so this target proves the
# module on its own terms too (both constructions, real).
add_test(
	NAME witness_no_foreign_reading_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/witness_no_foreign_reading_check.py"
		--selftest
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# TE-86 (F3, Mendeleev te84 coverage audit): the one bare cell in the pin
# tool's own population sweep -- --reuse-clone against a directory that is
# not a valid clone.
add_test(
	NAME pin_superslm_reuse_clone_invalid_test
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/pin_superslm_reuse_clone_invalid_test.py"
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
# C12b (sec 8, D-SLM4648) -- forward identity by per-row byte digests through
# ONE instrument over ONE fixed corpus: tests/c12b_row_digest_check.py's own
# docstring names its cells (S1 must-accept, S2 the entry-point substitution,
# S3 chunk-budget inertness, S4 the PS-N wrong-position MUST-REJECT, S5 the
# C1' exact-rational oracle, R1 the real Qwen3-Embedding-0.6B artifact). The
# instrument is a product target (src/c12b/); until it exists this cell is
# registered against an EMPTY instrument path and reports red-unimplemented
# by name rather than failing to configure (the same red-first shape TE-62
# used for cells whose product did not exist yet).
if(TARGET semb_c12b_row_digest)
	set(_semb_c12b_instrument "$<TARGET_FILE:semb_c12b_row_digest>")
else()
	set(_semb_c12b_instrument "")
endif()
# The real artifact is never committed (633 MB); a configure that names it
# (-DSEMB_C12B_MODEL=<path.sslm>) turns R1 from MISSING PREREQUISITE into a
# graded leg; -DSEMB_C12B_MINT_ANCHORS=ON makes that leg a MINTING run.
set(SEMB_C12B_MODEL "" CACHE FILEPATH "C12b R1: the real Qwen3-Embedding-0.6B .sslm (empty = MISSING PREREQUISITE)")
option(SEMB_C12B_MINT_ANCHORS "C12b R1: write tests/fixtures/c12b/anchors-*.tsv from this run instead of grading against it" OFF)
set(_semb_c12b_args
	--instrument "${_semb_c12b_instrument}"
	--build-dir "${CMAKE_BINARY_DIR}"
	--engine-pin "${SEMB_LOCK_TAG}@${SEMB_LOCK_COMMIT}")
if(NOT SEMB_C12B_MODEL STREQUAL "")
	list(APPEND _semb_c12b_args --model "${SEMB_C12B_MODEL}")
endif()
if(SEMB_C12B_MINT_ANCHORS)
	list(APPEND _semb_c12b_args --mint-anchors)
endif()
add_test(
	NAME c12b_row_digest_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/c12b_row_digest_check.py" ${_semb_c12b_args}
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
add_test(
	NAME ps_n_reference_oracle_selftest
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/oracle/ps_n_reference.py" --selftest
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
add_test(
	NAME q_width_threading_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/q_width_threading_check.py"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
add_test(
	NAME c12b_independent_commission_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/c12b_independent_commission_check.py"
		--instrument "${_semb_c12b_instrument}"
		--build-dir "${CMAKE_BINARY_DIR}/_c12b_independent_commission"
		--engine-prefix "${SEMB_ENGINE_PREFIX}"
		--cmake-executable "${CMAKE_COMMAND}"
		--ninja-executable "${CMAKE_MAKE_PROGRAM}"
		--python-executable "${Python3_EXECUTABLE}"
		--cxx-compiler "${CMAKE_CXX_COMPILER}"
		--rc-compiler "${CMAKE_RC_COMPILER}"
		--mt-executable "${CMAKE_MT}"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

add_test(
	NAME w_a_population_oracle_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/oracle/w_a_population.py"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# ---------------------------------------------------------------------------
# TE-92 (U1, the first frozen public raw-text vertical slice): the red suite
# for sec 3.1's five frozen verbs -- semb_encoder_open / _close / _dims,
# semb_encode, semb_status_name -- against tests/semb_public_abi_contract.h.
#
# The two C++ cells link against symbols the product does not define at
# main@1a040a4, so they are EXCLUDE_FROM_ALL: the default build of the tree
# stays green, and tests/u1_raw_text_cells_check.py builds them on demand and
# reports an unresolved frozen symbol as RED-UNIMPLEMENTED by name (the same
# red-by-name shape c12b_row_digest_check uses for an unbuilt instrument).
# ---------------------------------------------------------------------------
foreach(_semb_u1_cell u1_raw_text_contract_test u1_raw_text_parity_test)
	add_executable(${_semb_u1_cell} EXCLUDE_FROM_ALL ${_semb_u1_cell}.cpp)
	target_link_libraries(${_semb_u1_cell} PRIVATE superembedder superslm::superslm)
	target_include_directories(${_semb_u1_cell} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
endforeach()

# The converter-emitted Qwen3-Embedding-0.6B tokenizer artifact (3.4 MB, never
# committed; regenerated bit-for-bit by tools/tokenizer/regenerate_qwen3_tokenizer_artifact.py
# and held to tests/fixtures/tokenizer/qwen3-embedding-0.6b-tokenizer.manifest.json).
# Empty = the product legs report MISSING PREREQUISITE; with SEMB_C12B_MODEL it
# turns the real-pair legs on.
set(SEMB_U1_TOKENIZER "" CACHE FILEPATH
	"U1 raw-text product cells: the converter-emitted Qwen3-Embedding-0.6B tokenizer .sslm (empty = MISSING PREREQUISITE)")
set(_semb_u1_args --build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}")
if(NOT SEMB_C12B_MODEL STREQUAL "")
	list(APPEND _semb_u1_args --model "${SEMB_C12B_MODEL}")
endif()
if(NOT SEMB_U1_TOKENIZER STREQUAL "")
	list(APPEND _semb_u1_args --tokenizer "${SEMB_U1_TOKENIZER}")
endif()
add_test(
	NAME u1_raw_text_cells_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/u1_raw_text_cells_check.py" ${_semb_u1_args}
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# The public header pin: include/superembedder/semb.h must declare the five
# verbs, the opaque handle, both IN structs and the reachable status names
# exactly as the contract header does (extern "C" checks names, not types).
add_test(
	NAME u1_public_header_parity_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/u1_public_header_parity_check.py"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# The parity oracle's own commissioning (expected GREEN on unmodified main):
# through the EXISTING interim path and C12b's instrument, an omitted, doubled
# or wrong trailing special token moves the emitted vector on every row, so
# equality with that oracle pins the frozen path's composition.
set(_semb_u1_mut_args --instrument "${_semb_c12b_instrument}" --build-dir "${CMAKE_BINARY_DIR}")
if(NOT SEMB_C12B_MODEL STREQUAL "")
	list(APPEND _semb_u1_mut_args --model "${SEMB_C12B_MODEL}")
endif()
add_test(
	NAME u1_trailing_special_mutants_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/u1_trailing_special_mutants_check.py" ${_semb_u1_mut_args}
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# TE-93: U1's public bake-side batch encoder. Kept in a separate contract
# target so the closed TE-92 raw-text evidence remains byte-for-byte intact.
add_executable(u1_batch_contract_test EXCLUDE_FROM_ALL u1_batch_contract_test.cpp)
target_link_libraries(u1_batch_contract_test PRIVATE superembedder superslm::superslm)
target_include_directories(u1_batch_contract_test PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")

add_test(
	NAME u1_batch_header_parity_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/u1_batch_header_parity_check.py"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

add_test(
	NAME u1_batch_cells_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/u1_batch_cells_check.py" ${_semb_u1_args}
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
