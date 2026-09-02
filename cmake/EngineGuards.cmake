# cmake/EngineGuards.cmake — consumes the pinned SuperSLM engine install
# (tools/pin-superslm) and enforces the guards Claude/Plans/SuperEmbedder_Plan.md
# §4.1 specifies: two version guards (floor, exact pin) and the provenance
# checks that make `superslm.lock` an independently-verifiable claim rather
# than a string the build merely trusts.
#
# DESIGN NOTE ON find_package's VERSION ARGUMENT (build log: te61-u0a, read
# before editing this file). §4.1's prose calls for
# `find_package(superslm 1.3 CONFIG REQUIRED)`, relying on
# superslmConfigVersion.cmake's SameMajorVersion mode to accept 1.x >= 1.3 —
# but passing "1.3" to find_package means CMake's OWN version-compatibility
# machinery silently refuses (with CMake's generic "no suitable version
# found" message, not a named SEMB_* error) any installed engine below the
# floor, which would make the floor guard below UNREACHABLE for the exact
# defect it exists to name. This file therefore calls find_package WITHOUT a
# version constraint — accepting whatever superslm_VERSION the found package
# reports, whatever it is — and enforces BOTH the floor and the exact pin
# itself, by name, below. This preserves the intended protection in full (no
# real installed version can slip past either guard) while making both
# independently testable via a real `cmake -S ... -B ...` invocation, which
# is what C33 requires.

# ---------------------------------------------------------------------------
# 1. Parse superslm.lock. `tag=` is the only field a person edits; `commit=`
#    and `tree=` are written by tools/pin-superslm and read back here.
# ---------------------------------------------------------------------------
if(NOT DEFINED SEMB_ENGINE_LOCK_FILE)
	set(SEMB_ENGINE_LOCK_FILE "${CMAKE_SOURCE_DIR}/superslm.lock")
endif()

if(NOT EXISTS "${SEMB_ENGINE_LOCK_FILE}")
	message(FATAL_ERROR "SEMB_ENGINE_LOCK_MISSING: ${SEMB_ENGINE_LOCK_FILE} does not exist. "
		"Run tools/pin-superslm/pin_superslm.py first.")
endif()

file(STRINGS "${SEMB_ENGINE_LOCK_FILE}" _semb_lock_lines)
set(SEMB_LOCK_TAG "")
set(SEMB_LOCK_COMMIT "")
set(SEMB_LOCK_TREE "")
foreach(_line IN LISTS _semb_lock_lines)
	string(STRIP "${_line}" _line)
	if(_line MATCHES "^tag=(.*)$")
		set(SEMB_LOCK_TAG "${CMAKE_MATCH_1}")
	elseif(_line MATCHES "^commit=(.*)$")
		set(SEMB_LOCK_COMMIT "${CMAKE_MATCH_1}")
	elseif(_line MATCHES "^tree=(.*)$")
		set(SEMB_LOCK_TREE "${CMAKE_MATCH_1}")
	endif()
endforeach()

if(SEMB_LOCK_TAG STREQUAL "")
	message(FATAL_ERROR "SEMB_ENGINE_LOCK_MALFORMED: ${SEMB_ENGINE_LOCK_FILE} has no 'tag=' line.")
endif()
if(SEMB_LOCK_COMMIT STREQUAL "" OR SEMB_LOCK_TREE STREQUAL "")
	message(FATAL_ERROR "SEMB_ENGINE_LOCK_MALFORMED: ${SEMB_ENGINE_LOCK_FILE} is missing 'commit=' or "
		"'tree=' — run tools/pin-superslm/pin_superslm.py to populate them before configuring.")
endif()

string(REGEX REPLACE "^v" "" SEMB_LOCK_VERSION "${SEMB_LOCK_TAG}")

# ---------------------------------------------------------------------------
# 2. Locate the engine. CMAKE_PREFIX_PATH (or -Dsuperslm_DIR=...) must already
#    point at the prefix tools/pin-superslm installed to; this file does not
#    invoke the pin tool itself (it is a separate, explicit step — §4.1's own
#    "why not FetchContent" reasoning applies here too: configure should not
#    silently reach onto the network).
# ---------------------------------------------------------------------------
find_package(superslm CONFIG REQUIRED)

