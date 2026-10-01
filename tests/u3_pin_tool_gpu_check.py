"""U3 red suite: the pin tool's GPU half (te266 sec 4.6 row 7, "The GPU flag
does not move the pin", P:4217; row 8's engineFlags legs, P:4218; the U2 plan's
J10, te267 P:3755: `--with-gpu` and the `.cso` exclusion land in
tools/pin-superslm/pin_superslm.py, and `tree=` is identical for the CPU-only
and GPU installs of one tag).

Unit legs, every platform, over the pin tool's own functions
(derive_install_closure, provenance_lib.digest_members, compile_flags.record
with the pin tool's own target list):

  PT-a     pin_superslm.py accepts --with-gpu (its --help names the option).
  PT-b     tree= over a GPU install equals tree= over the CPU-only install of
           the same tag: an install manifest that adds the GPU runtime's
           platform-varying outputs (shaders/*.cso, the superslm_gpu library)
           to the CPU-only manifest digests to the same engine_tree_sha.
  PT-b'    must-reject (P:4217): the same with `.cso` taken out of the
           exclusion set moves tree=. Its construction is the plan's ("a GPU
           install whose .cso exclusion is removed moves it").
  PT-c     pin (row 8 must-accept, unit form): engineFlags over the pin tool's
           target list ["superslm"] is equal whether or not the build's
           compile_commands.json also holds superslm_gpu's TUs.
  PT-c'    must-reject 2 (P:4218): a flagsSha taken over superslm and
           superslm_gpu together differs from it.

Dev-box legs (Windows, the engine's GPU build): PT-real, a real `--with-gpu`
install and a real CPU-only install of v1.8.0 give equal tree= and equal
engineFlags, and one invocation writes both the build record and the GPU
install (J10). Off Windows: MISSING PREREQUISITE.

RED TODAY: PT-a (no option) and PT-b (`.cso` is not excluded,
pin_superslm.py _EXCLUDED_INSTALL_SUFFIXES). PT-b' passes vacuously today
(nothing to remove); it becomes load-bearing with the exclusion. PT-c/c' are
pins of compile_flags' rule.
"""
from __future__ import annotations

import argparse
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIN = ROOT / "tools" / "pin-superslm"
sys.path.insert(0, str(PIN))
sys.path.insert(0, str(ROOT / "tools"))
import pin_superslm  # noqa: E402
import compile_flags  # noqa: E402
from provenance_lib import digest_members  # noqa: E402

FAILED = False


def emit(state: str, leg: str, detail: str) -> None:
    global FAILED
    print(f"[{state}] {leg}: {detail}", flush=True)
    FAILED |= state in ("FAIL", "RED-UNIMPLEMENTED")


CPU_FILES = {
    "include/superslm/superslm.h": b"// header\n",
    "include/superslm/sha256.h": b"// sha\n",
    "lib/cmake/superslm/superslmConfig.cmake": b"# config\n",
    "lib/cmake/superslm/superslmTargets.cmake": b"# targets\n",
    "lib/libsuperslm.a": b"\x7fELF-archive",
}
GPU_EXTRA = {
    "bin/shaders/prefill_attn.cso": b"DXBC-one",
    "bin/shaders/prefill_mlp.cso": b"DXBC-two",
    "lib/libsuperslm_gpu.a": b"\x7fELF-gpu-archive",
    "lib/cmake/superslm/superslmTargets-release.cmake": b"# release targets\n",
}


