# tests/consumer/CMakeLists.txt -- TE-331 (U2-1 red suite): the out-of-tree
# consumer project (`Claude/Plans/te267-u2-release-plan.md` sec 5 U2-1 "Red
# first": "An out-of-tree consumer project (tests/consumer/) that calls
# find_package(superembedder 1.0 CONFIG REQUIRED), links, opens the
# synthetic artifact, encodes one string and checks the dimension -- fails
# at configure today (no config file).").
#
# DELIBERATELY NOT add_subdirectory()'d from the product's own root
# CMakeLists.txt or tests/CMakeLists.txt: an in-tree add_subdirectory sees
# the `superembedder` target directly (an IMPORTED or in-build target),
# which proves nothing about F4 (there is no install() surface at all --
# `git grep -n "install(" CMakeLists.txt` returns nothing at `fca421b`).
# This project is configured STANDALONE, exactly the way a real consumer
# would, against an INSTALL PREFIX:
#
#   cmake -S tests/consumer -B build/_scratch/te331_consumer \
#         -DCMAKE_PREFIX_PATH=<install prefix>
#
# tests/te331_u2_consumer_check.py drives it (build an install prefix by
# running `cmake --install` against the product build, then configure this
# project against that prefix) and reports the configure failure by name --
# today, `find_package(superembedder ...)` fails because no
# `superembedderConfig.cmake` exists anywhere, install or otherwise, because
# no install() rule writes one.
cmake_minimum_required(VERSION 3.21)
project(te331_u2_consumer CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(superembedder 1.0 CONFIG REQUIRED)

add_executable(te331_consumer main.cpp)
target_link_libraries(te331_consumer PRIVATE superembedder::superembedder)