# ---------------------------------------------------------------------------
# 3. The two version guards.
# ---------------------------------------------------------------------------
if(superslm_VERSION VERSION_LESS "1.3.0")
	message(FATAL_ERROR "SEMB_ENGINE_BELOW_PIN_FLOOR: found SuperSLM ${superslm_VERSION} at "
		"${superslm_DIR}, below the floor 1.3.0. The FP-free open path (§1.3) is a >= requirement: "
		"below the floor, the unmasked-host trap class is live.")
endif()

if(NOT superslm_VERSION VERSION_EQUAL SEMB_LOCK_VERSION)
	message(FATAL_ERROR "SEMB_ENGINE_PIN_MISMATCH: found SuperSLM ${superslm_VERSION} at "
		"${superslm_DIR}, but ${SEMB_ENGINE_LOCK_FILE} pins ${SEMB_LOCK_VERSION}. Bit-identity needs "
		"an exact pin, not a floor: re-run tools/pin-superslm/pin_superslm.py, or edit the lock's "
		"tag= to match what is installed.")
endif()

# ---------------------------------------------------------------------------
# 4. Provenance. superslm_DIR is <prefix>/lib/cmake/superslm; the provenance
#    manifest tools/pin-superslm wrote sits at <prefix>/share/superslm-provenance/.
# ---------------------------------------------------------------------------
get_filename_component(SEMB_ENGINE_PREFIX "${superslm_DIR}/../../.." ABSOLUTE)
set(SEMB_ENGINE_PROVENANCE_FILE "${SEMB_ENGINE_PREFIX}/share/superslm-provenance/provenance.json")

if(NOT EXISTS "${SEMB_ENGINE_PROVENANCE_FILE}")
	message(FATAL_ERROR "SEMB_ENGINE_PROVENANCE_MISSING: no provenance manifest at "
		"${SEMB_ENGINE_PROVENANCE_FILE}. This install was not produced by "
		"tools/pin-superslm/pin_superslm.py (or its provenance output was deleted); configure cannot "
		"verify what source this engine build came from.")
endif()

file(READ "${SEMB_ENGINE_PROVENANCE_FILE}" _semb_provenance_json)
string(JSON _semb_prov_tag ERROR_VARIABLE _semb_prov_err GET "${_semb_provenance_json}" "tag")
if(_semb_prov_err)
	message(FATAL_ERROR "SEMB_ENGINE_PROVENANCE_MALFORMED: ${SEMB_ENGINE_PROVENANCE_FILE} could not "
		"be parsed as JSON (${_semb_prov_err}).")
endif()
string(JSON _semb_prov_commit GET "${_semb_provenance_json}" "commit")
string(JSON _semb_prov_tree GET "${_semb_provenance_json}" "engine_tree_sha")
string(JSON _semb_prov_clean GET "${_semb_provenance_json}" "clean")

# 4a. Lock/provenance label agreement (leg f) — the lock's tag/commit must be
#     what the tool actually resolved when it built THIS prefix.
if(NOT SEMB_LOCK_TAG STREQUAL _semb_prov_tag OR NOT SEMB_LOCK_COMMIT STREQUAL _semb_prov_commit)
	message(FATAL_ERROR "SEMB_PIN_LABEL_MISMATCH: ${SEMB_ENGINE_LOCK_FILE} names tag=${SEMB_LOCK_TAG} "
		"commit=${SEMB_LOCK_COMMIT}, but the installed engine's own provenance "
		"(${SEMB_ENGINE_PROVENANCE_FILE}) names tag=${_semb_prov_tag} commit=${_semb_prov_commit}. "
		"The lock's labels must match what tools/pin-superslm actually resolved for this install.")
endif()

