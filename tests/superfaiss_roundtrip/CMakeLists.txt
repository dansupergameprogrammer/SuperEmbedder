# Standalone project for the round-trip harness's SuperFAISS program (plan
# U2-2). It is configured by tests/superfaiss_roundtrip/roundtrip.py, never by
# the product's own CMakeLists.txt, so nothing here is linked into the product.
#
# SUPERFAISS_SOURCE is a tree exported at superfaiss.lock's commit. Every
# src/*.cpp is compiled into the program with the flags SuperFAISS's
# docs/INTEGRATION.md section 1 calls non-negotiable:
#   GCC/Clang: -ffp-contract=off everywhere, -msse4.2 on kernels.cpp (x86);
#              the AVX2 TU needs nothing (target attributes).
#   MSVC:      /fp:precise everywhere, /arch:AVX2 on kernels_avx2.cpp.
#   clang-cl:  the MSVC flags, plus /clang:-ffp-contract=off everywhere and
#              /clang:-msse4.2 on kernels.cpp (x64/X86). CMake sets MSVC for
#              clang-cl too, so it is told apart by compiler ID Clang with the
#              MSVC frontend variant, as SuperFAISS's own CMakeLists.txt does
#              from its clang-cl fix onward. Without -msse4.2 clang-cl rejects
#              kernels.cpp's SSE4.1 intrinsics; without -ffp-contract=off its
#              /fp:precise permits implicit FMA contraction.
cmake_minimum_required(VERSION 3.21)
project(semb_superfaiss_roundtrip CXX)

if(NOT SUPERFAISS_SOURCE OR NOT EXISTS "${SUPERFAISS_SOURCE}/include/superfaiss/superfaiss.h")
	message(FATAL_ERROR "SUPERFAISS_SOURCE must name a SuperFAISS tree exported at superfaiss.lock's commit")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

file(GLOB SUPERFAISS_SOURCES CONFIGURE_DEPENDS "${SUPERFAISS_SOURCE}/src/*.cpp")
add_executable(sf_roundtrip sf_roundtrip.cpp ${SUPERFAISS_SOURCES})
target_include_directories(sf_roundtrip PRIVATE "${SUPERFAISS_SOURCE}/include")

set(SEMB_SF_CLANG_CL OFF)
if(MSVC AND CMAKE_CXX_COMPILER_ID STREQUAL "Clang"
		AND CMAKE_CXX_COMPILER_FRONTEND_VARIANT STREQUAL "MSVC")
	set(SEMB_SF_CLANG_CL ON)
endif()

if(MSVC)
	target_compile_options(sf_roundtrip PRIVATE /fp:precise)
	set_source_files_properties("${SUPERFAISS_SOURCE}/src/kernels_avx2.cpp" PROPERTIES COMPILE_OPTIONS "/arch:AVX2")
	if(SEMB_SF_CLANG_CL)
		target_compile_options(sf_roundtrip PRIVATE /clang:-ffp-contract=off)
		if(CMAKE_CXX_COMPILER_ARCHITECTURE_ID MATCHES "^(x64|X86)$")
			set_source_files_properties("${SUPERFAISS_SOURCE}/src/kernels.cpp" PROPERTIES COMPILE_OPTIONS "/clang:-msse4.2")
		endif()
	endif()
else()
	target_compile_options(sf_roundtrip PRIVATE -ffp-contract=off)
	if(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|AMD64|i686")
		set_source_files_properties("${SUPERFAISS_SOURCE}/src/kernels.cpp" PROPERTIES COMPILE_OPTIONS "-msse4.2")
	endif()
endif()
