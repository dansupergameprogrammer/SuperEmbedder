# SuperEmbedder — top-level CMakeLists.txt.
#
# TE-61 (Claude/Plans/SuperEmbedder_Plan.md's U0, slice A) built the
# scaffold, the engine pin, the two configure guards, the build-flag
# assertion, and CI. TE-63 (U0 slice B) adds the arithmetic: the interim
# engine-adapter TU (sec 4.3), PS-1's pooling epilogue and W-A's primitive
# driver (sec 3.2, sec 4.4), the seam serialisation (sec 4.4b), and the
# witness executable (sec 4.4's structural law).
cmake_minimum_required(VERSION 3.21)
project(superembedder VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

list(APPEND CMAKE_MODULE_PATH "${CMAKE_SOURCE_DIR}/cmake")

include(EngineGuards)   # find_package(superslm), the two version guards, provenance (C33)
include(BuildFlags)     # the precise-FP flag (directory-wide) + semb_assert_precise_fp() (C14)
include(SourceProvenance)  # semb_source_sha (C34)

# The pinned engine's tag/commit/tree baked in for the CLI to report and for
# any future unit that wants a compile-time handle on the pin.
configure_file(
	"${CMAKE_SOURCE_DIR}/cmake/templates/semb_engine_pin.h.in"
	"${CMAKE_BINARY_DIR}/generated/semb_engine_pin.h"
	@ONLY
)

# ---------------------------------------------------------------------------
# The superembedder library. TE-63 adds the arithmetic: PS-1's pooling
# epilogue + W-A's primitive driver (ps1_pool.cpp), the seam serialisation
# (seam_serialize.cpp), and the ONE interim-adapter TU that names the
# engine's forward entry points (engine_adapter_interim.cpp — C39's
# singleton scan enforces there is only one).
# ---------------------------------------------------------------------------
set(SEMB_LIBRARY_SOURCES
	src/version.cpp
	src/superembedder/ps1_pool.cpp
	src/superembedder/seam_serialize.cpp
	src/superembedder/wa_digest.cpp
	src/superembedder/engine_adapter_interim.cpp
)

semb_compute_source_provenance(superembedder
	SOURCES ${SEMB_LIBRARY_SOURCES}
	INCLUDE_DIRS "${CMAKE_SOURCE_DIR}/include" "${SEMB_ENGINE_PREFIX}/include"
	OUT_HEADER "${CMAKE_BINARY_DIR}/generated/semb_provenance.h"
)

add_library(superembedder STATIC ${SEMB_LIBRARY_SOURCES})
target_include_directories(superembedder
	PUBLIC
		$<BUILD_INTERFACE:${CMAKE_SOURCE_DIR}/include>
		$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
	PRIVATE
		"${CMAKE_BINARY_DIR}/generated"
)
target_link_libraries(superembedder PRIVATE superslm::superslm)
semb_verify_source_provenance(superembedder SIDECAR "${SEMB_SOURCE_PROVENANCE_SIDECAR}")

# engine_path_sha (sec 4.3: "the build selects one adapter translation unit
# in one branch of one variable... its bytes are engine_path_sha, manifest
# provenance since two adapters computing the same vectors share an
# epoch") — a content digest of the one selected adapter TU's own bytes,
# computed at configure (a byte digest of a produced/committed file, never
# a path or a CMake property — StandardsDocument.md sec 3.3's own
# producer-identity rule, applied here to the one variable this project
# has today: SEMB_ENGINE_ADAPTER_TU always resolves to the interim TU
# until U3 adds a second branch).
set(SEMB_ENGINE_ADAPTER_TU "${CMAKE_SOURCE_DIR}/src/superembedder/engine_adapter_interim.cpp")
file(SHA256 "${SEMB_ENGINE_ADAPTER_TU}" SEMB_ENGINE_PATH_SHA)
message(STATUS "engine_path_sha (${SEMB_ENGINE_ADAPTER_TU}): ${SEMB_ENGINE_PATH_SHA}")

# ---------------------------------------------------------------------------
# The semb CLI. A stub in this slice: it prints its version and the pinned
# engine's tag. Its verbs (bake/query/verify) are U1's.
# ---------------------------------------------------------------------------
add_executable(semb src/main.cpp)
target_link_libraries(semb PRIVATE superembedder)
target_include_directories(semb PRIVATE "${CMAKE_BINARY_DIR}/generated")

# ---------------------------------------------------------------------------
# The witness executable (sec 4.4b's structural law, clauses 1/2/4): a
# target of THIS build, linking the real superembedder library (and,
# transitively, the real installed superslm library) — never a prebuilt
# binary and never a second configure. Its own translation unit
# (src/witness/witness_main.cpp) is a loop and a serialiser, no
# arithmetic — clause 3's own reason W-A's driver and the interim adapter
# live in the library, not here.
# ---------------------------------------------------------------------------
add_executable(semb_witness src/witness/witness_main.cpp)
# Links the engine directly too (not only transitively through
# superembedder, which links it PRIVATE) — this TU calls
# superslm::Sha256/ToHex directly for the seam digest, sec 4.4b's own "the
# same routine model_sha uses."
target_link_libraries(semb_witness PRIVATE superembedder superslm::superslm)

# Both product targets above (and any future target this file declares) inherit the
# precise-FP flag from BuildFlags.cmake's directory-wide add_compile_options()
# automatically — there is no per-target call left to make. Assert the whole
# set now, once, after nothing else can add or remove a target.
semb_assert_precise_fp()

# ---------------------------------------------------------------------------
# Tests: the negative-configure matrix (C33's provenance legs, C34's
# source-provenance legs, and C14's build-configuration legs) and the
# positive-configure smoke.
# ---------------------------------------------------------------------------
enable_testing()

# TE-62's red suite (U0 slice B): C1, C3, C14, W-A's population, W-B, C39,
# C40, C31/C36/C38's structural matrix. tests/CMakeLists.txt is
# add_subdirectory-able because the superembedder target and
# superslm::superslm already exist in this scope by this point.
add_subdirectory(tests)

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