# 4b. Lock/provenance digest agreement (legs a, c) — checked from BOTH sides:
#     a hand-edited lock digest (leg a) and a hand-edited provenance digest
#     (leg c) are both real, independently constructible negative-configure
#     legs that land on this one comparison.
if(NOT SEMB_LOCK_TREE STREQUAL _semb_prov_tree)
	message(FATAL_ERROR "SEMB_ENGINE_PROVENANCE_MISMATCH: ${SEMB_ENGINE_LOCK_FILE} pins "
		"tree=${SEMB_LOCK_TREE}, but the installed engine's own provenance "
		"(${SEMB_ENGINE_PROVENANCE_FILE}) declares engine_tree_sha=${_semb_prov_tree}. One of the two "
		"was hand-edited, or the lock was not re-derived after the pin last changed.")
endif()

# 4c. clean=false (leg e) — the tool recorded that the clone carried an
#     uncommitted edit to a compile-closure member when this install was
#     built. This is the leg §8/C33 requires be built for real (an install
#     from a dirty clone) rather than constructed by editing a string.
if(NOT _semb_prov_clean)
	string(JSON _semb_prov_dirty_count ERROR_VARIABLE _semb_dirty_err LENGTH "${_semb_provenance_json}" "dirty_paths")
	message(FATAL_ERROR "SEMB_ENGINE_INSTALL_DIVERGED: the installed engine's own provenance records "
		"clean=false — the clone tools/pin-superslm built this install from carried an uncommitted "
		"edit to a file inside the compile+install closure (${_semb_prov_dirty_count} file(s)), so "
		"what got compiled disagrees with what tag ${_semb_prov_tag} says should be there.")
endif()

# ---------------------------------------------------------------------------
# 5. The deep check: recompute engine_tree_sha fresh from whatever is
#    CURRENTLY on disk under the prefix, via tools/pin-superslm/verify_provenance.py,
#    and require it to still agree with the lock. This is "the lock's digest
#    equals the digest recomputed at configure from the prefix's own bytes"
#    (§4.1) — it catches drift the two label/digest-agreement checks above
#    cannot see, because those only compare two DECLARED strings against each
#    other; this one re-reads real bytes.
# ---------------------------------------------------------------------------
find_package(Python3 COMPONENTS Interpreter REQUIRED)
execute_process(
	COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_LIST_DIR}/../tools/pin-superslm/verify_provenance.py" "${SEMB_ENGINE_PREFIX}"
	OUTPUT_VARIABLE _semb_verify_json
	RESULT_VARIABLE _semb_verify_rc
)
if(NOT _semb_verify_rc EQUAL 0)
	message(FATAL_ERROR "SEMB_ENGINE_PROVENANCE_VERIFY_FAILED: verify_provenance.py exited "
		"${_semb_verify_rc}. Output: ${_semb_verify_json}")
endif()
string(JSON _semb_recomputed_tree ERROR_VARIABLE _semb_rt_err GET "${_semb_verify_json}" "recomputed_engine_tree_sha")
if(_semb_rt_err OR _semb_recomputed_tree STREQUAL "" OR _semb_recomputed_tree STREQUAL "NOTFOUND")
	message(FATAL_ERROR "SEMB_ENGINE_INSTALL_DIVERGED: could not recompute engine_tree_sha from the "
		"prefix's current bytes (verify_provenance.py output: ${_semb_verify_json}). A covered file is "
		"missing from disk under ${SEMB_ENGINE_PREFIX}.")
endif()
if(NOT _semb_recomputed_tree STREQUAL SEMB_LOCK_TREE)
	message(FATAL_ERROR "SEMB_ENGINE_INSTALL_DIVERGED: recomputing engine_tree_sha from the bytes "
		"currently on disk under ${SEMB_ENGINE_PREFIX} gives ${_semb_recomputed_tree}, which disagrees "
		"with the lock's tree=${SEMB_LOCK_TREE}. The installed prefix was modified after "
		"tools/pin-superslm wrote its provenance.")
endif()

message(STATUS "SuperSLM engine pin verified: ${superslm_VERSION} @ ${_semb_prov_commit} "
	"(engine_tree_sha=${SEMB_LOCK_TREE})")
