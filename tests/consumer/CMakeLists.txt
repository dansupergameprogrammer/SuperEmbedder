# tests/consumer/CMakeLists.txt -- TE-331 (U2-1): the out-of-tree consumer
# project (`Claude/Plans/te267-u2-release-plan.md` sec 5 U2-1 "Red first":
# "An out-of-tree consumer project (tests/consumer/) that calls
# find_package(superembedder 1.0 CONFIG REQUIRED), links, opens the
# synthetic artifact, encodes one string and checks the dimension"; U2-7 "Red
# first" (1) and (2): the consumer's calls to semb_encoder_open_memory and
# semb_encode_query).
#
# DELIBERATELY NOT add_subdirectory()'d from the product's own root
# CMakeLists.txt or tests/CMakeLists.txt: an in-tree add_subdirectory sees
# the `superembedder` target directly, which proves nothing about the
# installed package. This project is configured STANDALONE, exactly the way a
# real consumer would, against an INSTALL PREFIX and nothing else (no engine
# prefix: the package depends on no other):
#
#   cmake -S tests/consumer -B <scratch> -DCMAKE_PREFIX_PATH=<install prefix>
#
# tests/te331_u2_consumer_check.py drives it.
cmake_minimum_required(VERSION 3.21)
project(te331_u2_consumer CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# The plan's request is 1.0, and it is the default. The installed package is
# SameMajorVersion and the product reads 0.1.0 until REL-1 sets 1.0.0, so this
# request is refused until then. The cache variable exists only so the check
# can run its mechanism leg at the package's own version; the 1.0 leg is the
# plan's proof.
set(SEMB_CONSUMER_REQUESTED_VERSION "1.0" CACHE STRING "the version find_package(superembedder) requests")
find_package(superembedder ${SEMB_CONSUMER_REQUESTED_VERSION} CONFIG REQUIRED)

add_executable(te331_consumer main.cpp)
target_link_libraries(te331_consumer PRIVATE superembedder::superembedder)
