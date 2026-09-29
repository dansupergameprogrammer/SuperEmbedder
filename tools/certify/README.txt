SuperEmbedder 1.0 -- certification package (te267 U2-6)
========================================================

SOURCE OF TRUTH. This file, run_certify.ps1, build_package.py, host_cpuid.cpp and
gpu-legs.json are committed at tools/certify/ in the SuperEmbedder repository. The
package folder is assembled from them on the dev box by build_package.py; its bin\,
artifacts\ and results\ are never committed.

WHAT THIS IS
------------
A run-only package, in the pattern of SuperSLM's tools/t2116_crossvendor/: prebuilt
binaries, the model and tokenizer, the corpus, and one script. Nothing on the machine
that runs it needs Visual Studio, CMake or a compiler. It runs every certified cell's
bake on the host whose tier the cell names and writes the run files the release list
cites (docs/certification/1.0.0/<cell id>/, U2-3 item 12), plus msvc19.33-auto's
query session, round trip and readings, C63 on the forced AVX-512 member, and the GPU
binary's runs.

The host needs:
  - Windows PowerShell 5.1 or PowerShell 7 (either works; the script is ASCII-only).
  - Nothing else for Python: the package carries its own (python\, the Windows embeddable
    CPython 3.13 with numpy), which runs msvc19.33-auto's round trip and readings on both
    hosts. Nothing on PATH is used. -Python <python.exe> overrides it (not for certification).
  - The Ubuntu-24.04 WSL distro, for the WSL member (runtime only; no compiler):
        wsl --install -d Ubuntu-24.04 --no-launch
        wsl -d Ubuntu-24.04 -u root          (once, to initialize it; then exit)
  - The Microsoft Visual C++ runtime the MSVC binaries load (the VS 2022 redistributable).

PACKAGE CONTENTS
----------------
  run_certify.ps1         the entry script
  package.json            product commit, derivation-input digest, artifact hashes
  bin\<member>\           semb.exe (semb for the WSL member), compile-flags.json,
                          engine-flags.json, member.json -- one folder per member:
                            msvc19.33-auto  msvc19.33-sse2  msvc19.33-avx2
                            msvc19.33-avx512 (also c63.exe)  clangcl18.1.8-auto
                            msvc19.44.35214-auto  gcc13.3.0-wsl-auto
  bin\msvc19.33-auto-gpu\ the GPU binary: semb.exe and shaders\ (not a member)
  bin\tools\              host_cpuid.exe and host_cpuid (the CPU probe, Windows and
                          Linux builds), sf_roundtrip.exe (the round trip's program)
  artifacts\              the model and tokenizer
  corpus\                 corpus-239 as semb bake's {id, text} JSONL
  c63\                    C63's two texts
  harness\                the round trip and readiness scripts, SuperFAISS's wvbank.py
  receipts\               the dev-box receipts host mode compares against (sitting 1)
  python\                 the embeddable CPython 3.13 (amd64) with numpy in Lib\site-packages
  python-runtime.json     the two downloads' names and SHA-256s and the unpacked tree's digest
                          (also in package.json under pythonRuntime)
  gpu-legs.json           GPU mode's other legs (U3 fills it; see GPU MODE)
  results\                created by the script; the only place it writes

RUNNING IT
----------
Open PowerShell in the package folder.

  Dev box, REL-4 step 2 (provisional binaries, frozen tree):
      .\run_certify.ps1 -Gpu
  Work machine, sitting 1 (REL-4 step 3):
      .\run_certify.ps1 -Host -Gpu
  Dev box, REL-4 step 5.1 (final binaries):
      .\run_certify.ps1 -Final -Members msvc19.33-auto,msvc19.33-sse2,msvc19.33-avx2,clangcl18.1.8-auto,msvc19.44.35214-auto,gcc13.3.0-wsl-auto
  Work machine, sitting 2 (REL-4 step 5.2):
      .\run_certify.ps1 -Final -Members msvc19.33-auto,msvc19.33-avx512,clangcl18.1.8-auto,msvc19.44.35214-auto,gcc13.3.0-wsl-auto

Without -Members the script runs the members this host runs: on a host with
AVX-512F/BW (the work machine) msvc19.33-avx512 and the four auto members, on any
other host (the dev box) msvc19.33-sse2, msvc19.33-avx2 and the four auto members.
Windows PowerShell may need: powershell -ExecutionPolicy Bypass -File run_certify.ps1
Use a 64-bit PowerShell: a 32-bit one cannot see System32\wsl.exe and refuses the WSL member.

IF IT STOPS OR THE MACHINE CRASHES
----------------------------------
Run the same command again. Every step records itself in results\state\<machine>\
when it has written its files, and a later run skips every step whose files still
match its record. A step that was interrupted has no record and runs again from its
start. Nothing needs cleaning up by hand. The last line says whether every step is
done; results\summary.json lists each step.

WHAT TO RETURN
--------------
The whole results\ folder. Its docs\certification\1.0.0\ tree is what REL-4 step 4
commits; host-mode\, c63\, readings\, roundtrip\ and logs\ are the other evidence.

REFUSALS (printed before anything runs; exit 1)
-----------------------------------------------
  SEMB-PACKAGE-BINARY-MISSING <name>     a member's semb, the GPU binary, c63, a probe,
                                         sf_roundtrip, an artifact, or python\python.exe (or it
                                         cannot import numpy)
  SEMB-PACKAGE-WSL-DISTRO-MISSING        Ubuntu-24.04 is not installed
  SEMB-PACKAGE-WSL-DISTRO-VERSION-MISMATCH <v>
                                         its VERSION_ID is not 24.04
  SEMB-PACKAGE-CPU-TIER-UNSUPPORTED <m>  a forced member above this CPU's tier
  SEMB-PACKAGE-UNKNOWN-MEMBER <m>        -Members names something the package lacks
  SEMB-PACKAGE-USAGE <text>              -Final with -Gpu or -Host, or without -Members

GPU MODE
--------
-Gpu runs the GPU binary's `semb bake --device gpu` over the proof corpus and files it
under results\docs\certification\1.0.0\gpu\<runId>\, with the manifest's device and
four gpu_* labels copied into run.json (U2-3 item 15). It then runs every leg in
gpu-legs.json whose hostTier is this host's (the work machine's C10(c), C10(g) and
C11 cells, te266 sec 4.5), each filed under its own run id. The list ships empty:
U3 fills it, and adds --device gpu to the product, before REL-4 step 3.

