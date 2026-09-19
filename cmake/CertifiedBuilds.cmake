# cmake/CertifiedBuilds.cmake -- certification_epoch's input (plan sec 3.3,
# sec 4.1a; D-SLM7206). The encoder derives certification_epoch as the SHA-256
# of docs/certified-builds.json's exact committed bytes, and it derives it from
# bytes compiled into the library, never from a file read at run time. This
# module reads the document at configure time, refuses by name when it is
# missing or is not parseable as JSON, and writes those exact bytes into the
# generated header semb_certified_builds.h.
#
# The canonical bytes are the file's exact committed bytes (D-SLM7192): the
# repository's `* -text` attribute makes them identical on every checkout, so
# no line-ending normalization is applied here. An edit to the document
# re-runs configure (CMAKE_CONFIGURE_DEPENDS), so a rebuild always compiles
# the document it names; a binary built before an edit keeps the bytes it was
# built with, which is what C42 (d)'s post-build-edit construction checks.

set(SEMB_CERTIFIED_BUILDS_DOCUMENT "${CMAKE_SOURCE_DIR}/docs/certified-builds.json")

if(NOT EXISTS "${SEMB_CERTIFIED_BUILDS_DOCUMENT}")
	message(FATAL_ERROR
		"SEMB_CERTIFIED_BUILDS_MISSING: ${SEMB_CERTIFIED_BUILDS_DOCUMENT} does not exist. "
		"certification_epoch is the SHA-256 of this document's bytes, compiled into the library; "
		"the build cannot derive the encoder fingerprint without it.")
endif()
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${SEMB_CERTIFIED_BUILDS_DOCUMENT}")

file(READ "${SEMB_CERTIFIED_BUILDS_DOCUMENT}" _semb_certified_builds_text)
string(JSON _semb_certified_builds_type ERROR_VARIABLE _semb_certified_builds_error
	TYPE "${_semb_certified_builds_text}")
if(NOT _semb_certified_builds_error STREQUAL "NOTFOUND")
	message(FATAL_ERROR
		"SEMB_CERTIFIED_BUILDS_UNPARSEABLE: ${SEMB_CERTIFIED_BUILDS_DOCUMENT} is not parseable as JSON: "
		"${_semb_certified_builds_error}")
endif()

# The document's exact bytes, as a C array initializer, sixteen bytes a line.
file(READ "${SEMB_CERTIFIED_BUILDS_DOCUMENT}" _semb_certified_builds_hex HEX)
string(LENGTH "${_semb_certified_builds_hex}" _semb_certified_builds_hex_len)
math(EXPR SEMB_CERTIFIED_BUILDS_SIZE "${_semb_certified_builds_hex_len} / 2")
string(REGEX REPLACE "([0-9a-f][0-9a-f])" "0x\\1," _semb_certified_builds_bytes "${_semb_certified_builds_hex}")
string(REGEX REPLACE "((0x[0-9a-f][0-9a-f],){16})" "\\1\n    " SEMB_CERTIFIED_BUILDS_BYTES
	"${_semb_certified_builds_bytes}")
file(SHA256 "${SEMB_CERTIFIED_BUILDS_DOCUMENT}" SEMB_CERTIFIED_BUILDS_SHA256)
message(STATUS "certification_epoch (SHA-256 of docs/certified-builds.json, ${SEMB_CERTIFIED_BUILDS_SIZE} bytes): "
	"${SEMB_CERTIFIED_BUILDS_SHA256}")

configure_file(
	"${CMAKE_SOURCE_DIR}/cmake/templates/semb_certified_builds.h.in"
	"${CMAKE_BINARY_DIR}/generated/semb_certified_builds.h"
	@ONLY
)
