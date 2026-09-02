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

# engine_path_sha (sec 4.3: "the build selects one adapter translation unit
# in one branch of one variable... its bytes are engine_path_sha, manifest
# provenance since two adapters computing the same vectors share an
# epoch") — a content digest of the one selected adapter TU's own bytes,
# computed at configure (a byte digest of a produced/committed file, never
# a path or a CMake property — StandardsDocument.md sec 3.3's own
# producer-identity rule, applied here to the one variable this project
# has today: SEMB_ENGINE_ADAPTER_TU always resolves to the interim TU
# until U3 adds a second branch). Computed BEFORE the configure_file()
# call below (TE-79 F-11, TE-76 review) so it reaches the generated pin
# header like the other three pin fields, rather than only a
# message(STATUS) line no build artifact carries.
set(SEMB_ENGINE_ADAPTER_TU "${CMAKE_SOURCE_DIR}/src/superembedder/engine_adapter_interim.cpp")
file(SHA256 "${SEMB_ENGINE_ADAPTER_TU}" SEMB_ENGINE_PATH_SHA)
message(STATUS "engine_path_sha (${SEMB_ENGINE_ADAPTER_TU}): ${SEMB_ENGINE_PATH_SHA}")

# The pinned engine's tag/commit/tree, and engine_path_sha, baked in for
# the CLI to report and for any future unit that wants a compile-time
# handle on the pin.
configure_file(
	"${CMAKE_SOURCE_DIR}/cmake/templates/semb_engine_pin.h.in"
	"${CMAKE_BINARY_DIR}/generated/semb_engine_pin.h"
	@ONLY
)

# sec 8 C31(ii) (SEMB_WITNESS_DETACHED_LINK, sec 4.4d item 2): a per-configure
# random 128-bit hex token, baked into a generated header the same way the
# four pin fields above are -- compiled into both the library and the
# witness executable's own TU, so the two copies are identical if and only
# if both were configured together. string(RANDOM ...) with no RANDOM_SEED
# given reseeds from the current time on every configure (CMake's own
# documented behavior), which is what makes this token PER-CONFIGURE.
string(RANDOM LENGTH 32 ALPHABET "0123456789abcdef" SEMB_WITNESS_BUILD_GENERATION_TOKEN)
configure_file(
	"${CMAKE_SOURCE_DIR}/cmake/templates/semb_witness_build_generation.h.in"
	"${CMAKE_BINARY_DIR}/generated/semb_witness_build_generation.h"
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
	src/superembedder/witness_build_generation.cpp
	src/superembedder/engine_adapter_interim.cpp
)

semb_compute_source_provenance(superembedder
	SOURCES ${SEMB_LIBRARY_SOURCES}
	# "${CMAKE_BINARY_DIR}/generated" added for
	# src/superembedder/witness_build_generation.cpp's own
	# #include "semb_witness_build_generation.h" (sec 8 C31(ii)) -- the
	# real compiler invocation this macro drives needs the identical
	# include path the actual target build uses to resolve it.
	INCLUDE_DIRS "${CMAKE_SOURCE_DIR}/include" "${SEMB_ENGINE_PREFIX}/include" "${CMAKE_BINARY_DIR}/generated"
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

# sec 8 C31(i) (SEMB_WITNESS_FOREIGN_BUILD, sec 4.4d item 1): the same
# source-provenance digest/re-verify pair already proven for the
# `superembedder` library target (C34), applied to `semb_witness` as a
# second, independent target -- a rebuild whose compiled closure disagrees
# with the configure-time digest fails the BUILD, by name, before any
# executable exists to misbehave.
semb_compute_source_provenance(semb_witness
	SOURCES src/witness/witness_main.cpp
	# "${CMAKE_BINARY_DIR}/generated" added for witness_main.cpp's own
	# #include "semb_witness_build_generation.h" (sec 8 C31(ii)).
	INCLUDE_DIRS "${CMAKE_SOURCE_DIR}/include" "${SEMB_ENGINE_PREFIX}/include" "${CMAKE_BINARY_DIR}/generated"
	OUT_HEADER "${CMAKE_BINARY_DIR}/generated/semb_witness_provenance.h"
	# A distinct sidecar name -- `superembedder`'s own call above uses the
	# default, unparameterized name; without an explicit override here
	# this call would silently overwrite THAT sidecar (both default to
	# the same file otherwise), corrupting superembedder's own POST_BUILD
	# re-verification (cmake/SourceProvenance.cmake's own SIDECAR_NAME
	# comment).
	SIDECAR_NAME "semb_witness_source_provenance.json"
)
set(SEMB_WITNESS_SOURCE_PROVENANCE_SIDECAR "${SEMB_SOURCE_PROVENANCE_SIDECAR}")

# Links the engine directly too (not only transitively through
# superembedder, which links it PRIVATE) — this TU calls
# superslm::Sha256/ToHex directly for the seam digest, sec 4.4b's own "the
# same routine model_sha uses."
target_link_libraries(semb_witness PRIVATE superembedder superslm::superslm)
# sec 8 C31(ii): witness_main.cpp includes the generated build-generation
# token header directly (semb_witness_build_generation.h) -- not exposed
# through superembedder's own PUBLIC include dirs, since that header lives
# in the same PRIVATE generated dir the library itself uses.
target_include_directories(semb_witness PRIVATE "${CMAKE_BINARY_DIR}/generated")
semb_verify_source_provenance(semb_witness SIDECAR "${SEMB_WITNESS_SOURCE_PROVENANCE_SIDECAR}")

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

# TE-79 F-4 (Significant, TE-76 review): semb_assert_precise_fp() moved
# HERE, after every add_subdirectory() this file calls -- it used to run
# BEFORE add_subdirectory(tests), so its own recursive BUILDSYSTEM_TARGETS
# walk (cmake/BuildFlags.cmake) saw an EMPTY subdirectory list and checked
# only [superembedder;semb;semb_witness], none of the nine test targets
# (executed, confirmed from the project's own recorded configure output:
# the printed population never named a test TU). Both product targets
# above (and any future target this file declares) inherit the precise-FP
# flag from BuildFlags.cmake's directory-wide add_compile_options()
# automatically — there is no per-target call left to make. Assert the
# whole set now, once, after nothing else can add or remove a target --
# which is only true once every add_subdirectory() call has already run.
semb_assert_precise_fp()

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