BUILDING THE PACKAGE (dev box)
------------------------------
Each numbered step is one command, safe to re-run after a crash. Use a fresh
checkout of the frozen tree (REL-4 step 1) at <repo>, the package folder <pkg>, a
SuperSLM clone holding v1.8.0 at <slm>, and a SuperFAISS clone at <sf>. Pin and build
refuse by name (SEMB-PACKAGE-BUILD-ENV-FLAGS-SET) while CFLAGS, CXXFLAGS, LDFLAGS or
CMAKE_TOOLCHAIN_FILE is set.

For each MSVC 19.33 member (auto, sse2, avx2, avx512) and clangcl18.1.8-auto, in a
shell after `vcvars64.bat -vcvars_ver=14.33` (clang-cl: also set CC and CXX to
clang-cl); for msvc19.44.35214-auto after BuildTools' `vcvars64.bat`; for
gcc13.3.0-wsl-auto inside `wsl -d Ubuntu-24.04 -u root`:
  1. python tools/certify/build_package.py pin   --member <m> --engine-prefix <e_m> --source <slm>
  2. python tools/certify/build_package.py build --member <m> --engine-prefix <e_m> --build-dir <b_m>
  3. python tools/certify/build_package.py stage --package <pkg> --member <m> --build-dir <b_m> --engine-prefix <e_m>
The GPU binary, after msvc19.33-auto is staged, in the MSVC 19.33 shell (needs U3):
  4. the same three steps with --member msvc19.33-auto-gpu (pin adds --with-gpu,
     build adds SEMB_BUILD_GPU=ON), and --shaders <the engine's shader folder> on stage;
     stage refuses SEMB-PACKAGE-GPU-ENGINE-MISMATCH unless its engine's build record is
     msvc19.33-auto's.
Tools:
  5. In the MSVC 19.33 shell: cl /nologo /O2 /EHsc tools\certify\host_cpuid.cpp /Fe:<t>\host_cpuid.exe
  6. In the WSL distro: g++ -O2 -o <t>/host_cpuid tools/certify/host_cpuid.cpp
  7. In the MSVC 19.33 shell (compiles sf_roundtrip.exe from the pinned SuperFAISS tree):
     python tools/certify/build_package.py tools --package <pkg> --probe-windows <t>\host_cpuid.exe --probe-linux <t>/host_cpuid --superfaiss-source <sf>
Python (the package's own; download these two files, nothing else, on any machine):
     a. https://www.python.org/downloads/windows/ -> the newest Python 3.13.x release ->
        "Windows embeddable package (64-bit)": python-3.13.<n>-embed-amd64.zip
     b. https://pypi.org/project/numpy/#files -> the newest numpy release's
        numpy-<v>-cp313-cp313-win_amd64.whl, and the SHA-256 PyPI shows beside it
  8. python tools/certify/build_package.py python-runtime --package <pkg> --embeddable-zip <a> --numpy-wheel <b> --numpy-sha256 <PyPI's SHA-256>
     (refuses SEMB-PACKAGE-PYTHON-RUNTIME-MISMATCH naming what is wrong: another Python
     version or architecture, a wheel not tagged cp313-cp313-win_amd64, or a SHA-256 that
     differs; a re-run whose files still match does nothing)
  9. python tools/certify/build_package.py finish --package <pkg> --model <model.sslm> --tokenizer <tokenizer.sslm>
Before the work machine's first sitting, after the dev box's own run:
  10. python tools/certify/build_package.py receipts --package <pkg> --from <pkg>\results
