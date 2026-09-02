# SuperEmbedder — top-level CMakeLists.txt.
#
# This is TE-61 (Claude/Plans/SuperEmbedder_Plan.md's U0, slice A): the
# scaffold, the engine pin, the two configure guards, the build-flag
# assertion, and CI. It carries no arithmetic — the encoder itself (the
# interim TU, the pooling epilogue, the witness drivers) is TE-63.
cmake_minimum_required(VERSION 3.21)
project(superembedder VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

list(APPEND CMAKE_MODULE_PATH "${CMAKE_SOURCE_DIR}/cmake")

include(EngineGuards)   # find_package(superslm), the two version guards, provenance (C33)
include(BuildFlags)     # semb_require_precise_fp()/semb_assert_precise_fp() (C14)
include(SourceProvenance)  # semb_source_sha (C34)

# The pinned engine's tag/commit/tree baked in for the CLI to report and for
# any future unit that wants a compile-time handle on the pin.
configure_file(
	"${CMAKE_SOURCE_DIR}/cmake/templates/semb_engine_pin.h.in"
	"${CMAKE_BINARY_DIR}/generated/semb_engine_pin.h"
	@ONLY
)

# ---------------------------------------------------------------------------
# The superembedder library. This slice's only source is the version
# accessor; the encoder itself is TE-63's.
# ---------------------------------------------------------------------------
semb_compute_source_provenance(superembedder
	SOURCES src/version.cpp
	HEADER_ROOTS include/superembedder
	OUT_HEADER "${CMAKE_BINARY_DIR}/generated/semb_provenance.h"
)

add_library(superembedder STATIC src/version.cpp)
target_include_directories(superembedder
	PUBLIC
		$<BUILD_INTERFACE:${CMAKE_SOURCE_DIR}/include>
		$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
	PRIVATE
		"${CMAKE_BINARY_DIR}/generated"
)
semb_require_precise_fp(superembedder)
semb_verify_source_provenance(superembedder SIDECAR "${SEMB_SOURCE_PROVENANCE_SIDECAR}")

# ---------------------------------------------------------------------------
# The semb CLI. A stub in this slice: it prints its version and the pinned
# engine's tag. Its verbs (bake/query/verify) are U1's.
# ---------------------------------------------------------------------------
add_executable(semb src/main.cpp)
target_link_libraries(semb PRIVATE superembedder)
target_include_directories(semb PRIVATE "${CMAKE_BINARY_DIR}/generated")
semb_require_precise_fp(semb)

# All targets are registered above; assert the whole set now, once, after
# nothing else can add or remove a target.
semb_assert_precise_fp()

# ---------------------------------------------------------------------------
# Tests: the negative-configure matrix (C33's seven legs, C34's five legs,
# C14's flag-strip proof) and the positive-configure smoke.
# ---------------------------------------------------------------------------
enable_testing()
add_test(
	NAME provenance_and_flag_matrix
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_SOURCE_DIR}/tools/ci/run_configure_matrix.py"
		--repo-root "${CMAKE_SOURCE_DIR}"
		--engine-prefix "${SEMB_ENGINE_PREFIX}"
		--cmake-executable "${CMAKE_COMMAND}"
		--generator "${CMAKE_GENERATOR}"
		--ninja-executable "${CMAKE_MAKE_PROGRAM}"
		--python-executable "${Python3_EXECUTABLE}"
)
