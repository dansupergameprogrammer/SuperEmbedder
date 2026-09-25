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

# TE-144 (U1 slice 1): C14's own PS-N mirror -- see the test file's own
# header comment for the two ties (trivial zero, matching PS-1's own bar;
# a real round-to-nearest-ties-to-even case through genuine BigUInt
# arithmetic, this cell's own addition since PS-N has no pooling step to
# cancel through).
semb_add_cxx_test(c14_ps_n_fp_contraction_tripwire_test c14_ps_n_fp_contraction_tripwire_test.cpp)

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

# TE-144 (U1 slice 1): C41 parts 1-3 (environment invariance, the
# cross-thread leg, the cleared-mask legs with their liveness control and
# engine-pin assertion). Needs the generated engine-pin header
# (semb_engine_pin.h) that is otherwise PRIVATE to the `superembedder`
# target, and the platform thread library for its cross-thread leg. This
# test opens the mechanism synthetic model+tokenizer pair
# (build/_scratch/u1_pair/*.sslm) minted by tests/u1_raw_text_cells_check.py
# / tests/fixtures/regenerate_tokenizer_pair_fixture.py -- ctest does not
# order tests by dependency, so a run of ONLY this test on a fresh build
# reports SEMB_ARTIFACT_UNREADABLE at open, named in this test's own
# failure message, rather than a silent skip; running the full suite (or
# u1_raw_text_cells_check once) mints the pair first.
#
# U2 cloud build: registered on WIN32 only. The test includes <windows.h>
# unconditionally (its cleared-mask and environment legs are Win32 calls), so
# on Linux it cannot compile and a GCC build of the tree never completed. The
# test is unchanged; the WSL/Linux members simply do not build it, as they
# could not before.
find_package(Threads REQUIRED)
if(WIN32)
	semb_add_cxx_test(c41_environment_invariance_test c41_environment_invariance_test.cpp)
	target_include_directories(c41_environment_invariance_test PRIVATE "${CMAKE_BINARY_DIR}/generated")
	target_link_libraries(c41_environment_invariance_test PRIVATE Threads::Threads)
endif()

# TE-182 (U1 slice 2's fourth test-author round, D-SLM6434 item 1): the
# interim ABI's own two bare cells over semb_interim_encode_batch_ps_n's
# optional-output contract (TE-149 coverage audit sec 7 items 3-4; TE-161
# review M-1, M-2) -- see the test file's own header comment. Plain,
# always-on, no product gating: it opens the mechanism synthetic pair
# directly through the interim path (content ids, not text), the identical
# hardcoded-path convention c41_environment_invariance_test above already
# uses.
semb_add_cxx_test(u1_interim_batch_optional_output_test u1_interim_batch_optional_output_test.cpp)

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

# TE-144 (U1 slice 1): C23, token-id determinism across the {machine, tier,
# toolchain} crossing. SEMB_TEST_SECOND_TOOLCHAIN_CXX names a second
# compiler (clang-cl) this driver also builds and runs the standalone
# instrument under, comparing digests; empty (the default) files that
# toolchain leg as UNREACHABLE rather than silently narrowing the crossing
# to one member. SEMB_U1_TOKENIZER (already defined below by the U1
# raw-text suite) doubles as this cell's own real-artifact gate, matching
# every other real-artifact leg's single-flag convention in this suite.
set(SEMB_TEST_SECOND_TOOLCHAIN_CXX "" CACHE FILEPATH
	"C23/second toolchain leg: a second C++ compiler (e.g. clang-cl.exe) this driver cross-builds the token-id instrument with (empty = filed UNREACHABLE)")