def tree_sha(tmp: Path, name: str, files: dict[str, bytes]) -> str:
    prefix = tmp / name / "prefix"
    build = tmp / name / "build"
    build.mkdir(parents=True)
    lines = []
    for rel, data in files.items():
        p = prefix / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        lines.append(str(p))
    (build / "install_manifest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    closure = pin_superslm.derive_install_closure(build, prefix)
    members = [("installed", p.relative_to(prefix.resolve()).as_posix(), p.read_bytes()) for p in sorted(closure)]
    return digest_members(members)


def entries(with_gpu: bool) -> list[dict]:
    out = [{"directory": "/b", "file": "/s/src/superslm.cpp", "output": "CMakeFiles/superslm.dir/src/superslm.cpp.o",
            "command": "/usr/bin/c++ -O2 -I/s/include -o CMakeFiles/superslm.dir/src/superslm.cpp.o -c /s/src/superslm.cpp"}]
    if with_gpu:
        out.append({"directory": "/b", "file": "/s/src/superslm_gpu.cpp",
                    "output": "CMakeFiles/superslm_gpu.dir/src/superslm_gpu.cpp.o",
                    "command": "/usr/bin/c++ -O2 -DSSLM_GPU=1 -I/s/include -o "
                               "CMakeFiles/superslm_gpu.dir/src/superslm_gpu.cpp.o -c /s/src/superslm_gpu.cpp"})
    return out


def flags_sha(targets: list[str], with_gpu: bool) -> str:
    rec, _ = compile_flags.record(entries(with_gpu), "gcc", [("/s", "<src>"), ("/b", "<build>")], targets, [], False)
    return compile_flags.digest(rec)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--python-executable", default=sys.executable)
    ap.add_argument("--scratch", default="")
    args = ap.parse_args(argv)

    helptext = subprocess.run([args.python_executable, str(PIN / "pin_superslm.py"), "--help"],
                              capture_output=True, text=True, errors="replace", cwd=ROOT)
    has = "--with-gpu" in helptext.stdout + helptext.stderr
    emit("PASS" if has else "FAIL", "PT-a pin_superslm.py accepts --with-gpu (J10, te267 P:3755)",
         "named in --help" if has else "--help does not name --with-gpu")

    with tempfile.TemporaryDirectory(prefix="u3_pin_", dir=args.scratch or None) as tmp:
        t = Path(tmp)
        cpu = tree_sha(t, "cpu", CPU_FILES)
        gpu = tree_sha(t, "gpu", {**CPU_FILES, **GPU_EXTRA})
        emit("PASS" if cpu == gpu else "FAIL",
             "PT-b tree= is equal for a GPU install and the CPU-only install of one tag (P:4217, J10)",
             f"cpu {cpu[:16]} / gpu {gpu[:16]}" + ("" if cpu == gpu else
                                                   " -- the GPU install's .cso files enter the install closure"))
        saved = set(pin_superslm._EXCLUDED_INSTALL_SUFFIXES)
        try:
            pin_superslm._EXCLUDED_INSTALL_SUFFIXES.discard(".cso")
            gpu_mut = tree_sha(t, "gpu_mut", {**CPU_FILES, **GPU_EXTRA})
        finally:
            pin_superslm._EXCLUDED_INSTALL_SUFFIXES.clear()
            pin_superslm._EXCLUDED_INSTALL_SUFFIXES.update(saved)
        emit("PASS" if gpu_mut != cpu else "FAIL",
             "PT-b' must-reject: with .cso taken out of the exclusion, the GPU install's tree= moves (P:4217)",
             f"cpu {cpu[:16]} / mutant {gpu_mut[:16]}" + ("" if ".cso" in saved else
                                                         " (vacuous today: .cso is not yet excluded)"))

    a, b = flags_sha(["superslm"], False), flags_sha(["superslm"], True)
    emit("PASS" if a == b else "FAIL",
         "PT-c pin: engineFlags over the pin tool's [\"superslm\"] ignores superslm_gpu's TUs (P:4218 must-accept, unit)",
         f"{a[:16]} / {b[:16]}")
    c = flags_sha(["superslm", "superslm_gpu"], True)
    emit("PASS" if c != a else "FAIL",
         "PT-c' must-reject 2: a flagsSha over superslm and superslm_gpu together moves engineFlags (P:4218)",
         f"{a[:16]} / {c[:16]}")

    if platform.system() == "Windows":
        emit("MISSING PREREQUISITE", "PT-real a real --with-gpu and CPU-only install of v1.8.0: equal tree= and "
             "engineFlags, one invocation writing both the build record and the GPU install (J10)",
             "run by the builder's pin step on the dev box (te266 sec 4.7 step 1b); not constructible in this cell")
    else:
        emit("MISSING PREREQUISITE", "PT-real the real --with-gpu install legs",
             "the engine's GPU build needs Windows and D3D12 (the dev box)")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
