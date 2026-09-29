"""U2 cloud build, U2-6: the certification package's scripts and refusals (te267 U2-6; sec 10 M6, M25).

Grades tools/certify/: the CPU probe, build_package.py's build-time refusals and python-runtime step, and run_certify.ps1's
refusals, run files, resumability and exit honesty. Every run_certify.ps1 leg runs the real script under the
PowerShell --pwsh names (Windows PowerShell 5.1 or PowerShell 7 on the dev box; PowerShell 7 elsewhere), in a
package this check constructs. Where the package carries a binary the host cannot provide here (the six other
members, the GPU binary, c63, wsl.exe), the construction stages tests/u2_6_fake_tool.cpp's program, which runs
the Python stand-in beside it; the stand-ins' behaviour is stated where they are written, below.

Legs:
  P1 probe      the probe prints HOST_BRAND, HOST_BEST_TIER and HOST_FEATURES; on Linux its tier equals the
                one /proc/cpuinfo's flags give (the kernel lists AVX-512 only when it saves that state), a
                second producer; elsewhere OBSERVED.
  P2 build      SEMB-PACKAGE-BUILD-ENV-FLAGS-SET <var> for each of CFLAGS, CXXFLAGS, LDFLAGS and
                CMAKE_TOOLCHAIN_FILE, on `pin` and on `build`, before anything runs; SEMB-PACKAGE-GPU-ENGINE-
                MISMATCH when the GPU binary's engine build record differs from msvc19.33-auto's, with nothing
                staged, and the GPU binary staged (shaders included) when they are equal; `python-runtime`
                refuses SEMB-PACKAGE-PYTHON-RUNTIME-MISMATCH for another Python version, a wheel not tagged
                cp313-cp313-win_amd64 and a SHA-256 other than the given one, writing nothing; unpacks a
                constructed embeddable zip and wheel into python/ (numpy in Lib/site-packages, the ._pth
                naming it) with both SHA-256s recorded; a re-run changes nothing; a file changed afterwards is
                restored by the next run; `finish` refuses SEMB-PACKAGE-BINARY-MISSING python before it, and
                after it writes the package's files and package.json with this tree's derivation-input digest
                and the runtime record.
  P3 refusals   SEMB-PACKAGE-BINARY-MISSING for a member's semb, the GPU binary and c63; SEMB-PACKAGE-WSL-
                DISTRO-MISSING; SEMB-PACKAGE-WSL-DISTRO-VERSION-MISMATCH; SEMB-PACKAGE-CPU-TIER-UNSUPPORTED for
                the forced AVX-512 member on an AVX2 host; SEMB-PACKAGE-BINARY-MISSING python for an absent
                python/python.exe, for one that cannot import numpy, and for an absent -Python override: each
                exits non-zero, prints the name, and runs nothing (no results/docs, no stand-in invoked).
  P4 dev box    the default run on an AVX2 host: the six dev-box cells' run directories, each with the file
                set U2-3 item 12 fixes, row digests recomputed here from the bank the stand-in wrote, every
                run.json copy equal to the manifest, run ids unique, msvc19.33-auto's query-digests.tsv
                recomputed here from the session's own output bytes, rt4-digests.txt, readings, the round
                trip and readings run by the package's own python/python.exe with nothing on PATH asked;
                nothing written outside results/; exit 0.
  P5 resume     a member that crashes mid-bake: exit non-zero, every other member done; the next run bakes
                only that member and exits 0; a third run bakes nothing; a run file edited afterwards makes
                the next run redo exactly that member's bake and the steps that read it.
  P6 work mach. the default run on an AVX-512 host with -Host -Gpu: the five @avx512 cells, C63, host mode
                equal to the receipts, GPU mode's gpu/<runId>/ with device and gpu_* copied; a receipt that
                differs in one row fails host mode by name.
  P7 final      -Final -Members: runs only the named members, under <cell>/final/, pass "final" and the five
                fingerprint components; -Final with -Gpu is refused.
  P8 real semb  the package with this build's own semb in two members' place, staged by build_package.py's
                `stage` from this build and its engine, and bin/tools by its `tools` step (the synthetic cap-512
                pair): its run files recomputed here from the real bank and read by the C42 checker's own Run
                reader and flag-record clause; the query digests equal `semb query --raw`
                one-shot vectors for three texts, a second output mode; the round trip in its prebuilt mode
                with SuperFAISS's program compiled from the pinned tree (MISSING PREREQUISITE without a
                SuperFAISS source); and a truncated model copy exits non-zero with no run written (the
                self-test's deliberate failure, U2-6 "Proof").

Exit 0 when every graded leg passes (MISSING PREREQUISITE legs pass); 1 otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import struct
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CERTIFY = REPO / "tools" / "certify"
sys.path.insert(0, str(CERTIFY))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "tools"))
import build_package as bp  # noqa: E402
import c35_two_installation_harness as c35  # noqa: E402

WINDOWS = os.name == "nt"
MEMBERS = list(bp.MEMBERS)
AUTO = "msvc19.33-auto"
WSL = bp.WSL_MEMBER
GPU = bp.GPU_BINARY


class Report:
    def __init__(self) -> None:
        self.failed = False

    def add(self, state: str, cell: str, detail: str) -> None:
        print(f"[{state}] {cell}: {detail}", flush=True)
        if state == "FAIL":
            self.failed = True

    def check(self, ok: bool, cell: str, detail: str) -> bool:
        self.add("PASS" if ok else "FAIL", cell, detail)
        return ok


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# -- the stand-ins ---------------------------------------------------------------------------------------------
# All read SEMB_FAKE_CONFIG (a JSON file) and append one line per invocation to its "log".
COMMON = r'''
import hashlib, json, os, struct, sys
from pathlib import Path
CONFIG = json.loads(Path(os.environ["SEMB_FAKE_CONFIG"]).read_text(encoding="utf-8"))
HERE = Path(__file__).resolve().parent
def log(line):
    with open(CONFIG["log"], "a", encoding="utf-8") as f:
        f.write(line + "\n")
'''

# semb: `bake` writes a DIMS-wide float32 bank whose rows are a function of the text alone (so every member's
# rows agree), and a manifest whose tier is the forced tier for a forced member and CONFIG["tier"] otherwise.
# It refuses (exit 7, like SEMB_ARTIFACT_UNREADABLE) a model whose size is not CONFIG["model_bytes"], and
# crashes (exit 3, after writing a partial bank) when its member is in CONFIG["crash"]. `query --stdin`
# prints one VECTOR_HEX= line per input line.
FAKE_SEMB = COMMON + r'''
DIMS = 8
def vec(text):
    d = hashlib.sha256(text.encode("utf-8")).digest()
    return struct.pack("<8f", *[(b - 128) / 64.0 for b in d[:8]])
def opt(args, name):
    return args[args.index(name) + 1] if name in args else None
member = HERE.name
args = sys.argv[1:]
log(f"{member} {args[0]}")
model = opt(args, "--model")
if Path(model).stat().st_size != CONFIG["model_bytes"]:
    print("semb: SEMB_ARTIFACT_UNREADABLE", file=sys.stderr); sys.exit(7)
tier_of = {"msvc19.33-sse2": "sse2", "msvc19.33-avx2": "avx2", "msvc19.33-avx512": "avx512"}
tier = tier_of.get(member, CONFIG["tier"])
if member == "gcc13.3.0-wsl-auto":
    tier = CONFIG.get("wsl_tier", tier)
cell = ("msvc19.33-auto" if member == "msvc19.33-auto-gpu" else member) + "@" + tier
if args[0] == "bake":
    rows = [json.loads(l) for l in Path(args[1]).read_text(encoding="utf-8").splitlines() if l.strip()]
    stem = opt(args, "--out")
    Path(stem + ".wvbank.json").write_text(json.dumps({"dims": DIMS, "count": len(rows), "dtype": "float32",
        "metric": "cosine", "ids": [r["id"] for r in rows]}), encoding="utf-8")
    if member in CONFIG.get("crash", []):
        sys.exit(3)
    Path(stem + ".wvbank.bin").write_bytes(b"".join(vec(r["text"]) for r in rows))
    gpu = opt(args, "--device") == "gpu"
    manifest = {"model_sha": "m" * 64, "tokenizer_sha": "t" * 64, "template_sha256": "p" * 64,
        "witness_sha": "w" * 64, "certification_epoch": "e" * 64, "encoder_fingerprint": "f" * 64,
        "certified_builds_sha256": CONFIG.get("list_sha", "l" * 64), "certified_cell": cell,
        "build_descriptor": {"os": "windows", "isa": "x86-64", "toolchain": member.split("-")[0],
            "stdlib": "stl", "configuration": "Release", "buildSystem": "cmake",
            "dispatch": tier_of.get(member, "auto"), "compileFlags": "c" * 64, "engineFlags": "g" * 64},
        "count": len(rows), "dims": DIMS, "machine_tier": tier,
        "token_id_digest": hashlib.sha256("|".join(r["id"] for r in rows).encode()).hexdigest(),
        "device": "gpu" if gpu else "cpu"}
    if gpu:
        manifest.update({"gpu_vendor_id": "0x10de", "gpu_device_id": "0x1e81",
                         "gpu_adapter_name": "Stand-in GPU", "gpu_driver_version": "1.2.3"})
    Path(stem + ".semb.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
elif args[0] == "query":
    for line in sys.stdin.buffer.read().split(b"\n"):
        if line:
            sys.stdout.write("VECTOR_HEX=" + vec(line.decode("utf-8")).hex() + "\n")
    sys.stderr.write("query_handle_opens=1\n")
else:
    sys.exit(2)
'''

# The CPU probe, both builds: under the wsl.exe stand-in (SEMB_FAKE_IN_WSL) it is the Linux build.
FAKE_PROBE = COMMON + r'''
in_wsl = os.environ.get("SEMB_FAKE_IN_WSL") == "1"
log("probe-linux" if in_wsl else "probe")
print("HOST_BRAND=" + CONFIG.get("brand", "Stand-in CPU"))
print("HOST_BEST_TIER=" + (CONFIG.get("wsl_tier", CONFIG["tier"]) if in_wsl else CONFIG["tier"]))
print("HOST_FEATURES=stand-in")
'''

FAKE_C63 = COMMON + r'''
log("c63 " + " ".join(sys.argv[1:3]))
for mc in (1, 4):
    print(f"[PASS] C63 (i) semb_encode armed, mc {mc}: stand-in")
print("TOTAL fail=%d" % CONFIG.get("c63_fail", 0))
sys.exit(1 if CONFIG.get("c63_fail", 0) else 0)
'''

# wsl.exe: `-l -q` lists CONFIG["distros"] in UTF-16LE, as wsl.exe does; `-d <d> -u root --exec <cmd>` runs
# <cmd> here: wslpath echoes, cat /etc/os-release and dpkg-query answer from CONFIG, and a program with a
# stand-in script beside it runs that script.
FAKE_WSL = COMMON + r'''
import subprocess
args = sys.argv[1:]
if args[:2] == ["-l", "-q"]:
    sys.stdout.buffer.write("\r\n".join(CONFIG.get("distros", [])).encode("utf-16-le") + "\r\n".encode("utf-16-le"))
    sys.exit(0)
if args[:1] != ["-d"] or args[2:5] != ["-u", "root", "--exec"]:
    print("wsl stand-in: unexpected " + repr(args), file=sys.stderr); sys.exit(2)
if args[1] not in CONFIG.get("distros", []):
    sys.exit(1)
cmd = args[5:]
log("wsl " + " ".join(cmd[:2]))
if cmd[0] == "wslpath":
    print(cmd[-1]); sys.exit(0)
if cmd[:2] == ["cat", "/etc/os-release"]:
    print('NAME="Ubuntu"\nVERSION_ID="%s"' % CONFIG.get("wsl_version", "24.04")); sys.exit(0)
if cmd[0] == "dpkg-query":
    print({"libc6": "2.39-0ubuntu8.9", "libstdc++6": "14.2.0-4ubuntu2~24.04.1"}[cmd[-1]], end=""); sys.exit(0)
target = Path(cmd[0])
script = target.with_name(target.stem + ".py")
env = dict(os.environ, SEMB_FAKE_IN_WSL="1")
if script.is_file():
    sys.exit(subprocess.run([sys.executable, str(script)] + cmd[1:], env=env).returncode)
sys.exit(subprocess.run(cmd, env=env).returncode)
'''

# python/python.exe: the package's own interpreter. It logs "python <what it runs>" and runs it under the
# interpreter running this stand-in (SEMB_FAKE_PYTHON, which has numpy), passing stdio and the exit code through;
# with CONFIG["python_no_numpy"] its import check fails, as an interpreter without numpy's would.
FAKE_PYTHON = COMMON + r'''
import subprocess
args = sys.argv[1:]
what = "-c" if args[:1] == ["-c"] else (Path(args[0]).name if args else "")
log("python " + what)
if what == "-c" and CONFIG.get("python_no_numpy") and "numpy" in args[1]:
    print("ModuleNotFoundError: No module named 'numpy'", file=sys.stderr)
    sys.exit(1)
sys.exit(subprocess.run([sys.executable] + args).returncode)
'''

# A working Python with numpy on PATH (python, python3, python.exe, py.exe): the script must never ask it.
FAKE_PATH_PYTHON = COMMON + r'''
import subprocess
log("PATH-python " + " ".join(sys.argv[1:2]))
sys.exit(subprocess.run([sys.executable] + sys.argv[1:]).returncode)
'''

FAKE_ROUNDTRIP = r'''
import sys
from pathlib import Path
a = sys.argv[1:]
out = Path(a[a.index("--out") + 1]); out.mkdir(parents=True, exist_ok=True)
assert Path(a[a.index("--bank") + 1] + ".wvbank.bin").is_file()
(out / "rt4-digests.tsv").write_text("artifact\tsynthetic\nint8_bank_sha256\t%s\ncrossdevice_hits_sha256\t%s\n"
    % ("1" * 64, "2" * 64), encoding="utf-8", newline="\n")
print("[PASS] stand-in round trip")
'''

FAKE_READINESS = r'''
import json, sys
from pathlib import Path
a = sys.argv[1:]
out = Path(a[a.index("--out") + 1]); out.mkdir(parents=True, exist_ok=True)
(out / "readiness.json").write_text(json.dumps({"cell": a[a.index("--cell") + 1], "stand_in": True}))
print("[READING] stand-in")
'''


def stage_tool(fake_exe: Path, dest: Path, script: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fake_exe, dest)
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    dest.with_name(dest.stem + ".py").write_text(script, encoding="utf-8")


def build_fake_package(pkg: Path, fake_exe: Path, corpus_src: Path, model_bytes: int) -> None:
    shutil.rmtree(pkg, ignore_errors=True)
    pkg.mkdir(parents=True)
    shutil.copyfile(CERTIFY / "run_certify.ps1", pkg / "run_certify.ps1")
    shutil.copyfile(CERTIFY / "gpu-legs.json", pkg / "gpu-legs.json")
    for member in MEMBERS + [GPU]:
        name = "semb" if member == WSL else "semb.exe"
        stage_tool(fake_exe, pkg / "bin" / member / name, FAKE_SEMB)
        (pkg / "bin" / member / "compile-flags.json").write_text('{"member": "%s"}\n' % member)
        (pkg / "bin" / member / "engine-flags.json").write_text('{"engine": "%s"}\n' % member)
        (pkg / "bin" / member / "member.json").write_text(json.dumps({
            "member": member, "enginePin": {"tag": "v1.8.0", "commit": "c" * 40, "engine_tree_sha": "d" * 64},
            "engineBuildRecord": "sslm-build-record-v1:" + "0" * 64, "productCommit": "a" * 40,
            "derivationInputsSha256": "b" * 64, "semb": name}))
    stage_tool(fake_exe, pkg / "bin" / bp.C63_MEMBER / "c63.exe", FAKE_C63)
    stage_tool(fake_exe, pkg / "bin" / "tools" / "host_cpuid.exe", FAKE_PROBE)
    stage_tool(fake_exe, pkg / "bin" / "tools" / "host_cpuid", FAKE_PROBE)
    (pkg / "bin" / "tools" / "sf_roundtrip.exe").write_bytes(b"stand-in")
    stage_tool(fake_exe, pkg / "python" / "python.exe", FAKE_PYTHON)
    (pkg / "artifacts").mkdir()
    (pkg / "artifacts" / "model.sslm").write_bytes(b"M" * model_bytes)
    (pkg / "artifacts" / "tokenizer.sslm").write_bytes(b"T" * 100)
    (pkg / "corpus").mkdir()
    shutil.copyfile(corpus_src, pkg / "corpus" / "corpus-239.idtext.jsonl")
    (pkg / "c63").mkdir()
    for name in ("mid.txt", "short.txt"):
        shutil.copyfile(REPO / "tests" / "fixtures" / "c63" / name, pkg / "c63" / name)
    rt = pkg / "harness" / "tests" / "superfaiss_roundtrip" / "roundtrip.py"
    rt.parent.mkdir(parents=True)
    rt.write_text(FAKE_ROUNDTRIP, encoding="utf-8")
    rd = pkg / "harness" / "tools" / "readiness" / "readiness.py"
    rd.parent.mkdir(parents=True)
    rd.write_text(FAKE_READINESS, encoding="utf-8")
    (pkg / "harness" / "wvbank.py").write_text("# stand-in\n")
    (pkg / "package.json").write_text(json.dumps({
        "schemaVersion": 1, "productCommit": "a" * 40, "derivationInputsSha256": "b" * 64, "members": MEMBERS,
        "model": {"file": "model.sslm"}, "tokenizer": {"file": "tokenizer.sslm"},
        "corpus": "corpus/corpus-239.idtext.jsonl", "artifactKind": "synthetic"}))


class Runner:
    def __init__(self, pwsh: list[str], python: str, fake_bin: Path, work: Path) -> None:
        self.pwsh, self.python, self.fake_bin, self.work = pwsh, python, fake_bin, work

    def config(self, **values) -> Path:
        cfg = {"log": str(self.work / "invocations.log"), "tier": "avx2", "model_bytes": 1000,
               "distros": ["Ubuntu-24.04"]}
        cfg.update(values)
        path = self.work / "config.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        return path

    def invocations(self) -> list[str]:
        log = self.work / "invocations.log"
        lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        log.unlink(missing_ok=True)
        return lines

    def run(self, pkg: Path, *script_args: str, with_wsl: bool = True,
            python_arg: str | None = None) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ, SEMB_FAKE_PYTHON=self.python, SEMB_FAKE_CONFIG=str(self.work / "config.json"))
        path = env.get("PATH", "")
        if with_wsl:
            path = str(self.fake_bin) + os.pathsep + path
        env["PATH"] = path
        cmd = self.pwsh + ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(pkg / "run_certify.ps1"),
                           *script_args] + (["-Python", python_arg] if python_arg is not None else [])
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace", env=env, timeout=1800)


def tree_outside_results(pkg: Path) -> dict[str, str]:
    return {str(p.relative_to(pkg)): sha(p.read_bytes()) for p in sorted(pkg.rglob("*"))
            if p.is_file() and p.relative_to(pkg).parts[0] != "results"}


def recompute_run(run_dir: Path, bank_stem: Path, report: Report, label: str, cell: str) -> dict | None:
    """Recomputes a run directory's files from the bank the member wrote; returns run.json."""
    names = ("row-digests.tsv", "token-id-digest.txt", "bake-manifest.semb.json", "compile-flags.json",
             "engine-flags.json", "run.json")
    missing = [n for n in names if not (run_dir / n).is_file()]
    if not report.check(not missing, f"{label} file set", f"{run_dir.name}: " + (", ".join(missing) + " missing"
                                                                                   if missing else "all six files")):
        return None
    header = json.loads(Path(str(bank_stem) + ".wvbank.json").read_text(encoding="utf-8"))
    payload = Path(str(bank_stem) + ".wvbank.bin").read_bytes()
    manifest_bytes = Path(str(bank_stem) + ".semb.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    stride = 4 * header["dims"]
    tsv = "".join(f"{i}\t{sha(payload[k * stride:(k + 1) * stride])}\n" for k, i in enumerate(header["ids"]))
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    ok = (run_dir / "row-digests.tsv").read_bytes() == tsv.encode()
    ok &= (run_dir / "bake-manifest.semb.json").read_bytes() == manifest_bytes
    ok &= (run_dir / "token-id-digest.txt").read_bytes() == (manifest["token_id_digest"] + "\n").encode()
    copies = {"buildDescriptor": "build_descriptor", "machineTier": "machine_tier", "dispatchedTier": "machine_tier",
              "certificationEpoch": "certification_epoch", "certifiedBuildsSha256": "certified_builds_sha256",
              "certifiedCell": "certified_cell", "tokenIdDigest": "token_id_digest"}
    bad = [k for k, m in copies.items() if run.get(k) != manifest.get(m)]
    bad += [k for k, v in (("manifestSha256", sha(manifest_bytes)), ("rowDigest", sha(tsv.encode())),
                           ("cellId", cell)) if run.get(k) != v]
    report.check(ok and not bad, f"{label} run files recomputed",
                 f"{cell}: rows, tokens and manifest recomputed from the bank; run.json fields "
                 + ("all equal" if not bad else "differ: " + ", ".join(bad)))
    return run


# -- legs -----------------------------------------------------------------------------------------------------
def leg_probe(report: Report, probe: Path) -> None:
    out = subprocess.run([str(probe)], capture_output=True, text=True)
    fields = dict(re.findall(r"^(HOST_[A-Z_]+)=(.*)$", out.stdout, re.M))
    ok = out.returncode == 0 and set(fields) == {"HOST_BRAND", "HOST_BEST_TIER", "HOST_FEATURES"} and \
        fields.get("HOST_BEST_TIER") in ("scalar", "sse2", "avx2", "avx512")
    report.check(ok, "P1 probe output", out.stdout.strip().replace("\n", " | "))
    cpuinfo = Path("/proc/cpuinfo")
    if platform.system() == "Linux" and cpuinfo.is_file() and platform.machine() in ("x86_64", "AMD64"):
        flags = set()
        for line in cpuinfo.read_text().splitlines():
            if line.startswith("flags"):
                flags = set(line.split(":", 1)[1].split())
                break
        want = "scalar"
        if "sse2" in flags:
            want = "sse2"
        if {"avx", "avx2", "fma"} <= flags:
            want = "avx2"
        if {"avx", "avx2", "fma", "avx512f", "avx512bw"} <= flags:
            want = "avx512"
        report.check(fields.get("HOST_BEST_TIER") == want, "P1 probe tier = /proc/cpuinfo",
                     f"probe {fields.get('HOST_BEST_TIER')}, cpuinfo flags {want}")
    else:
        report.add("OBSERVED", "P1 probe tier", f"{fields.get('HOST_BEST_TIER')} (no /proc/cpuinfo to compare)")


def leg_build(report: Report, work: Path) -> None:
    root = work / "p2"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    for step in ("pin", "build"):
        for var in bp.ENV_FLAGS:
            argv = [step, "--member", AUTO, "--engine-prefix", str(root / "no-prefix")]
            if step == "pin":
                argv += ["--source", str(root / "no-source")]
            else:
                argv += ["--build-dir", str(root / "no-build")]
            env = {k: v for k, v in os.environ.items() if k not in bp.ENV_FLAGS}
            env[var] = "/arch:AVX2" if var != "CMAKE_TOOLCHAIN_FILE" else "x.cmake"
            proc = subprocess.run([sys.executable, str(CERTIFY / "build_package.py"), *argv], capture_output=True,
                                  text=True, env=env)
            report.check(proc.returncode == 1 and proc.stderr.strip() == f"SEMB-PACKAGE-BUILD-ENV-FLAGS-SET {var}"
                         and "+ " not in proc.stdout and not (root / "no-build").exists(),
                         f"P2 {step} refuses {var}", f"exit {proc.returncode}: {proc.stderr.strip()}")
    proc = subprocess.run([sys.executable, str(CERTIFY / "build_package.py"), "build", "--member", "msvc19.33-avx1024",
                           "--engine-prefix", "x", "--build-dir", "y"], capture_output=True, text=True)
    report.check(proc.returncode == 1 and "SEMB-PACKAGE-UNKNOWN-MEMBER msvc19.33-avx1024" in proc.stderr,
                 "P2 unknown member refused", proc.stderr.strip())

    def prefix(name: str, record: str) -> Path:
        p = root / name / "share" / "superslm-provenance"
        p.mkdir(parents=True)
        (p / "provenance.json").write_text(json.dumps({"engine_build": {
            "buildRecord": record, "flagsSha": "f" * 64, "dispatch": "auto",
            "flags": {"family": "msvc", "record": {}, "residual": []}}}))
        return root / name

    def build_dir(name: str) -> Path:
        b = root / name
        (b / "generated").mkdir(parents=True)
        (b / "generated" / "compile-flags.json").write_text("{}\n")
        (b / "generated" / "semb_engine_pin.h").write_text(
            '#define SEMB_ENGINE_PIN_TAG "v1.8.0"\n#define SEMB_ENGINE_PIN_COMMIT "%s"\n'
            '#define SEMB_ENGINE_PIN_TREE_SHA "%s"\n' % ("c" * 40, "d" * 64))
        (b / "semb.exe").write_bytes(b"exe")
        return b

    pkg = root / "package"
    auto_prefix, same, other = prefix("e-auto", "rec-A"), prefix("e-gpu-same", "rec-A"), prefix("e-gpu-other", "rec-B")
    shaders = root / "shaders"
    shaders.mkdir()
    (shaders / "k.cso").write_bytes(b"cso")
    rc = bp.main(["stage", "--package", str(pkg), "--member", AUTO, "--build-dir", str(build_dir("b-auto")),
                  "--engine-prefix", str(auto_prefix), "--repo", str(REPO)])
    report.check(rc == 0 and (pkg / "bin" / AUTO / "member.json").is_file(), "P2 stage msvc19.33-auto", f"exit {rc}")
    proc = subprocess.run([sys.executable, str(CERTIFY / "build_package.py"), "stage", "--package", str(pkg),
                           "--member", GPU, "--build-dir", str(build_dir("b-gpu")), "--engine-prefix", str(other),
                           "--shaders", str(shaders), "--repo", str(REPO)], capture_output=True, text=True)
    report.check(proc.returncode == 1 and proc.stderr.startswith("SEMB-PACKAGE-GPU-ENGINE-MISMATCH")
                 and not (pkg / "bin" / GPU).exists(), "P2 GPU engine mismatch refused",
                 f"exit {proc.returncode}: {proc.stderr.strip()[:160]}")
    rc = bp.main(["stage", "--package", str(pkg), "--member", GPU, "--build-dir", str(root / "b-gpu"),
                  "--engine-prefix", str(same), "--shaders", str(shaders), "--repo", str(REPO)])
    report.check(rc == 0 and (pkg / "bin" / GPU / "shaders" / "k.cso").is_file()
                 and json.loads((pkg / "bin" / GPU / "member.json").read_text())["engineBuildRecord"] == "rec-A",
                 "P2 GPU binary staged on the auto member's engine record", f"exit {rc}")
    leg_python_runtime(report, root, pkg)
    # `finish`: the package's own files, and the tree's commit and derivation-input digest in package.json.
    import derivation_inputs
    model, tokenizer = root / "m.sslm", root / "t.sslm"
    model.write_bytes(b"model")
    tokenizer.write_bytes(b"tokenizer")
    rc = bp.main(["finish", "--package", str(pkg), "--model", str(model), "--tokenizer", str(tokenizer),
                  "--repo", str(REPO)])
    meta = json.loads((pkg / "package.json").read_text()) if (pkg / "package.json").is_file() else {}
    rows = (pkg / "corpus" / "corpus-239.idtext.jsonl").read_text(encoding="utf-8").splitlines() \
        if (pkg / "corpus" / "corpus-239.idtext.jsonl").is_file() else []
    same = all((pkg / n).read_bytes() == (CERTIFY / n).read_bytes() for n in ("run_certify.ps1", "gpu-legs.json"))
    report.check(rc == 0 and meta.get("derivationInputsSha256") == derivation_inputs.digest(REPO) and len(rows) == 239
                 and meta.get("model", {}).get("sha256") == sha(b"model") and same
                 and (pkg / "harness" / "tests" / "superfaiss_roundtrip" / "roundtrip.py").is_file()
                 and (pkg / "harness" / "tools" / "readiness" / "readiness.py").is_file()
                 and meta.get("pythonRuntime") == json.loads((pkg / "python-runtime.json").read_text()),
                 "P2 finish writes the package's files and package.json",
                 f"exit {rc}; {len(rows)} corpus rows; derivation digest {meta.get('derivationInputsSha256')}")


def leg_python_runtime(report: Report, root: Path, pkg: Path) -> None:
    """build_package.py python-runtime over a constructed embeddable zip and numpy wheel (D-SLM7811)."""
    import zipfile

    def build_py(*argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(CERTIFY / "build_package.py"), *argv], capture_output=True,
                              text=True)

    def make_zip(path: Path, members: dict[str, bytes]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as z:
            for name, data in members.items():
                z.writestr(name, data)
        return path

    pth = b"python313.zip\r\n.\r\n\r\n# Uncomment to run site.main() automatically\r\n#import site\r\n"
    embed = {"python.exe": b"MZ python", "python313.dll": b"MZ dll", "python313.zip": b"PK stdlib",
             "python313._pth": pth}
    dl = root / "downloads"
    good_zip = make_zip(dl / "python-3.13.7-embed-amd64.zip", embed)
    old_zip = make_zip(dl / "python-3.12.10-embed-amd64.zip", embed)

    def wheel(tag: str) -> Path:
        return make_zip(dl / tag / f"numpy-2.3.3-{tag}.whl", {
            "numpy/__init__.py": b"__version__ = '2.3.3'\n",
            "numpy-2.3.3.dist-info/WHEEL": f"Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: {tag}\n".encode()})

    good_whl, old_whl = wheel("cp313-cp313-win_amd64"), wheel("cp312-cp312-win_amd64")
    finish = build_py("finish", "--package", str(pkg), "--model", "m", "--tokenizer", "t", "--repo", str(REPO))
    report.check(finish.returncode == 1 and finish.stderr.startswith("SEMB-PACKAGE-BINARY-MISSING python")
                 and not (pkg / "package.json").exists(), "P2 finish before python-runtime refused",
                 f"exit {finish.returncode}: {finish.stderr.strip()[:120]}")
    for label, argv, needle in (
            ("another Python version", ["--embeddable-zip", str(old_zip), "--numpy-wheel", str(good_whl)], "3.12.10"),
            ("a cp312 wheel", ["--embeddable-zip", str(good_zip), "--numpy-wheel", str(old_whl)], "cp313-cp313-win_amd64"),
            ("a SHA-256 other than the given", ["--embeddable-zip", str(good_zip), "--numpy-wheel", str(good_whl),
                                                "--numpy-sha256", "0" * 64], "sha256")):
        proc = build_py("python-runtime", "--package", str(pkg), *argv)
        report.check(proc.returncode == 1 and proc.stderr.startswith("SEMB-PACKAGE-PYTHON-RUNTIME-MISMATCH")
                     and needle in proc.stderr and not (pkg / "python").exists()
                     and not (pkg / "python-runtime.json").exists(), f"P2 python-runtime refuses {label}",
                     f"exit {proc.returncode}: {proc.stderr.strip()[:140]}")
    args = ["python-runtime", "--package", str(pkg), "--embeddable-zip", str(good_zip), "--numpy-wheel", str(good_whl),
            "--numpy-sha256", sha(good_whl.read_bytes()).upper()]
    proc = build_py(*args)
    py = pkg / "python"
    rec = json.loads((pkg / "python-runtime.json").read_text()) if (pkg / "python-runtime.json").is_file() else {}
    pth_lines = (py / "python313._pth").read_bytes().split(b"\r\n") if (py / "python313._pth").is_file() else []
    report.check(proc.returncode == 0 and (py / "python.exe").read_bytes() == b"MZ python"
                 and (py / "Lib" / "site-packages" / "numpy" / "__init__.py").is_file()
                 and pth_lines[:3] == [b"python313.zip", b".", b"Lib\\site-packages"] and b"#import site" in pth_lines
                 and rec.get("embeddableZip", {}).get("sha256") == sha(good_zip.read_bytes())
                 and rec.get("numpyWheel", {}).get("sha256") == sha(good_whl.read_bytes())
                 and rec.get("pythonVersion") == "3.13.7" and rec.get("numpyVersion") == "2.3.3"
                 and not (pkg / "python.partial").exists(), "P2 python-runtime unpacks and records",
                 f"exit {proc.returncode}; record {sorted(rec)}; ._pth {pth_lines[:3]}")
    before = {str(q.relative_to(pkg)): (q.stat().st_mtime_ns, q.read_bytes()) for q in sorted(py.rglob("*")) if q.is_file()}
    proc = build_py(*args)
    after = {str(q.relative_to(pkg)): (q.stat().st_mtime_ns, q.read_bytes()) for q in sorted(py.rglob("*")) if q.is_file()}
    report.check(proc.returncode == 0 and "nothing to do" in proc.stdout and before == after,
                 "P2 python-runtime re-run changes nothing", proc.stdout.strip()[:120])
    (py / "Lib" / "site-packages" / "numpy" / "__init__.py").write_text("tampered\n")
    proc = build_py(*args)
    report.check(proc.returncode == 0 and "unpacked" in proc.stdout
                 and (py / "Lib" / "site-packages" / "numpy" / "__init__.py").read_bytes() == b"__version__ = '2.3.3'\n",
                 "P2 python-runtime restores a changed tree", proc.stdout.strip()[:120])


def leg_refusals(report: Report, r: Runner, pkg: Path, fake_exe: Path, corpus: Path) -> None:
    def expect(label: str, name: str, *args: str, with_wsl: bool = True, python_arg: str | None = None) -> None:
        shutil.rmtree(pkg / "results", ignore_errors=True)
        proc = r.run(pkg, *args, with_wsl=with_wsl, python_arg=python_arg)
        ran = [l for l in r.invocations() if not l.startswith(("probe", "wsl", "python -c"))]
        report.check(proc.returncode == 1 and name in proc.stdout and not ran
                     and not (pkg / "results" / "docs").exists(), f"P3 {label}",
                     f"exit {proc.returncode}; '{name}' {'printed' if name in proc.stdout else 'NOT printed'}; "
                     f"{len(ran)} member invocations")

    r.config(tier="avx2")
    for victim, name in ((pkg / "bin" / "msvc19.33-avx2" / "semb.exe", "SEMB-PACKAGE-BINARY-MISSING msvc19.33-avx2"),
                         (pkg / "bin" / GPU / "semb.exe", f"SEMB-PACKAGE-BINARY-MISSING {GPU}"),
                         (pkg / "bin" / bp.C63_MEMBER / "c63.exe", "SEMB-PACKAGE-BINARY-MISSING c63")):
        hidden = victim.with_name(victim.name + ".hidden")
        victim.rename(hidden)
        expect(f"{victim.parent.name}/{victim.name} absent", name)
        hidden.rename(victim)
    r.config(tier="avx2", distros=["Ubuntu-22.04"])
    expect("Ubuntu-24.04 absent", "SEMB-PACKAGE-WSL-DISTRO-MISSING")
    r.config(tier="avx2", wsl_version="22.04")
    expect("Ubuntu-24.04 at another VERSION_ID", "SEMB-PACKAGE-WSL-DISTRO-VERSION-MISMATCH 22.04")
    r.config(tier="avx2")
    expect("forced AVX-512 member on an AVX2 host", "SEMB-PACKAGE-CPU-TIER-UNSUPPORTED msvc19.33-avx512",
           "-Members", "msvc19.33-avx512")
    expect("-Final with -Gpu", "SEMB-PACKAGE-USAGE", "-Final", "-Gpu", "-Members", AUTO)
    # The package's own Python (D-SLM7811): absent, unable to import numpy, and an absent -Python override.
    own = pkg / "python" / "python.exe"
    own.rename(own.with_name("python.exe.hidden"))
    expect("python/python.exe absent, a working Python on PATH", "SEMB-PACKAGE-BINARY-MISSING python")
    own.with_name("python.exe.hidden").rename(own)
    r.config(tier="avx2", python_no_numpy=True)
    expect("python/python.exe without numpy", "SEMB-PACKAGE-BINARY-MISSING python")
    r.config(tier="avx2")
    expect("-Python naming an absent interpreter", "SEMB-PACKAGE-BINARY-MISSING python",
           python_arg=str(pkg / "no-such-python.exe"))
    if not WINDOWS:  # a Windows host may have a real wsl.exe on PATH; the stand-in is then the only one
        expect("no wsl.exe at all", "SEMB-PACKAGE-WSL-DISTRO-MISSING", with_wsl=False)


def member_calls(calls: list[str]) -> list[str]:
    """A member's own bake and query invocations (the wsl.exe stand-in logs the command it runs as well)."""
    return [c for c in calls if c.endswith((" bake", " query")) and not c.startswith("wsl ")]


def cells_of(pkg: Path) -> dict[str, Path]:
    root = pkg / "results" / "docs" / "certification" / "1.0.0"
    return {d.name: d for d in sorted(root.iterdir()) if d.is_dir() and d.name != "gpu"} if root.is_dir() else {}


def check_cells(report: Report, pkg: Path, label: str, want: set[str], pass_: str = "provisional") -> dict:
    cells = cells_of(pkg)
    report.check(set(cells) == want, f"{label} cells", f"{sorted(cells)} (want {sorted(want)})")
    runs = {}
    for cell, d in cells.items():
        member = cell.split("@")[0]
        run_dir = d / "final" if pass_ == "final" else d
        stem = pkg / "results" / "work" / member / pass_ / "bank" / "corpus"
        run = recompute_run(run_dir, stem, report, f"{label} {cell}", cell)
        if run:
            runs[cell] = run
            report.check(run.get("pass") == pass_ and run.get("hostBestTier") and run.get("host")
                         and run.get("enginePin", {}).get("tag") == "v1.8.0" and run.get("productCommit") == "a" * 40
                         and run.get("derivationInputsSha256") == "b" * 64, f"{label} {cell} run.json provenance",
                         f"pass {run.get('pass')}, hostBestTier {run.get('hostBestTier')}, host {run.get('host')}")
    ids = [r["runId"] for r in runs.values()]
    report.check(len(ids) == len(set(ids)), f"{label} run ids unique", ", ".join(ids))
    return runs


def check_query(report: Report, pkg: Path, cell: str, label: str, pass_: str = "provisional") -> None:
    d = cells_of(pkg).get(cell)
    run_dir = (d / "final" if pass_ == "final" else d) if d else None
    qd = run_dir / "query-digests.tsv" if run_dir else None
    if not report.check(bool(qd and qd.is_file()), f"{label} query-digests.tsv", str(qd)):
        return
    out = (pkg / "results" / "work" / AUTO / f"{pass_}-query" / "query.out").read_bytes().decode()
    texts = (pkg / "results" / "work" / AUTO / f"{pass_}-query" / "query-texts.txt").read_bytes()
    rows = [json.loads(l) for l in (pkg / "corpus" / "corpus-239.idtext.jsonl").read_text(encoding="utf-8").splitlines()]
    want = "".join(f"{row['id']}\t{sha(bytes.fromhex(line[len('VECTOR_HEX='):]))}\n"
                   for row, line in zip(rows, out.splitlines()))
    report.check(qd.read_text(encoding="utf-8") == want and len(out.splitlines()) == len(rows)
                 and texts == "".join(r["text"] + "\n" for r in rows).encode("utf-8") and not texts.startswith(b"\xef\xbb\xbf"),
                 f"{label} query digests recomputed", f"{len(rows)} texts, LF, UTF-8 without a BOM; digests of the "
                                                      "session's own VECTOR_HEX bytes")
    report.check((run_dir / "rt4-digests.txt").is_file(), f"{label} rt4-digests.txt", str(run_dir / "rt4-digests.txt"))


def leg_dev_box(report: Report, r: Runner, pkg: Path) -> None:
    shutil.rmtree(pkg / "results", ignore_errors=True)
    r.config(tier="avx2")
    before = tree_outside_results(pkg)
    proc = r.run(pkg)
    calls = r.invocations()
    report.check(proc.returncode == 0, "P4 dev-box run exit 0", f"exit {proc.returncode}" +
                 ("" if proc.returncode == 0 else ": " + (proc.stdout + proc.stderr)[-1500:]))
    want = {"msvc19.33-auto@avx2", "msvc19.33-sse2@sse2", "msvc19.33-avx2@avx2", "clangcl18.1.8-auto@avx2",
            "msvc19.44.35214-auto@avx2", "gcc13.3.0-wsl-auto@avx2"}
    runs = check_cells(report, pkg, "P4", want)
    wsl = runs.get("gcc13.3.0-wsl-auto@avx2", {})
    report.check(wsl.get("wslGuest", {}).get("VERSION_ID") == "24.04" and wsl.get("wslGuest", {}).get("libc6")
                 == "2.39-0ubuntu8.9" and "wsl -d" not in proc.stdout and any(c.startswith("wsl ") for c in calls)
                 and "probe-linux" in calls, "P4 WSL member through wsl.exe",
                 f"wslGuest {wsl.get('wslGuest')}; linux probe ran: {'probe-linux' in calls}")
    check_query(report, pkg, "msvc19.33-auto@avx2", "P4")
    report.check((pkg / "results" / "readings" / "msvc19.33-auto@avx2" / "readiness.json").is_file(),
                 "P4 readings", "results/readings/msvc19.33-auto@avx2/readiness.json")
    report.check(not any("c63" in c for c in calls), "P4 no C63 on the dev box", "C63 runs with the AVX-512 member")
    pys = [c for c in calls if c.startswith("python ")]
    path_py = [c for c in calls if c.startswith("PATH-python")]
    report.check(pys == ["python -c", "python roundtrip.py", "python readiness.py"] and not path_py,
                 "P4 the package's own Python", f"python/python.exe ran {pys}; a working Python on PATH ran "
                                                f"{len(path_py)} times (no -Python given)")
    summary = json.loads((pkg / "results" / "summary.json").read_text(encoding="utf-8"))
    report.check(summary.get("allStepsDone") is True and summary.get("hostBestTier") == "avx2",
                 "P4 summary.json", f"allStepsDone {summary.get('allStepsDone')}, {len(summary.get('steps', []))} steps")
    report.check(tree_outside_results(pkg) == before, "P4 writes only under results/",
                 "every file outside results/ is byte-identical after the run")


def leg_resume(report: Report, r: Runner, pkg: Path) -> None:
    shutil.rmtree(pkg / "results", ignore_errors=True)
    r.config(tier="avx2", crash=["clangcl18.1.8-auto"])
    first = r.run(pkg)
    calls = [c for c in member_calls(r.invocations()) if c.endswith(" bake")]
    report.check(first.returncode == 1 and "INCOMPLETE" in first.stdout and len(calls) == 6
                 and "clangcl18.1.8-auto@avx2" not in cells_of(pkg) and len(cells_of(pkg)) == 5,
                 "P5 a crashing member", f"exit {first.returncode}; bakes {calls}; cells {sorted(cells_of(pkg))}")
    r.config(tier="avx2")
    second = r.run(pkg)
    calls = member_calls(r.invocations())
    report.check(second.returncode == 0 and calls == ["clangcl18.1.8-auto bake"], "P5 resume runs only the crashed member",
                 f"exit {second.returncode}; invocations {calls}")
    third = r.run(pkg)
    calls = member_calls(r.invocations())
    report.check(third.returncode == 0 and calls == [] and third.stdout.count("[DONE]") >= 9,
                 "P5 a finished package runs nothing", f"exit {third.returncode}; invocations {calls}")
    tsv = cells_of(pkg)["msvc19.33-auto@avx2"] / "row-digests.tsv"
    tsv.write_bytes(tsv.read_bytes().replace(b"\t", b"\t0", 1)[:-1])
    fourth = r.run(pkg)
    calls = member_calls(r.invocations())
    report.check(fourth.returncode == 0 and calls == ["msvc19.33-auto bake", "msvc19.33-auto query"],
                 "P5 an edited run file redoes that member and what reads it", f"exit {fourth.returncode}; {calls}")
    check_cells(report, pkg, "P5 after resume", {"msvc19.33-auto@avx2", "msvc19.33-sse2@sse2", "msvc19.33-avx2@avx2",
                                                 "clangcl18.1.8-auto@avx2", "msvc19.44.35214-auto@avx2",
                                                 "gcc13.3.0-wsl-auto@avx2"})


def leg_work_machine(report: Report, r: Runner, pkg: Path, dev_receipts: dict[str, bytes]) -> None:
    shutil.rmtree(pkg / "results", ignore_errors=True)
    shutil.rmtree(pkg / "receipts", ignore_errors=True)
    for cell, rows in dev_receipts.items():
        (pkg / "receipts" / cell).mkdir(parents=True)
        (pkg / "receipts" / cell / "row-digests.tsv").write_bytes(rows[0])
        (pkg / "receipts" / cell / "token-id-digest.txt").write_bytes(rows[1])
    r.config(tier="avx512")
    proc = r.run(pkg, "-Host", "-Gpu")
    calls = r.invocations()
    report.check(proc.returncode == 0, "P6 work-machine run exit 0", f"exit {proc.returncode}" +
                 ("" if proc.returncode == 0 else ": " + (proc.stdout + proc.stderr)[-1500:]))
    check_cells(report, pkg, "P6", {"msvc19.33-auto@avx512", "msvc19.33-avx512@avx512", "clangcl18.1.8-auto@avx512",
                                    "msvc19.44.35214-auto@avx512", "gcc13.3.0-wsl-auto@avx512"})
    report.check(any(c.startswith("c63") for c in calls) and
                 (pkg / "results" / "c63" / "msvc19.33-avx512@avx512" / "c63.out").is_file(),
                 "P6 C63 after the AVX-512 member's bake", "results/c63/msvc19.33-avx512@avx512/c63.out")
    host = pkg / "results" / "host-mode"
    report.check(sorted(p.name for p in host.iterdir()) == ["msvc19.33-avx2@avx2", "msvc19.33-sse2@sse2"]
                 if host.is_dir() else False, "P6 host mode under results/host-mode, not a new cell",
                 str(sorted(p.name for p in host.iterdir())) if host.is_dir() else "absent")
    gpu_root = pkg / "results" / "docs" / "certification" / "1.0.0" / "gpu"
    gruns = sorted(gpu_root.iterdir()) if gpu_root.is_dir() else []
    ok = len(gruns) == 1
    if ok:
        run = recompute_run(gruns[0], pkg / "results" / "work" / "gpu" / "proof-corpus" / "bank" / "corpus", report,
                            "P6 GPU run", "msvc19.33-auto@avx512")
        ok = bool(run) and run.get("device") == "gpu" and run.get("gpu_adapter_name") == "Stand-in GPU" \
            and run.get("runId") == gruns[0].name
    report.check(ok, "P6 GPU mode gpu/<runId>/", f"{[p.name for p in gruns]}")
    # A receipt that differs in one row fails host mode by name, and only host mode.
    tsv = pkg / "receipts" / "msvc19.33-sse2@sse2" / "row-digests.tsv"
    lines = tsv.read_bytes().split(b"\n")
    lines[3] = lines[3][:-1] + (b"0" if lines[3][-1:] != b"0" else b"1")
    tsv.write_bytes(b"\n".join(lines))
    shutil.rmtree(host, ignore_errors=True)
    proc = r.run(pkg, "-Host", "-Gpu")
    report.check(proc.returncode == 1 and "HOST-MODE DIFFERENCE: msvc19.33-sse2@sse2" in proc.stdout
                 and "[PASS]    msvc19.33-avx2 host-mode bake" in proc.stdout, "P6 host-mode difference refused",
                 f"exit {proc.returncode}")
    r.invocations()


def leg_final(report: Report, r: Runner, pkg: Path) -> None:
    r.config(tier="avx512", list_sha="9" * 64)
    proc = r.run(pkg, "-Final", "-Members", "msvc19.33-auto,msvc19.33-avx512")
    calls = [c for c in r.invocations() if c.endswith((" bake", " query")) or c.startswith("c63")]
    calls = [c for c in calls if not c.startswith("wsl ")]
    report.check(proc.returncode == 0 and calls == ["msvc19.33-auto bake", "msvc19.33-auto query",
                                                   "msvc19.33-avx512 bake"], "P7 final runs only the named members",
                 f"exit {proc.returncode}; {calls}")
    for cell in ("msvc19.33-auto@avx512", "msvc19.33-avx512@avx512"):
        d = cells_of(pkg)[cell] / "final"
        run = recompute_run(d, pkg / "results" / "work" / cell.split("@")[0] / "final" / "bank" / "corpus", report,
                            f"P7 {cell} final", cell)
        fc = (run or {}).get("fingerprintComponents", {})
        report.check(bool(run) and run.get("pass") == "final" and sorted(fc) == sorted(
            ["model_sha", "tokenizer_sha", "template_sha256", "witness_sha", "certification_epoch"])
            and run.get("certifiedBuildsSha256") == "9" * 64, f"P7 {cell} final run.json",
            f"pass {(run or {}).get('pass')}, components {sorted(fc)}")
    check_query(report, pkg, "msvc19.33-auto@avx512", "P7", "final")


def engine_prefix_of(build_dir: Path) -> Path | None:
    cache = build_dir / "CMakeCache.txt"
    if cache.is_file():
        found = re.search(r"^CMAKE_PREFIX_PATH:[A-Z]*=(.*)$", cache.read_text(encoding="utf-8", errors="replace"), re.M)
        if found and found.group(1).strip():
            return Path(found.group(1).strip().split(";")[0])
    return None


def leg_real(report: Report, r: Runner, work: Path, build_dir: Path, semb: Path, probe: Path, fake_exe: Path,
             corpus: Path, superfaiss: str) -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("roundtrip", REPO / "tests" / "superfaiss_roundtrip" / "roundtrip.py")
    rt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rt)
    try:
        model, tokenizer = rt.synthetic_pair(REPO / "build" / "_scratch" / "te222_c17_pair")
    except Exception as exc:  # noqa: BLE001
        report.add("FAIL", "P8 synthetic pair", f"{type(exc).__name__}: {exc}")
        return
    pkg = work / "p8-package"
    build_fake_package(pkg, fake_exe, corpus, 1000)
    shutil.copyfile(model, pkg / "artifacts" / "model.sslm")
    shutil.copyfile(tokenizer, pkg / "artifacts" / "tokenizer.sslm")
    # The two real members are staged by build_package.py's own `stage` step from this build and its engine.
    prefix = engine_prefix_of(build_dir)
    for member in (AUTO, "clangcl18.1.8-auto"):
        rc = bp.main(["stage", "--package", str(pkg), "--member", member, "--build-dir", str(semb.parent),
                      "--engine-prefix", str(prefix), "--repo", str(REPO)]) if prefix else 1
        if not report.check(rc == 0, f"P8 build_package stage {member}", f"from {semb.parent}, engine {prefix}"):
            return
    shutil.copy2(probe, pkg / "bin" / "tools" / "host_cpuid.exe")
    # The round trip, real, in its prebuilt mode: build_package.py's `tools` step compiles SuperFAISS's program
    # from the tree superfaiss.lock pins and stages it with wvbank.py and this build's probe.
    have_rt = False
    if superfaiss:
        rc = bp.main(["tools", "--package", str(pkg), "--probe-windows", str(probe), "--probe-linux", str(probe),
                      "--superfaiss-source", superfaiss, "--repo", str(REPO)])
        if not report.check(rc == 0 and (pkg / "bin" / "tools" / "sf_roundtrip.exe").stat().st_size > 1000,
                            "P8 build_package tools", "SuperFAISS's program compiled from the pinned tree"):
            return
        stage_tool(fake_exe, pkg / "bin" / "tools" / "host_cpuid", FAKE_PROBE)  # the Linux slot keeps its stand-in
        shutil.copy2(probe, pkg / "bin" / "tools" / "host_cpuid.exe")
        for rel in ("tests/superfaiss_roundtrip/roundtrip.py", "tests/te230_c5_floor.py",
                    "tests/fixtures/c12b/corpus-239.jsonl"):
            (pkg / "harness" / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / rel, pkg / "harness" / rel)
        have_rt = True
    else:
        report.add("MISSING PREREQUISITE", "P8 round trip, prebuilt mode",
                   "needs a SuperFAISS clone (SEMB_SUPERFAISS_SOURCE); the stand-in round trip runs instead")
    r.config(tier="avx2", model_bytes=(pkg / "artifacts" / "model.sslm").stat().st_size)
    proc = r.run(pkg, "-Members", f"{AUTO},clangcl18.1.8-auto")
    r.invocations()
    report.check(proc.returncode == 0, "P8 real semb run exit 0", f"exit {proc.returncode}" +
                 ("" if proc.returncode == 0 else ": " + (proc.stdout + proc.stderr)[-2500:]))
    cells = cells_of(pkg)
    report.check(len(cells) == 2 and all(c.split("@")[1] in ("sse2", "avx2", "avx512") for c in cells),
                 "P8 cells from the real manifests' machine_tier", str(sorted(cells)))
    import check_certified_builds as c42
    import derivation_inputs
    tree = derivation_inputs.digest(REPO)
    for cell in cells:
        run = recompute_run(cells[cell], pkg / "results" / "work" / cell.split("@")[0] / "provisional" / "bank" /
                            "corpus", report, f"P8 {cell}", cell)
        # The checker's own readers over the package's files: the run's format, and C42 (b')'s flag clause (both
        # records recompute to the manifest's descriptor digests and carry no residual location).
        parsed = c42.Run(cells[cell].parent, cells[cell], cell, [])
        descriptor = (run or {}).get("buildDescriptor") or {}
        flags = [t for name, key in (("compile-flags.json", "compileFlags"), ("engine-flags.json", "engineFlags"))
                 for t in c42.flag_record_problems(cell, parsed.optional(name), name, descriptor.get(key))]
        report.check(not parsed.problems and not flags and (run or {}).get("derivationInputsSha256") == tree,
                     f"P8 {cell} read by the C42 checker", "; ".join(parsed.problems + flags) or
                     "run format, both flag records and the derivation-input digest of this tree")
    auto_cell = next((c for c in cells if c.startswith(AUTO + "@")), None)
    if auto_cell:
        check_query(report, pkg, auto_cell, "P8")
        rows = [json.loads(l) for l in corpus.read_text(encoding="utf-8").splitlines()]
        digests = dict(l.split("\t") for l in (cells[auto_cell] / "query-digests.tsv").read_text().splitlines())
        stem = pkg / "results" / "work" / AUTO / "provisional" / "bank" / "corpus"
        agree = []
        for row in rows[:3]:
            raw = subprocess.run([str(semb), "query", str(stem), row["text"], "--raw", "--model", model,
                                  "--tokenizer", tokenizer], capture_output=True)
            agree.append(raw.returncode == 0 and sha(raw.stdout) == digests.get(row["id"]))
        report.check(all(agree), "P8 query digests = semb query --raw", f"{sum(agree)}/3 one-shot --raw vectors agree")
        if have_rt:
            log = pkg / "results" / "roundtrip" / auto_cell / "provisional.txt"
            text = log.read_text(encoding="utf-8") if log.is_file() else ""
            report.check("[PASS] RT-2 SuperFAISS PerDevice float32 = numpy float64" in text and "[FAIL]" not in text
                         and (cells[auto_cell] / "rt4-digests.txt").is_file(), "P8 round trip in prebuilt mode",
                         f"{text.count('[PASS]')} PASS lines, RT-4 digests filed")
    # The self-test's deliberate failure: a truncated artifact copy exits non-zero and writes no run.
    shutil.rmtree(pkg / "results", ignore_errors=True)
    data = (pkg / "artifacts" / "model.sslm").read_bytes()
    (pkg / "artifacts" / "model.sslm").write_bytes(data[: len(data) // 2])
    proc = r.run(pkg, "-Members", "clangcl18.1.8-auto")
    r.invocations()
    report.check(proc.returncode == 1 and not cells_of(pkg) and "semb bake exited" in proc.stdout,
                 "P8 truncated model copy exits non-zero", f"exit {proc.returncode}; cells {sorted(cells_of(pkg))}")


def find_pwsh(explicit: str) -> list[str] | None:
    for cand in ([explicit] if explicit else []) + [os.environ.get("SEMB_PWSH", "")] + ["pwsh", "powershell"]:
        if cand and shutil.which(cand):
            return [shutil.which(cand)]
    return None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", type=Path, required=True)
    ap.add_argument("--probe", type=Path, required=True)
    ap.add_argument("--fake-tool", type=Path, required=True)
    ap.add_argument("--semb", type=Path, required=True)
    ap.add_argument("--pwsh", default="")
    ap.add_argument("--superfaiss-source", default="")
    ap.add_argument("--legs", default="P1,P2,P3,P4,P5,P6,P7,P8")
    args = ap.parse_args(argv)
    legs = set(args.legs.split(","))
    report = Report()
    work = args.build_dir / "_scratch" / "u2_6_package"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    if "P1" in legs:
        leg_probe(report, args.probe)
    if "P2" in legs:
        leg_build(report, work)
    pwsh = find_pwsh(args.pwsh)
    if pwsh is None:
        report.add("MISSING PREREQUISITE", "P3-P8 run_certify.ps1",
                   "no PowerShell (pwsh or powershell) on PATH and none named by --pwsh / SEMB_PWSH")
        return 1 if report.failed else 0
    fake_bin = work / "fake-bin"
    stage_tool(args.fake_tool, fake_bin / "wsl.exe", FAKE_WSL)
    for name in ("python", "python3", "python.exe", "py.exe"):
        stage_tool(args.fake_tool, fake_bin / name, FAKE_PATH_PYTHON)
    corpus = c35.corpus_jsonl(work)
    r = Runner(pwsh, sys.executable, fake_bin, work)
    pkg = work / "package"
    build_fake_package(pkg, args.fake_tool, corpus, 1000)
    if "P3" in legs:
        leg_refusals(report, r, pkg, args.fake_tool, corpus)
    if legs & {"P4", "P5", "P6", "P7"}:
        leg_dev_box(report, r, pkg)
        receipts = {c: ((cells_of(pkg)[c] / "row-digests.tsv").read_bytes(),
                        (cells_of(pkg)[c] / "token-id-digest.txt").read_bytes())
                    for c in ("msvc19.33-sse2@sse2", "msvc19.33-avx2@avx2") if c in cells_of(pkg)}
        if "P5" in legs:
            leg_resume(report, r, pkg)
        if "P6" in legs or "P7" in legs:
            leg_work_machine(report, r, pkg, receipts)
        if "P7" in legs:
            leg_final(report, r, pkg)
    if "P8" in legs:
        leg_real(report, r, work, args.build_dir, args.semb, args.probe, args.fake_tool, corpus,
                 args.superfaiss_source or os.environ.get("SEMB_SUPERFAISS_SOURCE", ""))
    print("u2_6_package_check: " + ("FAIL" if report.failed else "PASS"), flush=True)
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