add_test(
	NAME c23_token_id_determinism_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/c23_token_id_determinism_check.py"
		--build-dir "${CMAKE_BINARY_DIR}"
		--engine-prefix "${SEMB_ENGINE_PREFIX}"
		--primary-cxx-compiler "${CMAKE_CXX_COMPILER}"
		--secondary-cxx-compiler "${SEMB_TEST_SECOND_TOOLCHAIN_CXX}"
		--tokenizer "${SEMB_U1_TOKENIZER}"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# TE-144 (U1 slice 1): C41 part 4, the instruction-level object-code scan.
# QUARANTINED per StandardsDocument.md sec 5.4 and this project's own C41
# disposition -- this test's own exit code is always 0 for a scan that
# completes (see the script's own header comment); it never gates the
# build on an uncommissioned instrument's reading. Depends on nothing but
# the already-built `superembedder` target's own object files.
set(SEMB_TEST_OBJDUMP "" CACHE FILEPATH
	"C41 part 4: path to llvm-objdump (empty tries PATH, then MISSING PREREQUISITE)")
if(SEMB_TEST_OBJDUMP STREQUAL "")
	find_program(_semb_test_llvm_objdump NAMES llvm-objdump llvm-objdump.exe
		PATHS "C:/Program Files/LLVM/bin")
	if(_semb_test_llvm_objdump)
		set(SEMB_TEST_OBJDUMP "${_semb_test_llvm_objdump}" CACHE FILEPATH
			"C41 part 4: configured llvm-objdump path" FORCE)
	endif()
endif()
add_test(
	NAME c41_part4_object_code_scan
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/c41_part4_object_code_scan.py"
		--build-dir "${CMAKE_BINARY_DIR}"
		--repo-root "${CMAKE_SOURCE_DIR}"
		--objdump "${SEMB_TEST_OBJDUMP}"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# TE-201 item 5: structural scope gate for C41 part 4.  Unlike the
# quarantined instruction reading, this compares the scan's declared source
# population to SEMB_LIBRARY_SOURCES and fails if any library TU is absent.
add_test(
	NAME c41_part4_scope_derivation_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/c41_part4_scope_derivation_check.py"
		--repo-root "${CMAKE_SOURCE_DIR}"
		--scan-script "${CMAKE_CURRENT_SOURCE_DIR}/c41_part4_object_code_scan.py"
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
# TE-137: this cell's own R1 leg is the real Qwen3-Embedding-0.6B artifact
# (633 MB, never committed; CI cannot hold it). Its S1-S5 mechanism legs run
# against a regenerated synthetic artifact and always execute regardless;
# R1 already reports MISSING PREREQUISITE (non-failing), never FAIL, when
# --model is absent -- which is every CI configure, since CI never sets
# SEMB_C12B_MODEL. The label is therefore applied ONLY when SEMB_C12B_MODEL
# is actually configured (a certification run, or a future CI change that
# points at the artifact): a ctest LABEL is per-test, not per-leg, so
# labelling this cell unconditionally would make `ctest -LE real_artifact`
# also exclude S1-S5 from every ordinary CI run, which gate 7 requires to
# keep running. Conditioned this way, the label is a no-op today (nothing
# in CI carries it, so `-LE real_artifact` changes nothing) and becomes a
# real, structural exclusion the moment anything -- CI included -- actually
# points this cell at the real artifact, without a name regex to maintain.
if(NOT SEMB_C12B_MODEL STREQUAL "")
	set_tests_properties(c12b_row_digest_check PROPERTIES LABELS "real_artifact")
endif()

# TE-180 item 4 (D-SLM6430 bare cell C): the store's committed real entry
# against tests/c12b_row_digest_check.py's own instrument (semb_c12b_
# row_digest), for every one of the 239 real documents -- mechanizing the
# manual cross-check Claude/Brunel/te164-slice3-build-2026-09-07.md sec 3
# and Claude/Curie/te168-slice3-oracle-fix-2026-09-07.md sec 3 both report
# as an executed, one-off probe. Independent of both epoch_store_emit's own
# construction and of C2's own oracle (tests/c2_lineage_equality_test.cpp).
# TE-190 item 5 (D-SLM6466 ruling 2, closing O2): the graded live entry is
# no longer a pinned fingerprint literal -- c12b_epoch_store_cross_check.py
# now SELECTS the epoch-store/live/<fingerprint>/ entry whose committed
# row-digest.tsv document count matches --corpus's own (239), refusing by
# name when none or more than one live entry matches, so a legitimate
# epoch rotation (a second live entry committed alongside this one) does
# not turn this cell red for a reason unrelated to the claim it grades.
# real_artifact only: needs the built instrument and the real model,
# exactly like c12b_row_digest_check above.
if(TARGET semb_c12b_row_digest AND NOT SEMB_C12B_MODEL STREQUAL "")
	add_test(
		NAME c12b_epoch_store_cross_check
		COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/c12b_epoch_store_cross_check.py"
			--instrument "${_semb_c12b_instrument}"
			--model "${SEMB_C12B_MODEL}"
			--corpus "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/c12b/corpus-239.tokens.tsv"
			--append-token-id 151643
			--store-root "${CMAKE_CURRENT_SOURCE_DIR}/.."
			--build-dir "${CMAKE_BINARY_DIR}"
		WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
	)
	set_tests_properties(c12b_epoch_store_cross_check PROPERTIES LABELS "real_artifact")
endif()

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
	NAME c12b_commission_workspace_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/c12b_commission_workspace_check.py"
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
# TE-94 (D-SLM6314 resolution): the contract cell's K-15 concurrency cells
# run threads, so it links the platform thread library explicitly.
find_package(Threads REQUIRED)
foreach(_semb_u1_cell u1_raw_text_contract_test u1_raw_text_parity_test)
	add_executable(${_semb_u1_cell} EXCLUDE_FROM_ALL ${_semb_u1_cell}.cpp)
	target_link_libraries(${_semb_u1_cell} PRIVATE superembedder superslm::superslm Threads::Threads)
	target_include_directories(${_semb_u1_cell} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
	# TE-94: the DIAGNOSTIC-ONLY twin under the retired 496d036 seven-member
	# semb_config (tests/semb_public_abi_contract.h's header comment). Built
	# only by the driver's --diag-legacy-layout pass; its results are [DIAG]
	# rows, never the suite's verdict.
	add_executable(${_semb_u1_cell}_legacy EXCLUDE_FROM_ALL ${_semb_u1_cell}.cpp)
	target_link_libraries(${_semb_u1_cell}_legacy PRIVATE superembedder superslm::superslm Threads::Threads)
	target_include_directories(${_semb_u1_cell}_legacy PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
	target_compile_definitions(${_semb_u1_cell}_legacy PRIVATE SEMB_CONTRACT_LEGACY_APPENDED_ID_MEMBER=1)
endforeach()

# ---------------------------------------------------------------------------
# TE-145 (U1 slice 2): semb_encode_batch's red suite. Both link against
# symbols undefined at this branch's own base c0f52d4
# (semb_encode_batch, and w_b_corpus_witness_test's semb_wb_digest), so both
# are EXCLUDE_FROM_ALL; tests/u1_batch_contract_check.py builds each on
# demand and reports the unresolved symbol by name, the same red-first shape
# tests/u1_raw_text_cells_check.py already uses. u1_batch_contract_test
# carries the cells that need no K-15 seam observable (the precedence/
# refusal/row-identity driver, plus C27's corpus form); u1_batch_workspace_test
# and w_b_corpus_witness_test are registered further below, inside
# semb_add_workspace_tests(), because the seam-observable cells (C4's
# no-forward-ran proof, C26's two races, C48, C49, C50) and the witness leg's
# own primitives (semb_encode_document_for_witness, semb_seam_serialize_document)
# need the identical testseam wiring u1_workspace_seam_test already uses.
# ---------------------------------------------------------------------------
add_executable(u1_batch_contract_test EXCLUDE_FROM_ALL u1_batch_contract_test.cpp)
target_link_libraries(u1_batch_contract_test PRIVATE superembedder superslm::superslm)
target_include_directories(u1_batch_contract_test PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")

set(_semb_batch_args --build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}")
if(NOT SEMB_C12B_MODEL STREQUAL "")
	list(APPEND _semb_batch_args --model "${SEMB_C12B_MODEL}")
endif()
if(NOT SEMB_U1_TOKENIZER STREQUAL "")
	list(APPEND _semb_batch_args --tokenizer "${SEMB_U1_TOKENIZER}")
endif()
add_test(
	NAME u1_batch_contract_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/u1_batch_contract_check.py" ${_semb_batch_args}
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
if(NOT SEMB_C12B_MODEL STREQUAL "" AND NOT SEMB_U1_TOKENIZER STREQUAL "")
	set_tests_properties(u1_batch_contract_check PROPERTIES LABELS "real_artifact" TIMEOUT 7200)
endif()

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
# TE-137: this driver's own PRODUCT legs need --model AND --tokenizer (the
# real Qwen3-Embedding-0.6B artifact and its converter-emitted tokenizer,
# neither committed; CI cannot hold them). Its MECHANISM legs (the synthetic
# model+tokenizer pair, K-01..K-17, P-00..P-05) always run regardless; the
# PRODUCT legs already report MISSING PREREQUISITE (non-failing), never
# FAIL, when either is absent -- every CI configure, since CI never sets
# SEMB_C12B_MODEL or SEMB_U1_TOKENIZER. See the c12b_row_digest_check label
# comment above for why the label is conditioned on both being configured
# rather than applied unconditionally: unconditional would make
# `ctest -LE real_artifact` also exclude the MECHANISM legs from every
# ordinary CI run, which gate 7 requires to keep running.
if(NOT SEMB_C12B_MODEL STREQUAL "" AND NOT SEMB_U1_TOKENIZER STREQUAL "")
	set_tests_properties(u1_raw_text_cells_check PROPERTIES LABELS "real_artifact")
endif()

# The public header pin: include/superembedder/semb.h must declare the five
# verbs, the opaque handle, both IN structs and the status enum -- names AND
# explicit ordinals (TE-94, P-5) -- exactly as the contract header does
# (extern "C" checks names, not types).
add_test(
	NAME u1_public_header_parity_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/u1_public_header_parity_check.py"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# ---------------------------------------------------------------------------
# TE-94 (D-SLM6314 resolution sec 7.1; K-16): the public header compiles as
# STRICT C on every platform that builds the library. Two halves:
#   (1) a BUILD-time cell -- tests/u1_public_header_strict_c.c compiled as an
#       object on the default build, in C MODE, by the SAME C++ driver this
#       tree is configured with: `/TC /W4 /WX` under cl and clang-cl,
#       `-x c -std=c99 -Wall -Wextra -Werror -pedantic` under GCC/Clang/
#       AppleClang. So a C++-only construct entering
#       include/superembedder/semb.h breaks `cmake --build` on every CI job
#       that builds the library;
#   (2) a ctest-time cell -- tests/u1_public_header_strict_c_check.py compiles
#       the same probe against the real header (must-accept) and against
#       mutated copies carrying C++ syntax (must-reject, each of which must
#       also compile as C++), so the cell is proven able to FAIL BY NAME.
# WHY THE C++ DRIVER IN C MODE RATHER THAN enable_language(C): this tree's
# every scratch configure -- tools/ci/run_configure_matrix.py,
# tests/c12b_independent_commission_check.py, tests/witness_structural_matrix.py,
# tools/engine_side_wa_perturbation.py, and a developer's clang-cl tree --
# passes CMAKE_CXX_COMPILER alone. Enabling C made CMake infer a C compiler
# on its own, and with clang-cl as CXX it inferred the GNU-style clang.exe
# and then handed it MSVC flags (executed: c12b_independent_commission_check
# FAILED under clang-cl at TE-94's first re-entry). Every driver this tree
# already uses compiles C when told to, so no second language is enabled.
# ---------------------------------------------------------------------------
if(CMAKE_CXX_COMPILER_ID STREQUAL "MSVC" OR CMAKE_CXX_COMPILER_FRONTEND_VARIANT STREQUAL "MSVC")
	set(_semb_strict_c_obj "${CMAKE_CURRENT_BINARY_DIR}/u1_public_header_strict_c.obj")
	set(_semb_strict_c_cmd "${CMAKE_CXX_COMPILER}" /nologo /TC /W4 /WX /c
		"/I${CMAKE_CURRENT_SOURCE_DIR}/../include" "/Fo${_semb_strict_c_obj}"
		"${CMAKE_CURRENT_SOURCE_DIR}/u1_public_header_strict_c.c")
else()
	set(_semb_strict_c_obj "${CMAKE_CURRENT_BINARY_DIR}/u1_public_header_strict_c.o")
	set(_semb_strict_c_cmd "${CMAKE_CXX_COMPILER}" -x c -std=c99 -Wall -Wextra -Werror -pedantic -c
		"-I${CMAKE_CURRENT_SOURCE_DIR}/../include" -o "${_semb_strict_c_obj}"
		"${CMAKE_CURRENT_SOURCE_DIR}/u1_public_header_strict_c.c")
endif()
add_custom_command(
	OUTPUT "${_semb_strict_c_obj}"
	COMMAND ${_semb_strict_c_cmd}
	DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/u1_public_header_strict_c.c"
		"${CMAKE_CURRENT_SOURCE_DIR}/../include/superembedder/semb.h"
	COMMENT "K-16: compiling include/superembedder/semb.h as strict C"
	VERBATIM
)
add_custom_target(u1_public_header_strict_c ALL DEPENDS "${_semb_strict_c_obj}")
add_test(
	NAME u1_public_header_strict_c_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/u1_public_header_strict_c_check.py"
		--c-compiler "${CMAKE_CXX_COMPILER}"
		--cxx-compiler "${CMAKE_CXX_COMPILER}"
		--compiler-id "${CMAKE_CXX_COMPILER_ID}"
		--frontend "${CMAKE_CXX_COMPILER_FRONTEND_VARIANT}"
		--include-dir "${CMAKE_CURRENT_SOURCE_DIR}/../include"
		--scratch "${CMAKE_BINARY_DIR}/_u1_strict_c"
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
# TE-137: this cell's own "R real candidate arms" leg needs --model (the
# real Qwen3-Embedding-0.6B artifact, never committed; CI cannot hold it).
# Its "S synthetic pair arms" leg (the commissioning proof over the
# synthetic model+tokenizer pair) always runs regardless; the R leg already
# reports MISSING PREREQUISITE (non-failing), never FAIL, when --model is
# absent -- every CI configure, since CI never sets SEMB_C12B_MODEL. See
# the c12b_row_digest_check label comment above for why the label is
# conditioned on SEMB_C12B_MODEL rather than applied unconditionally:
# unconditional would make `ctest -LE real_artifact` also exclude the
# "S synthetic pair arms" leg from every ordinary CI run, which gate 7
# requires to keep running.
if(NOT SEMB_C12B_MODEL STREQUAL "")
	set_tests_properties(u1_trailing_special_mutants_check PROPERTIES LABELS "real_artifact")
endif()

# TE-114: create the seam target in the SAME directory scope as production.
# CMake source properties are directory-scoped, independently of target usage.
# A deferred root-directory call shares every source property structurally,
# including later assignments, custom properties and future CMake properties.
# The test artifacts remain excluded from ALL and are never installed.
function(semb_add_workspace_tests)
  find_package(Threads REQUIRED)
  set(_semb_test_dir "${CMAKE_CURRENT_FUNCTION_LIST_DIR}")
  set(_semb_seam_sources)
  foreach(_source IN LISTS SEMB_LIBRARY_SOURCES)
    get_filename_component(_absolute "${_source}" ABSOLUTE BASE_DIR "${CMAKE_SOURCE_DIR}")
    list(APPEND _semb_seam_sources "${_absolute}")
  endforeach()
  get_target_property(_production_sources superembedder SOURCES)
  set(_production_normalized)
  foreach(_source IN LISTS _production_sources)
    get_filename_component(_absolute "${_source}" ABSOLUTE BASE_DIR "${CMAKE_SOURCE_DIR}")
    list(APPEND _production_normalized "${_absolute}")
  endforeach()
  if(NOT _production_normalized STREQUAL _semb_seam_sources)
    message(FATAL_ERROR "K-15 interface: normalized source membership mismatch")
  endif()
  add_library(superembedder_testseam STATIC EXCLUDE_FROM_ALL ${_semb_seam_sources})
  set(_semb_interface_properties
    CXX_STANDARD CXX_STANDARD_REQUIRED CXX_EXTENSIONS COMPILE_FEATURES
    COMPILE_OPTIONS COMPILE_DEFINITIONS INCLUDE_DIRECTORIES SYSTEM
    INTERFACE_COMPILE_FEATURES INTERFACE_COMPILE_OPTIONS INTERFACE_COMPILE_DEFINITIONS
    INTERFACE_INCLUDE_DIRECTORIES INTERFACE_SYSTEM_INCLUDE_DIRECTORIES
    LINK_LIBRARIES INTERFACE_LINK_LIBRARIES LINK_OPTIONS INTERFACE_LINK_OPTIONS
    LINK_DIRECTORIES INTERFACE_LINK_DIRECTORIES LINK_DEPENDS INTERFACE_LINK_DEPENDS
    STATIC_LIBRARY_OPTIONS LINK_FLAGS MSVC_RUNTIME_LIBRARY MSVC_DEBUG_INFORMATION_FORMAT
    POSITION_INDEPENDENT_CODE INTERPROCEDURAL_OPTIMIZATION OSX_ARCHITECTURES
    CXX_VISIBILITY_PRESET VISIBILITY_INLINES_HIDDEN)
  foreach(_config DEBUG RELEASE RELWITHDEBINFO MINSIZEREL ${CMAKE_CONFIGURATION_TYPES})
    string(TOUPPER "${_config}" _upper)
    list(APPEND _semb_interface_properties
      COMPILE_DEFINITIONS_${_upper} LINK_FLAGS_${_upper}
      STATIC_LIBRARY_FLAGS_${_upper} INTERPROCEDURAL_OPTIMIZATION_${_upper}
      OSX_ARCHITECTURES_${_upper})
  endforeach()
  list(REMOVE_DUPLICATES _semb_interface_properties)
  foreach(_property IN LISTS _semb_interface_properties)
    get_target_property(_value superembedder ${_property})
    if(NOT _value STREQUAL "_value-NOTFOUND")
      set_property(TARGET superembedder_testseam PROPERTY ${_property} "${_value}")
    endif()
  endforeach()
  get_target_property(_dependencies superembedder MANUALLY_ADDED_DEPENDENCIES)
  if(_dependencies)
    add_dependencies(superembedder_testseam ${_dependencies})
  endif()
  target_compile_definitions(superembedder_testseam PRIVATE SEMB_ENABLE_WORKSPACE_TEST_SEAM=1)
  target_include_directories(superembedder_testseam PRIVATE "${_semb_test_dir}")
  add_executable(u1_workspace_seam_test EXCLUDE_FROM_ALL "${_semb_test_dir}/u1_workspace_seam_test.cpp")
  target_link_libraries(u1_workspace_seam_test PRIVATE superembedder_testseam superslm::superslm Threads::Threads)
  target_include_directories(u1_workspace_seam_test PRIVATE "${_semb_test_dir}")
  # TE-213: a private worker for te196's equal-hash I5 cell. It is invoked
  # only by the ordinary te196 driver and is never registered as a test.
  add_executable(te213_manifest_binding_testseam_worker EXCLUDE_FROM_ALL "${_semb_test_dir}/te196_manifest_binding_test.cpp")
  target_link_libraries(te213_manifest_binding_testseam_worker PRIVATE superembedder_testseam superslm::superslm Threads::Threads)
  target_include_directories(te213_manifest_binding_testseam_worker PRIVATE "${_semb_test_dir}" "${CMAKE_SOURCE_DIR}/src/superembedder")
  add_dependencies(te196_manifest_binding_test te213_manifest_binding_testseam_worker)
  # TE-145 (U1 slice 2): the seam-observable batch cells (C4's no-forward-ran
  # proof, C26's two races, C48, C49, C50) and the real W-B witness leg both
  # need the identical testseam wiring this function already builds for
  # u1_workspace_seam_test -- registered here rather than as ordinary
  # semb_add_cxx_test targets because semb_encode_batch (and, for the
  # witness leg, semb_wb_digest) do not exist at this branch's own base
  # c0f52d4; both are EXCLUDE_FROM_ALL, built and run on demand by
  # tests/u1_batch_contract_check.py (the same driver that builds
  # u1_batch_contract_test above).
  add_executable(u1_batch_workspace_test EXCLUDE_FROM_ALL "${_semb_test_dir}/u1_batch_workspace_test.cpp")
  target_link_libraries(u1_batch_workspace_test PRIVATE superembedder_testseam superslm::superslm Threads::Threads)
  target_include_directories(u1_batch_workspace_test PRIVATE "${_semb_test_dir}")
  add_executable(w_b_corpus_witness_test EXCLUDE_FROM_ALL "${_semb_test_dir}/w_b_corpus_witness_test.cpp")
  target_link_libraries(w_b_corpus_witness_test PRIVATE superembedder_testseam superslm::superslm)
  target_include_directories(w_b_corpus_witness_test PRIVATE "${_semb_test_dir}")
  set_target_properties(superembedder_testseam PROPERTIES
    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/tests")
  set_target_properties(u1_workspace_seam_test u1_batch_workspace_test w_b_corpus_witness_test te213_manifest_binding_testseam_worker PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/tests")
  # Explicit diagnostic configurations compile generated fault copies only into
  # the noninstalled seam target. The production source/target is unchanged.
  set(SEMB_WORKSPACE_DIAGNOSTIC_ADAPTER "" CACHE FILEPATH "K-15 diagnostic adapter copy (tests only)")
  option(SEMB_WORKSPACE_DELAY_REFUSAL_HELPERS "K-15 test-only late-success helper control" OFF)
  if(SEMB_WORKSPACE_DIAGNOSTIC_ADAPTER)
    if(NOT EXISTS "${SEMB_WORKSPACE_DIAGNOSTIC_ADAPTER}")
      message(FATAL_ERROR "K-15 diagnostic adapter copy is absent")
    endif()
    get_target_property(_diagnostic_sources superembedder_testseam SOURCES)
    list(FIND _diagnostic_sources "${SEMB_ENGINE_ADAPTER_TU}" _adapter_index)
    if(_adapter_index LESS 0)
      message(FATAL_ERROR "K-15 diagnostic adapter source is not uniquely selected")
    endif()
    list(REMOVE_AT _diagnostic_sources ${_adapter_index})
    list(APPEND _diagnostic_sources "${SEMB_WORKSPACE_DIAGNOSTIC_ADAPTER}")
    set_property(TARGET superembedder_testseam PROPERTY SOURCES "${_diagnostic_sources}")
    # The copied TU's local internal header remains the real source header.
    get_filename_component(_adapter_include "${SEMB_ENGINE_ADAPTER_TU}" DIRECTORY)
    set_property(SOURCE "${SEMB_WORKSPACE_DIAGNOSTIC_ADAPTER}" PROPERTY INCLUDE_DIRECTORIES "${_adapter_include}")
  endif()
  if(SEMB_WORKSPACE_DELAY_REFUSAL_HELPERS)
    target_compile_definitions(u1_workspace_seam_test PRIVATE SEMB_WORKSPACE_DELAY_REFUSAL_HELPERS=1)
  endif()
  # Evaluated target properties retain generator expressions and imported-engine
  # usage. Actual per-source compiler invocations are checked independently.
  set(_semb_link_manifest "")
  foreach(_property LINK_LIBRARIES INTERFACE_LINK_LIBRARIES LINK_OPTIONS INTERFACE_LINK_OPTIONS
      LINK_DIRECTORIES INTERFACE_LINK_DIRECTORIES STATIC_LIBRARY_OPTIONS MSVC_RUNTIME_LIBRARY
      CXX_STANDARD CXX_STANDARD_REQUIRED CXX_EXTENSIONS)
    string(APPEND _semb_link_manifest "${_property}.production=$<TARGET_GENEX_EVAL:superembedder,$<TARGET_PROPERTY:superembedder,${_property}>>\n")
    string(APPEND _semb_link_manifest "${_property}.testseam=$<TARGET_GENEX_EVAL:superembedder_testseam,$<TARGET_PROPERTY:superembedder_testseam,${_property}>>\n")
  endforeach()
  string(APPEND _semb_link_manifest "engine=$<TARGET_FILE:superslm::superslm>\nselection=${SEMB_C38_DEFINE_TARGET}\n")
  file(GENERATE OUTPUT "${CMAKE_BINARY_DIR}/tests/k15-interface-$<CONFIG>.txt" CONTENT "${_semb_link_manifest}")
  set_target_properties(superembedder superembedder_testseam PROPERTIES EXPORT_COMPILE_COMMANDS ON)
  set(CMAKE_EXPORT_COMPILE_COMMANDS ON CACHE BOOL "Export actual compiler commands for K-15 parity" FORCE)
  add_test(NAME u1_workspace_seam_absent_check
    COMMAND "${Python3_EXECUTABLE}" "${_semb_test_dir}/u1_workspace_seam_absent_check.py"
      --production "$<TARGET_FILE:superembedder>" --testseam "$<TARGET_FILE:superembedder_testseam>"
      --build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}"
    WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}")
  if(CMAKE_GENERATOR MATCHES "Ninja")
    set(_semb_workspace_ninja "${CMAKE_MAKE_PROGRAM}")
  else()
    find_program(_semb_workspace_ninja NAMES ninja REQUIRED)
  endif()
  set(_semb_workspace_control_args
    --engine-lock "${SEMB_ENGINE_LOCK_FILE}"
    --engine-prefix "${SEMB_ENGINE_PREFIX}"
    --cmake-executable "${CMAKE_COMMAND}"
    --ninja-executable "${_semb_workspace_ninja}"
    --cxx-compiler "${CMAKE_CXX_COMPILER}")
  if(NOT SEMB_C38_DEFINE_TARGET STREQUAL "")
    list(APPEND _semb_workspace_control_args --c38-define-target "${SEMB_C38_DEFINE_TARGET}")
  endif()
  if(CMAKE_RC_COMPILER)
    list(APPEND _semb_workspace_control_args --rc-compiler "${CMAKE_RC_COMPILER}")
  endif()
  if(CMAKE_MT)
    list(APPEND _semb_workspace_control_args --mt-executable "${CMAKE_MT}")
  endif()
  add_test(NAME u1_workspace_source_properties_check
    COMMAND "${Python3_EXECUTABLE}" "${_semb_test_dir}/u1_workspace_source_properties_check.py"
      --build-dir "${CMAKE_BINARY_DIR}/_k15_source_properties" ${_semb_workspace_control_args}
    WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}")
  add_test(NAME u1_workspace_control_vitality_check
    COMMAND "${Python3_EXECUTABLE}" "${_semb_test_dir}/u1_workspace_control_vitality_check.py"
      --build-dir "${CMAKE_BINARY_DIR}/_k15_controls" ${_semb_workspace_control_args}
    WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}")
  set_tests_properties(u1_workspace_source_properties_check u1_workspace_control_vitality_check
    PROPERTIES RUN_SERIAL TRUE)
  # This target is created after the root's ordinary precision assertion.
  # Re-run the same real gate with the final complete target population.
  semb_assert_precise_fp()
endfunction()
if(DEFINED SEMB_LIBRARY_SOURCES)
  cmake_language(DEFER DIRECTORY "${CMAKE_SOURCE_DIR}" CALL semb_add_workspace_tests)
endif()

# ---------------------------------------------------------------------------
# TE-162 (U1 slice 3): the epoch store's four able-to-fail constructions and
# C2 (`Claude/Plans/te140-u1-remainder-sequencing.md` sec 4.3;
# `Claude/Plans/SuperEmbedder_Plan.md` sec 8, C32/C2). Five registrations,
# one per cell the dispatch's own brief enumerates:
#   cell 1 -> epoch_store_check              (the store check itself)
#   cell 2 -> epoch_store_constructions_check (the constructions population, twelve as of TE-170/TE-180)
#   cell 3 -> c2_lineage_equality_test_synthetic / _real_artifact (C2)
#   cell 4 -> folded into c2_lineage_equality_test_real_artifact
#   cell 5 -> epoch_store_gitattributes_check
# `epoch-store/` does not exist anywhere in this tree at this branch's own
# base (confirmed this round, matching `Claude/Mendeleev/
# te142-te140-subplan-coverage-audit-2026-09-06.md` sec 1's own absent-
# surface grep): the builder's round is what makes cells 1/2/3/4 stop
# reporting their own named red state.

# The C++ gate cell (C2 + cell 4), linked against the product library
# directly (semb_encode_document_for_witness, semb_seam_serialize_document
# and semb_encode are all already built at Slice 0's own baseline).
add_executable(c2_lineage_equality_test "${CMAKE_CURRENT_SOURCE_DIR}/c2_lineage_equality_test.cpp")
target_link_libraries(c2_lineage_equality_test PRIVATE superembedder superslm::superslm)
target_include_directories(c2_lineage_equality_test PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
set_target_properties(c2_lineage_equality_test PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/tests")

add_test(
	NAME c2_lineage_equality_test_synthetic
	COMMAND c2_lineage_equality_test
		--regen-synthetic-pair
		--dims 32
		--tokens "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/c12b/synthetic-corpus.tokens.tsv"
		--terminator-id 262
		--store-root "${CMAKE_CURRENT_SOURCE_DIR}/../epoch-store"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

if(NOT SEMB_C12B_MODEL STREQUAL "" AND NOT SEMB_U1_TOKENIZER STREQUAL "")
	add_test(
		NAME c2_lineage_equality_test_real_artifact
		COMMAND c2_lineage_equality_test
			--model "${SEMB_C12B_MODEL}"
			--tokenizer "${SEMB_U1_TOKENIZER}"
			--dims 1024
			--tokens "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/c12b/corpus-239.tokens.tsv"
			--terminator-id 151643
			--store-root "${CMAKE_CURRENT_SOURCE_DIR}/../epoch-store"
			--corpus-jsonl "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/c12b/corpus-239.jsonl"
		WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
	)
	set_tests_properties(c2_lineage_equality_test_real_artifact PROPERTIES LABELS "real_artifact")
endif()

# TE-180 item 2 (D-SLM6428 bare cell A): an empty or unreadable
# --corpus-jsonl is a registered red-by-name cell. c2_lineage_equality_test.cpp's
# own S7 block (:444-455) is the LAST thing main() runs -- AFTER the
# synthetic pair regeneration, the mutation-proof block's two
# ComputeSeamDigest calls (:345-361), the live-fingerprint read via Open()
# and semb_encode (:366-385), the lineage.tsv read (:392-404) and the
# whole per-document C2 loop (:408-434) -- confirmed by reading the source
# AND by execution (TE-190 M1): the run prints "C2 summary: 8 of 8
# documents checked, 0 mismatch(es)" before the S7 FAIL row. It is reached
# by the SYNTHETIC leg's own args (--regen-synthetic-pair, no real
# artifact) because --corpus-jsonl is the only gate S7 checks, not because
# S7 runs early; no real_artifact leg is needed. Each of the four
# registrations below therefore re-runs the entire synthetic C2 loop to
# reach S7 -- the ~1s-per-cell cost these four cells carry is C2's own, not
# S7's, and none of the four can distinguish S7 firing from any other cell
# in the same TU failing (M1, TE-190). Two constructions (an empty file; a
# path that does not exist),
# both reaching the same S7 branch, whose message is c2_lineage_equality_test.cpp's
# own ternary: "carries no readable document (empty corpus)" for the empty
# file, "cannot open <path>" for the missing path, then the shared "-- an
# empty or unreadable corpus is a FAIL, not MISSING PREREQUISITE (S7,
# TE-174)" tail. TE-190 M3: asserting only the shared tail (as a single
# regex both _fails_named cells shared) cannot tell the two branches apart
# -- if the configure-time empty file is absent when ctest runs, the
# "empty" registration's own command hits the SAME "cannot open <path>"
# branch the missing-path registration exercises, and the shared-tail
# regex still matches, so all four cells stay green while only the
# cannot-open branch is exercised. Each construction below is therefore
# asserted against its OWN discriminating regex (the empty file's "no
# readable document"; the missing path's "cannot open"), never the shared
# tail alone.
#
# CTEST PROPERTY FINDING, verified by execution this round rather than
# assumed: WILL_FAIL and PASS_REGULAR_EXPRESSION do NOT conjoin when set on
# the same ctest test. Once PASS_REGULAR_EXPRESSION is present, ctest's own
# pass/fail is driven ENTIRELY by whether the regex is found in the
# process's output -- the exit code is ignored outright -- and WILL_FAIL
# then inverts THAT regex-driven verdict, never the exit code. A four-cell
# probe (exit0/exit1 crossed with regex-present/absent, both properties
# set together) confirmed this: exit1+regex-present read ctest-FAILED
# ("Required regular expression found"), the opposite of what treating the
# two properties as an AND would predict; exit0+regex-absent read
# ctest-PASSED, likewise inverted from an AND reading. So "asserting
# non-zero exit AND the S7 FAIL row" (the brief's own phrasing) is realized
# below as TWO separate, single-purpose registrations per construction --
# one WILL_FAIL-only (the exit-code fact) and one PASS_REGULAR_EXPRESSION-
# only (the message fact) -- never as one registration combining both
# properties, which the probe showed does not assert their conjunction.
file(WRITE "${CMAKE_BINARY_DIR}/_epoch_store_cell_a/empty_corpus.jsonl" "")
# TE-190 M3: each construction's own discriminating half of the ternary,
# never the shared tail alone -- see the comment above this block.
set(_c2_s7_empty_message_regex "no readable document")
set(_c2_s7_missing_message_regex "cannot open")

add_test(
	NAME c2_lineage_equality_test_synthetic_empty_corpus_jsonl_exits_nonzero
	COMMAND c2_lineage_equality_test
		--regen-synthetic-pair
		--dims 32
		--tokens "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/c12b/synthetic-corpus.tokens.tsv"
		--terminator-id 262
		--store-root "${CMAKE_CURRENT_SOURCE_DIR}/../epoch-store"
		--corpus-jsonl "${CMAKE_BINARY_DIR}/_epoch_store_cell_a/empty_corpus.jsonl"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
set_tests_properties(c2_lineage_equality_test_synthetic_empty_corpus_jsonl_exits_nonzero PROPERTIES WILL_FAIL TRUE)

add_test(
	NAME c2_lineage_equality_test_synthetic_empty_corpus_jsonl_fails_named
	COMMAND c2_lineage_equality_test
		--regen-synthetic-pair
		--dims 32
		--tokens "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/c12b/synthetic-corpus.tokens.tsv"
		--terminator-id 262
		--store-root "${CMAKE_CURRENT_SOURCE_DIR}/../epoch-store"
		--corpus-jsonl "${CMAKE_BINARY_DIR}/_epoch_store_cell_a/empty_corpus.jsonl"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
set_tests_properties(c2_lineage_equality_test_synthetic_empty_corpus_jsonl_fails_named PROPERTIES
	PASS_REGULAR_EXPRESSION "${_c2_s7_empty_message_regex}")

add_test(
	NAME c2_lineage_equality_test_synthetic_missing_corpus_jsonl_exits_nonzero
	COMMAND c2_lineage_equality_test
		--regen-synthetic-pair
		--dims 32
		--tokens "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/c12b/synthetic-corpus.tokens.tsv"
		--terminator-id 262
		--store-root "${CMAKE_CURRENT_SOURCE_DIR}/../epoch-store"
		--corpus-jsonl "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/c12b/__te180_cell_a_missing_corpus.jsonl"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
set_tests_properties(c2_lineage_equality_test_synthetic_missing_corpus_jsonl_exits_nonzero PROPERTIES WILL_FAIL TRUE)

add_test(
	NAME c2_lineage_equality_test_synthetic_missing_corpus_jsonl_fails_named
	COMMAND c2_lineage_equality_test
		--regen-synthetic-pair
		--dims 32
		--tokens "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/c12b/synthetic-corpus.tokens.tsv"
		--terminator-id 262
		--store-root "${CMAKE_CURRENT_SOURCE_DIR}/../epoch-store"
		--corpus-jsonl "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/c12b/__te180_cell_a_missing_corpus.jsonl"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
set_tests_properties(c2_lineage_equality_test_synthetic_missing_corpus_jsonl_fails_named PROPERTIES
	PASS_REGULAR_EXPRESSION "${_c2_s7_missing_message_regex}")

# The Python-side support tool cell 1 and cell 2 both shell out to, to
# materialise an independently-derived store entry (tests/
# epoch_store_emit.cpp's own header comment states the full computation).
add_executable(epoch_store_emit "${CMAKE_CURRENT_SOURCE_DIR}/epoch_store_emit.cpp")
target_link_libraries(epoch_store_emit PRIVATE superembedder superslm::superslm)
target_include_directories(epoch_store_emit PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
set_target_properties(epoch_store_emit PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/tests")

# Cell 1: the store check itself.
add_test(
	NAME epoch_store_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/epoch_store_check.py"
		--repo-root "${CMAKE_CURRENT_SOURCE_DIR}/.."
		--emit-binary "$<TARGET_FILE:epoch_store_emit>"
		--scratch-dir "${CMAKE_BINARY_DIR}/_epoch_store_check"
		--real-model "${SEMB_C12B_MODEL}"
		--real-tokenizer "${SEMB_U1_TOKENIZER}"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
if(NOT SEMB_C12B_MODEL STREQUAL "")
	set_tests_properties(epoch_store_check PROPERTIES LABELS "real_artifact")
endif()

# Cell 2: the constructions population (twelve as of TE-170/TE-180), in a scratch git repository.
add_test(
	NAME epoch_store_constructions_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/epoch_store_constructions_check.py"
		--repo-root "${CMAKE_CURRENT_SOURCE_DIR}/.."
		--emit-binary "$<TARGET_FILE:epoch_store_emit>"
		--scratch-dir "${CMAKE_BINARY_DIR}/_epoch_store_constructions"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# Cell 5: the .gitattributes pin.
add_test(
	NAME epoch_store_gitattributes_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/epoch_store_gitattributes_check.py"
		--repo-root "${CMAKE_CURRENT_SOURCE_DIR}/.."
		--scratch-dir "${CMAKE_BINARY_DIR}/_epoch_store_gitattributes"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# TE-163 (U1 slice 4): the bank pair / manifest sidecar / semb_bank_open
# red suite (Claude/Bach/briefs/te163-slice4-red.md) -- cells 1, 2, 3, 5, 6.
# Links against symbols undefined at this branch's own base 7af22da
# (semb_bake_to_path, semb_bank_open, semb_bank_close), so it is
# EXCLUDE_FROM_ALL; tests/te163_bank_pair_check.py builds it on demand and
# reports the unresolved symbol(s) by name, the same red-first shape
# tests/u1_batch_contract_check.py already uses for Slice 2. No K-15 seam
# observable is needed (bake/open/close are ordinary superembedder entries,
# not seam-instrumented), so this links plain `superembedder`, not
# `superembedder_testseam`.
# ---------------------------------------------------------------------------
add_executable(te163_bank_pair_test EXCLUDE_FROM_ALL te163_bank_pair_test.cpp)
target_link_libraries(te163_bank_pair_test PRIVATE superembedder superslm::superslm)
target_include_directories(te163_bank_pair_test PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")

set(_semb_te163_args --build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}")
if(NOT SEMB_C12B_MODEL STREQUAL "")
	list(APPEND _semb_te163_args --model "${SEMB_C12B_MODEL}")
endif()
if(NOT SEMB_U1_TOKENIZER STREQUAL "")
	list(APPEND _semb_te163_args --tokenizer "${SEMB_U1_TOKENIZER}")
endif()
add_test(
	NAME te163_bank_pair_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te163_bank_pair_check.py" ${_semb_te163_args}
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
if(NOT SEMB_C12B_MODEL STREQUAL "" AND NOT SEMB_U1_TOKENIZER STREQUAL "")
	set_tests_properties(te163_bank_pair_check PROPERTIES LABELS "real_artifact")
endif()

# TE-163 cell 4: C34 legs (e)/(h), the manifest-honesty scratch-build
# mutation proof (SEMB_ADAPTER_ID_MISMATCH / SEMB_PS_VERSION_LABEL_MISMATCH).
# A compiled-in-constant mutation cannot be driven from an already-linked
# executable -- this driver clones the source tree, edits one label constant
# in the clone, reconfigures and rebuilds a scratch tree, and asserts the
# bake refuses by name; restores, rebuilds, asserts it writes. Red at
# 7af22da: semb_bake_to_path and both compiled-in label constants
# (SEMB_ADAPTER_SELF_ID, SEMB_PS_VERSION_LABEL) do not exist yet -- this
# driver reports RED-UNIMPLEMENTED by name rather than failing to configure.
set(SEMB_TEST_ENGINE_PREFIX_TE163 "${SEMB_ENGINE_PREFIX}" CACHE PATH
	"C34 (e)/(h) scratch-build mutation proof: the engine install prefix its scratch reconfigure links against")
# Both legs bake with the real pair and the cell has no mechanism leg, so it
# is registered only when the pair is configured -- the form this file uses
# for purely real cells (c2_lineage_equality_test_real_artifact,
# te264_raw_equals_batch_real_artifact). An unconfigured tree does not
# register it at all, so ctest cannot report it Passed having run nothing.
# (The conditional-label form c12b_row_digest_check's comment sets out is for
# mixed cells, whose mechanism legs must keep running in every tree.) The
# driver's own MISSING PREREQUISITE return stays as the guard for direct
# invocation.
if(NOT SEMB_C12B_MODEL STREQUAL "" AND NOT SEMB_U1_TOKENIZER STREQUAL "")
	add_test(
		NAME te163_c34_manifest_honesty_check
		COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te163_c34_manifest_honesty_check.py"
			--repo-root "${CMAKE_SOURCE_DIR}"
			--engine-prefix "${SEMB_TEST_ENGINE_PREFIX_TE163}"
			--cmake-executable "${CMAKE_COMMAND}"
			--cxx-compiler "${CMAKE_CXX_COMPILER}"
			--python-executable "${Python3_EXECUTABLE}"
			--model "${SEMB_C12B_MODEL}"
			--tokenizer "${SEMB_U1_TOKENIZER}"
		WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
	)
	set_tests_properties(te163_c34_manifest_honesty_check PROPERTIES LABELS "real_artifact")
endif()

# ---------------------------------------------------------------------------
# TE-196 (U1 slice 4 fix round): the manifest-binding driver -- the cells
# for the TE-193 review's P-3 (channels under schemaVersion 1) and the
# later items of the same round as their cells land in the binary. Every
# symbol it links exists at 21b1735, but it needs the synthetic mechanism
# pair and a scratch dir as runtime arguments, so it follows the
# te163_bank_pair_check shape: EXCLUDE_FROM_ALL, built and run on demand
# by tests/te196_manifest_binding_check.py (which also ensures the pair,
# since ctest does not order tests by dependency). The mechanism-bake
# scaffolding inside the binary is COPIED from
# tests/te163_bank_pair_test.cpp per this round's own brief (TE-192 owns
# that file in a concurrent round -- nothing is factored out of it). The
# src include dir is for json_lite.h, the product's own internal JSON
# reader (the same include the te166_bake_239_timer target already uses).
# ---------------------------------------------------------------------------
add_executable(te196_manifest_binding_test EXCLUDE_FROM_ALL te196_manifest_binding_test.cpp)
target_link_libraries(te196_manifest_binding_test PRIVATE superembedder superslm::superslm)
target_include_directories(te196_manifest_binding_test PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}"
	"${CMAKE_SOURCE_DIR}/src/superembedder")

set(_semb_te196_args --build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}")
add_test(
	NAME te196_manifest_binding_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te196_manifest_binding_check.py" ${_semb_te196_args}
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# TE-194 (U1 slice 5): the query path / real W-Q witness leg red suite
# (Claude/Bach/briefs/te194-slice5-red.md) -- cells 1, 2, 4, 5, 6, plus the
# fingerprint-rotation fixed point. Appended as ONE CONTIGUOUS BLOCK per
# this round's own Writable contract, so the merge with TE-192's own append
# (a sibling block, same convention) is a single ordered concatenation.
# ---------------------------------------------------------------------------

# Cells 1, 2, 6 -- links plain `superembedder` (no K-15 seam needed: cell
# 1's bank-in-use leg and C8's three legs are all sequential constructions).
# Undefined at link at this branch's own base 21b1735 (semb_query_open,
# semb_query_encode, semb_query_close, semb_fingerprint_of do not exist) --
# EXCLUDE_FROM_ALL; tests/te194_query_check.py builds it on demand and
# reports the unresolved symbol(s) by name, the identical shape
# tests/te163_bank_pair_check.py already uses.
add_executable(te194_query_test EXCLUDE_FROM_ALL te194_query_test.cpp)
target_link_libraries(te194_query_test PRIVATE superembedder superslm::superslm)
target_include_directories(te194_query_test PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")

add_test(
	NAME te194_query_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te194_query_check.py"
		--build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}"
		--model "${SEMB_C12B_MODEL}" --tokenizer "${SEMB_U1_TOKENIZER}"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
if(NOT SEMB_C12B_MODEL STREQUAL "" AND NOT SEMB_U1_TOKENIZER STREQUAL "")
	set_tests_properties(te194_query_check PROPERTIES LABELS "real_artifact")
endif()

# Cell 3 / C26's remaining two races -- needs the K-15 seam
# (`superembedder_testseam`), so this target's own registration is DEFERRED
# to run AFTER semb_add_workspace_tests() (tests/CMakeLists.txt's own
# earlier `cmake_language(DEFER DIRECTORY ... CALL semb_add_workspace_tests)`)
# has created that target -- deferred calls run in the order they were
# scheduled, and this one is scheduled later in the same file, so
# superembedder_testseam exists by the time this function body runs.
function(semb_add_te194_query_workspace_tests)
  if(NOT TARGET superembedder_testseam)
    return()  # semb_add_workspace_tests() itself only runs when SEMB_LIBRARY_SOURCES is defined
  endif()
  set(_semb_te194_test_dir "${CMAKE_CURRENT_FUNCTION_LIST_DIR}")
  add_executable(te194_query_workspace_test EXCLUDE_FROM_ALL "${_semb_te194_test_dir}/te194_query_workspace_test.cpp")
  target_link_libraries(te194_query_workspace_test PRIVATE superembedder_testseam superslm::superslm Threads::Threads)
  target_include_directories(te194_query_workspace_test PRIVATE "${_semb_te194_test_dir}")
  add_test(
    NAME te194_query_workspace_check
    COMMAND "${Python3_EXECUTABLE}" "${_semb_te194_test_dir}/te194_query_workspace_check.py"
      --build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}"
    WORKING_DIRECTORY "${_semb_te194_test_dir}/.."
  )
endfunction()
if(DEFINED SEMB_LIBRARY_SOURCES)
  cmake_language(DEFER DIRECTORY "${CMAKE_SOURCE_DIR}" CALL semb_add_te194_query_workspace_tests)
endif()

function(semb_add_te222_query_ownership_tests)
  if(NOT TARGET superembedder_testseam)
    return()
  endif()
  set(_semb_te222_test_dir "${CMAKE_CURRENT_FUNCTION_LIST_DIR}")
  add_executable(te222_query_ownership_test EXCLUDE_FROM_ALL
                 "${_semb_te222_test_dir}/te222_query_ownership_test.cpp")
  target_link_libraries(te222_query_ownership_test PRIVATE superembedder_testseam superslm::superslm Threads::Threads)
  target_include_directories(te222_query_ownership_test PRIVATE "${_semb_te222_test_dir}")
  add_test(
    NAME te222_query_ownership_check
    COMMAND "${Python3_EXECUTABLE}" "${_semb_te222_test_dir}/te222_query_ownership_check.py"
      --build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}"
    WORKING_DIRECTORY "${_semb_te222_test_dir}/.."
  )
endfunction()
if(DEFINED SEMB_LIBRARY_SOURCES)
  cmake_language(DEFER DIRECTORY "${CMAKE_SOURCE_DIR}" CALL semb_add_te222_query_ownership_tests)
endif()

# U2 cloud build -- U2-9's seam-observable cells (C60 (c), C60's poison
# must-reject/must-accept, C61 (a)-(f)) and U2-10's C66 (a). Links the test
# seam mirror; red on today's pool (see the executable's header).
function(semb_add_u2_9_workspace_cells_tests)
  if(NOT TARGET superembedder_testseam)
    return()
  endif()
  set(_semb_u2_9_test_dir "${CMAKE_CURRENT_FUNCTION_LIST_DIR}")
  add_executable(u2_9_workspace_cells_test EXCLUDE_FROM_ALL "${_semb_u2_9_test_dir}/u2_9_workspace_cells_test.cpp")
  target_link_libraries(u2_9_workspace_cells_test PRIVATE superembedder_testseam superslm::superslm Threads::Threads)
  target_include_directories(u2_9_workspace_cells_test PRIVATE "${_semb_u2_9_test_dir}")
  add_test(
    NAME u2_9_workspace_cells_check
    COMMAND "${Python3_EXECUTABLE}" "${_semb_u2_9_test_dir}/u2_9_workspace_cells_check.py"
      --build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}"
    WORKING_DIRECTORY "${_semb_u2_9_test_dir}/.."
  )
  set_tests_properties(u2_9_workspace_cells_check PROPERTIES TIMEOUT 2400)
endfunction()
if(DEFINED SEMB_LIBRARY_SOURCES)
  cmake_language(DEFER DIRECTORY "${CMAKE_SOURCE_DIR}" CALL semb_add_u2_9_workspace_cells_tests)
endif()

# U2 cloud build -- U2-10's C64, the class sweep: links the SHIPPED static
# target with the global operator new replaced (no test seam). The driver
# script runs every table row and driver and prints the pre-build reading.
add_executable(u2_10_c64_class_sweep_test EXCLUDE_FROM_ALL u2_10_c64_class_sweep_test.cpp)
target_link_libraries(u2_10_c64_class_sweep_test PRIVATE superembedder superslm::superslm Threads::Threads)
target_include_directories(u2_10_c64_class_sweep_test PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
add_test(
	NAME u2_10_c64_class_sweep_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/u2_10_c64_class_sweep_check.py"
		--build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
set_tests_properties(u2_10_c64_class_sweep_check PROPERTIES TIMEOUT 3600)

# U2 cloud build -- U2-10's C65 commissioning constructions (must-accept,
# must-reject SEMB_C_LINKAGE_UNLISTED, vitality SEMB_C_LINKAGE_STALE) over the
# shipped archive, on ELF. Red until the census tool (Builds item 5) exists.
if(NOT WIN32)
	add_test(
		NAME u2_10_c65_census_commissioning_check
		COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/u2_10_c65_census_commissioning_check.py"
			--build-dir "${CMAKE_BINARY_DIR}" --archive "$<TARGET_FILE:superembedder>"
		WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
	)
endif()

# U2 cloud build -- U2-10's C66 (b), the RLIMIT_AS sweep (the GCC leg; the
# Job-object leg is MSVC's). Links the SHIPPED static target, no seam.
if(NOT WIN32)
	add_executable(u2_10_c66b_rlimit_sweep_test EXCLUDE_FROM_ALL u2_10_c66b_rlimit_sweep_test.cpp)
	target_link_libraries(u2_10_c66b_rlimit_sweep_test PRIVATE superembedder superslm::superslm Threads::Threads)
	add_test(
		NAME u2_10_c66b_rlimit_sweep_check
		COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/u2_10_c66b_rlimit_sweep_check.py"
			--build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}"
		WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
	)
endif()

# U2 cloud build -- U2-10's C63, the adversary's keeper: real model and
# tokenizer (SEMB_C12B_MODEL, SEMB_U1_TOKENIZER) and the adversary's two texts
# (mid.txt, 603 B / 133 positions; short.txt). Any of them unset -> the cell
# reports MISSING PREREQUISITE and passes; set, it carries real_artifact.
set(SEMB_C63_MID_TEXT "" CACHE FILEPATH "C63: the adversary's mid.txt (603 B, 133 positions)")
set(SEMB_C63_SHORT_TEXT "" CACHE FILEPATH "C63: the adversary's short.txt")
add_executable(u2_10_c63_keeper_test u2_10_c63_keeper_test.cpp)
target_link_libraries(u2_10_c63_keeper_test PRIVATE superembedder superslm::superslm Threads::Threads)
set(_semb_c63_args "")
if(NOT SEMB_C12B_MODEL STREQUAL "" AND NOT SEMB_U1_TOKENIZER STREQUAL "" AND NOT SEMB_C63_MID_TEXT STREQUAL ""
   AND NOT SEMB_C63_SHORT_TEXT STREQUAL "")
	set(_semb_c63_args --model "${SEMB_C12B_MODEL}" --tokenizer "${SEMB_U1_TOKENIZER}"
		--mid "${SEMB_C63_MID_TEXT}" --short "${SEMB_C63_SHORT_TEXT}" --scratch "${CMAKE_BINARY_DIR}")
endif()
add_test(NAME u2_10_c63_keeper COMMAND u2_10_c63_keeper_test ${_semb_c63_args})
if(_semb_c63_args)
	set_tests_properties(u2_10_c63_keeper PROPERTIES LABELS "real_artifact")
endif()

# U2 cloud build -- U2-0 item 1's pin-carrier cell (the tokenizer manifest's
# converter fields and the README's pin word equal the lock; must-rejects
# mutation-proven in the cell) and the interpreter gate's red (a scratch
# configure with an interpreter older than the converter's Unicode 15.1.0).
add_test(
	NAME u2_0_pin_carrier_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/u2_0_pin_carrier_check.py"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
add_test(
	NAME u2_0_python_gate_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/u2_0_python_gate_check.py"
		--build-dir "${CMAKE_BINARY_DIR}" --prefix-path "${CMAKE_PREFIX_PATH}"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# U2 cloud build -- U2-1's C56, the Linux shared library's proof: install,
# export set, NEEDED, and the .so against the static route (synthetic pair
# here; the real leg with SEMB_C12B_MODEL and SEMB_U1_TOKENIZER set).
if(NOT WIN32 AND NOT APPLE)
	set(_semb_c56_args --build-dir "${CMAKE_BINARY_DIR}" --archive "$<TARGET_FILE:superembedder>"
		--engine-lib "$<TARGET_FILE:superslm::superslm>")
	if(NOT SEMB_C12B_MODEL STREQUAL "" AND NOT SEMB_U1_TOKENIZER STREQUAL "")
		list(APPEND _semb_c56_args --model "${SEMB_C12B_MODEL}" --tokenizer "${SEMB_U1_TOKENIZER}")
	endif()
	add_test(
		NAME u2_1_c56_so_check
		COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/u2_1_c56_so_check.py" ${_semb_c56_args}
		WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
	)
	if(NOT SEMB_C12B_MODEL STREQUAL "" AND NOT SEMB_U1_TOKENIZER STREQUAL "")
		set_tests_properties(u2_1_c56_so_check PROPERTIES LABELS "real_artifact")
	endif()
endif()

# U2 cloud build -- U2-5's C16 (no assert( in src/ or include/) and C19 (the
# 1.0 reader's pins: an unknown manifest member accepted, with its
# unknown-key-rejecting mutant built in the cell; schemaVersion 2 refused).
add_test(
	NAME u2_5_c16_no_assert_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/u2_5_c16_no_assert_check.py"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
if(NOT WIN32)
	add_test(
		NAME u2_5_c19_check
		COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/u2_5_c19_check.py"
			--build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}"
			--archive "$<TARGET_FILE:superembedder>" --engine-lib "$<TARGET_FILE:superslm::superslm>"
		WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
	)
endif()

# U2 cloud build -- U2-7's C52 (d) (the in-call rewrite, through a test-seam
# park point in the memory open) and C55's general oracle (independent
# ref_encode counts). Links the test seam mirror; link-red until U2-7 items
# 1, 2, 6 and the seam land.
function(semb_add_u2_7_c52d_c55_tests)
  if(NOT TARGET superembedder_testseam)
    return()
  endif()
  set(_semb_u2_7_dir "${CMAKE_CURRENT_FUNCTION_LIST_DIR}")
  add_executable(u2_7_c52d_c55_test EXCLUDE_FROM_ALL "${_semb_u2_7_dir}/u2_7_c52d_c55_test.cpp")
  target_link_libraries(u2_7_c52d_c55_test PRIVATE superembedder_testseam superslm::superslm Threads::Threads)
  target_include_directories(u2_7_c52d_c55_test PRIVATE "${_semb_u2_7_dir}")
  add_test(
    NAME u2_7_c52d_c55_check
    COMMAND "${Python3_EXECUTABLE}" "${_semb_u2_7_dir}/u2_7_c52d_c55_check.py"
      --build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}"
    WORKING_DIRECTORY "${_semb_u2_7_dir}/.."
  )
endfunction()
if(DEFINED SEMB_LIBRARY_SOURCES)
  cmake_language(DEFER DIRECTORY "${CMAKE_SOURCE_DIR}" CALL semb_add_u2_7_c52d_c55_tests)
endif()

add_executable(te222_c17_probe EXCLUDE_FROM_ALL te222_c17_probe.cpp)
target_link_libraries(te222_c17_probe PRIVATE superembedder superslm::superslm)
target_include_directories(te222_c17_probe PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")

# Cell 4 -- C41 part 4's scope widening (semb_query_encode's own TU). Reads
# the query TU's compiled object once it exists; RED-UNIMPLEMENTED today
# (see the script's own header comment for why and for the routed finding
# on the candidate TU name).
add_test(
	NAME te194_c41_query_scope_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te194_c41_query_scope_check.py"
		--build-dir "${CMAKE_BINARY_DIR}"
		--objdump "${SEMB_TEST_OBJDUMP}"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# Cell 5 -- C17's sixth leg / W-Q's own composition-drift construction.
# QUARANTINED instrument (TE-194-c17-wq-sixth-leg); always red-unimplemented
# today (see the script's own header comment).
add_test(
	NAME te194_c17_sixth_leg_construction
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te194_c17_sixth_leg_construction.py"
		--build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# ---------------------------------------------------------------------------
# TE-230 (U1 slice 6): the executable `semb` CLI, C24, C18, and C5.  The
# Python driver owns command-line/process assertions; its separately-built
# probe opens the resulting bank through the frozen C ABI and independently
# produces the library query bytes that CLI --hex must equal.
# ---------------------------------------------------------------------------
add_executable(te230_semb_cli_probe EXCLUDE_FROM_ALL te230_semb_cli_probe.cpp)
target_link_libraries(te230_semb_cli_probe PRIVATE superembedder superslm::superslm)
target_include_directories(te230_semb_cli_probe PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")

add_test(
	NAME te230_semb_cli_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te230_semb_cli_check.py"
		--build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
add_test(
	NAME te230_c4_zero_gain_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te230_c4_zero_gain_check.py"
		--build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
# C5 is purely real (no mechanism leg), so it is registered only when the
# pair is configured, the same form as te163_c34_manifest_honesty_check: an
# unconfigured tree does not register it, so ctest cannot report it Passed
# having run nothing. The driver's MISSING PREREQUISITE return stays as the
# guard for direct invocation.
if(NOT SEMB_C12B_MODEL STREQUAL "" AND NOT SEMB_U1_TOKENIZER STREQUAL "")
	add_test(
		NAME te230_c5_real_workload
		COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te230_c5_real_workload.py"
			--build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}"
			--model "${SEMB_C12B_MODEL}" --tokenizer "${SEMB_U1_TOKENIZER}"
		WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
	)
	set_tests_properties(te230_c5_real_workload PROPERTIES LABELS "real_artifact" TIMEOUT 1800)
endif()

# ---------------------------------------------------------------------------
# TE-237 (U1 slice 6 fix-round pins, Claude/Bach/briefs/te237-slice6-s3-pins.md):
# the S-3 cross-handle construction (TE-236 D-SLM6642's named construction --
# park one materializing semb_bank_open and prove close/acquire on a distinct
# live bank can complete). Links `superembedder_testseam` (the hook the cell
# parks at is the declared internal seam tests/support/semb_bank_open_seam.h
# documents; its full contract is in
# tests/te237_bank_cross_handle_test.cpp's header comment), so the
# registration is DEFERRED exactly like te194/te222's own testseam targets --
# deferred calls run in scheduling order and semb_add_workspace_tests() is
# scheduled earlier in this file, so superembedder_testseam exists when this
# function body runs. EXCLUDE_FROM_ALL: the semb_bank_test_seam_* surface is
# undefined at this branch's own base fe0c0e0, so the driver builds it on
# demand and reports the unresolved symbol(s) by name as RED-UNIMPLEMENTED,
# the identical red-first shape tests/te194_query_workspace_check.py uses.
# ---------------------------------------------------------------------------
function(semb_add_te237_bank_cross_handle_tests)
  if(NOT TARGET superembedder_testseam)
    return()  # semb_add_workspace_tests() itself only runs when SEMB_LIBRARY_SOURCES is defined
  endif()
  set(_semb_te237_test_dir "${CMAKE_CURRENT_FUNCTION_LIST_DIR}")
  add_executable(te237_bank_cross_handle_test EXCLUDE_FROM_ALL
                 "${_semb_te237_test_dir}/te237_bank_cross_handle_test.cpp")
  target_link_libraries(te237_bank_cross_handle_test PRIVATE superembedder_testseam superslm::superslm Threads::Threads)
  target_include_directories(te237_bank_cross_handle_test PRIVATE "${_semb_te237_test_dir}")
  set_target_properties(te237_bank_cross_handle_test PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/tests")
  add_test(
    NAME te237_bank_cross_handle_check
    COMMAND "${Python3_EXECUTABLE}" "${_semb_te237_test_dir}/te237_bank_cross_handle_check.py"
      --build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}"
    WORKING_DIRECTORY "${_semb_te237_test_dir}/.."
  )
endfunction()
if(DEFINED SEMB_LIBRARY_SOURCES)
  cmake_language(DEFER DIRECTORY "${CMAKE_SOURCE_DIR}" CALL semb_add_te237_bank_cross_handle_tests)
endif()

# ---------------------------------------------------------------------------
# TE-264 (U1 Slice 7 red suite, `Claude/Plans/te140-u1-remainder-sequencing.md`
# sec 4.7 steps 1-6). Appended as one contiguous block.
# ---------------------------------------------------------------------------

# Step 2 (D-SLM7197, D-SLM7205): semb_encode composes through ComposeBatch as
# a batch of one. The structural half reads semb_encode's body.
add_test(
	NAME te264_raw_entry_composition_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te264_raw_entry_composition_check.py"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# Step 2's committed raw-equals-batch cell (D-SLM7204): over the 239 corpus
# documents and the 16 W-B documents, semb_encode's vector equals the
# semb_encode_batch row for the same text, byte for byte. Green before and
# after step 2; registered only when the real artifact is configured.
add_executable(te264_raw_equals_batch_test te264_raw_equals_batch_test.cpp)
target_link_libraries(te264_raw_equals_batch_test PRIVATE superembedder superslm::superslm)
target_include_directories(te264_raw_equals_batch_test PRIVATE
	"${CMAKE_CURRENT_SOURCE_DIR}" "${CMAKE_SOURCE_DIR}/src/superembedder")
if(NOT SEMB_C12B_MODEL STREQUAL "" AND NOT SEMB_U1_TOKENIZER STREQUAL "")
	add_test(
		NAME te264_raw_equals_batch_real_artifact
		COMMAND te264_raw_equals_batch_test
			--model "${SEMB_C12B_MODEL}" --tokenizer "${SEMB_U1_TOKENIZER}"
			--corpus "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/c12b/corpus-239.jsonl"
			--corpus-manifest "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/c12b/corpus-239.manifest.json"
		WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
	)
	set_tests_properties(te264_raw_equals_batch_real_artifact PROPERTIES LABELS "real_artifact" TIMEOUT 3600)
endif()

# Steps 3, 4 (a), 4 (e) and 5: one probe bakes on one encoder handle and the
# driver compares the manifest's clear components and the two ABI fingerprint
# values with oracles typed from the plan and read from repository files.
add_executable(te264_fingerprint_probe te264_fingerprint_probe.cpp)
target_link_libraries(te264_fingerprint_probe PRIVATE superembedder superslm::superslm)
foreach(_semb_te264_cell IN ITEMS template epoch epoch-edit untagged)
	string(REPLACE "-" "_" _semb_te264_name "${_semb_te264_cell}")
	add_test(
		NAME te264_fingerprint_${_semb_te264_name}_check
		COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te264_fingerprint_final_check.py"
			--build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}" --cell ${_semb_te264_cell}
		WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
	)
endforeach()
# epoch-edit edits the committed docs/certified-builds.json in place for the
# length of one probe run and restores it; nothing else may read it meanwhile.
set_tests_properties(te264_fingerprint_epoch_edit_check PROPERTIES RUN_SERIAL TRUE)

# Step 4 (d) (D-SLM7206): configure refuses a missing and an unparseable
# docs/certified-builds.json by name; the unchanged document configures.
add_test(
	NAME te264_c42_configure_legs_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te264_c42_configure_legs_check.py"
		--repo-root "${CMAKE_SOURCE_DIR}"
		--engine-prefix "${SEMB_ENGINE_PREFIX}"
		--cmake-executable "${CMAKE_COMMAND}"
		--generator "${CMAKE_GENERATOR}"
		--ninja-executable "${CMAKE_MAKE_PROGRAM}"
		--python-executable "${Python3_EXECUTABLE}"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# Step 4 (c) (D-SLM7206): the C42 (a)-(c) release checker refuses its three
# constructions on a synthetic four-member package, each on its own clause,
# accepts the unedited package, and accepts the committed interim package.
add_test(
	NAME te264_c42_checker_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te264_c42_checker_check.py"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# ---------------------------------------------------------------------------
# TE-331 (U2-1/U2-3/U2-7 red suite, `Claude/Plans/te267-u2-release-plan.md`).
# Links against symbols undefined at this branch's own base `fca421b`
# (semb_encoder_open_memory, semb_encode_query, semb_interim_query_token_count,
# semb_interim_certification_verdict), so it is EXCLUDE_FROM_ALL;
# tests/te331_u2_surface_link_check.py builds it on demand and reports the
# unresolved symbol(s) by name, the te163/te194 red-first shape.
# ---------------------------------------------------------------------------
add_executable(te331_u2_surface_link_test EXCLUDE_FROM_ALL te331_u2_surface_link_test.cpp)
target_link_libraries(te331_u2_surface_link_test PRIVATE superembedder superslm::superslm)
target_include_directories(te331_u2_surface_link_test PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")

set(_semb_te331_surface_args --build-dir "${CMAKE_BINARY_DIR}" --cmake-executable "${CMAKE_COMMAND}")
if(NOT SEMB_C12B_MODEL STREQUAL "")
	list(APPEND _semb_te331_surface_args --model "${SEMB_C12B_MODEL}")
endif()
if(NOT SEMB_U1_TOKENIZER STREQUAL "")
	list(APPEND _semb_te331_surface_args --tokenizer "${SEMB_U1_TOKENIZER}")
endif()
add_test(
	NAME te331_u2_surface_link_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te331_u2_surface_link_check.py" ${_semb_te331_surface_args}
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# Item 14/M18: sslm_build_identity + SEMB_ENGINE_LINK_MISMATCH. Links against
# a symbol the PINNED ENGINE (SuperSLM 1.5.0) does not define at all, so it
# is EXCLUDE_FROM_ALL; tests/te331_u2_engine_identity_check.py builds it on
# demand and reports the unresolved symbol by name.
add_executable(te331_u2_engine_identity_test EXCLUDE_FROM_ALL te331_u2_engine_identity_test.cpp)
target_link_libraries(te331_u2_engine_identity_test PRIVATE superembedder superslm::superslm)
target_include_directories(te331_u2_engine_identity_test PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")

add_test(
	NAME te331_u2_engine_identity_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te331_u2_engine_identity_check.py" ${_semb_te331_surface_args}
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)

# U2-1 (F4): the out-of-tree consumer, and R20/M19's post-build census, and
# U2-3's C42 extended clauses (b'/e/f/g/h) (R9/R10's tool cells moved to
# 1.x, D-SLM7711), and U2-7 item 3/C54's binary-mode CLI line reading, and U2-3 item
# 5's --force-tier pin-tool option: standalone Python drivers, no CMake
# target of their own (they build/configure their own scratch trees or
# drive the CLI/tools directly).
add_test(
	NAME te331_u2_consumer_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te331_u2_consumer_check.py"
		--cmake-executable "${CMAKE_COMMAND}" --product-build "${CMAKE_BINARY_DIR}"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
add_test(
	NAME te331_u2_c42_clauses_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te331_u2_c42_clauses_check.py"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
add_test(
	NAME te331_u2_export_surface_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te331_u2_export_surface_check.py"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
add_test(
	NAME te331_u2_misc_absence_check
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/te331_u2_misc_absence_check.py"
	WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
