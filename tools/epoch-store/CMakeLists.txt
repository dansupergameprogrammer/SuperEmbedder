# tools/epoch-store/CMakeLists.txt -- TE-164 (U1 slice 3 build): the epoch
# store's own minting tool (`Claude/Plans/SuperEmbedder_Plan.md` sec 8,
# C32). Registered from the root CMakeLists.txt, before that file's own
# semb_assert_precise_fp() call, so this target is swept into C14's
# directory-wide precise-FP audit the same as every other target.
#
# Reads tests/semb_epoch_store_contract.h for the path/member-name constants
# ONLY (an include, never a write -- tests/** stays outside this seat's own
# writable scope); the include path below is scoped to this one target so no
# other tool or the library gains it by accident.
add_executable(epoch_store_mint "${CMAKE_CURRENT_SOURCE_DIR}/mint.cpp")
target_link_libraries(epoch_store_mint PRIVATE superembedder superslm::superslm)
target_include_directories(epoch_store_mint PRIVATE "${CMAKE_SOURCE_DIR}/tests")
set_target_properties(epoch_store_mint PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/tools")
