"""tests/u2_3_c51_support.py -- shared apparatus for C51 (d)'s runtime legs (`Claude/Plans/te267-u2-release-plan.md`
sec 5 U2-3 item 13's must-rejects (k-1)...(k-9) and its Must-accepts; REL-2 step 1; plan of record sec 8 C51 (d)).

Not a test. The drivers that import it:

  tests/u2_3_c51_k1_k3_toolchain_check.py   (k-1) (k-2) (k-3), the own-compiler and second-CMake must-accepts
  tests/u2_3_c51_k4_verdict_test.cpp        (k-4), the open-time comparison graded as a function of its inputs
  tests/u2_3_c51_k5_k8_flags_check.py       (k-5) (k-6) (k-8)
  tests/u2_3_c51_k7_m4_checker_check.py     (k-7) (m4), C42 (b')'s location and engine-flag bindings
  tests/u2_3_c51_k9_tree_digest_check.py    (k-9)
  tests/u2_3_c51_any_directory_check.py     the any-directory must-accept and the platform-free lock (F33)

Every leg is a real execution: the pin tool, `cmake -S -B`, `cmake --build`, `semb --version` and `semb bake` on the
synthetic tokenizer pair (the verdict reads no artifact byte, so the synthetic pair decides the same cell a real
artifact would). Nothing here edits the repository: the product is configured from copies made by
tools/ci/run_configure_matrix.py's own `copy_repo`, and every pin writes a scratch copy of `superslm.lock`.

TOOLCHAINS. A leg's "toolchain" is a compiler plus the environment it runs in. The tree's own compiler (the one
this build directory was configured with, in the environment ctest runs in) is always present and is the member
under test. Others come from --toolchains-file, a JSON file
    {"toolchains": [{"name": "clangcl18.1.8", "cxx": "C:/Program Files/LLVM/bin/clang-cl.exe",
                     "env": "\"C:/Program Files/Microsoft Visual Studio/2022/BuildTools/VC/Auxiliary/Build/vcvars64.bat\" -vcvars_ver=14.33",
                     "member": true}, ...]}
where `env` (Windows only) is a command whose environment the toolchain runs in (captured once through
`cmd /c "call <env> && set"`), `cc` is optional (defaults to `cxx` on the MSVC frontend, the C driver beside
`cxx` otherwise) and `member` says whether the member legs ((k-8), the any-directory must-accept) run under it too.
Off Windows, with no file, a second compiler is found on PATH (clang++-18 or clang++ beside GCC, g++ beside Clang)
for the cross-compiler legs only; it is not a member.

OUTCOMES. Each leg prints `[PASS]`, `[FAIL]` or `[MISSING PREREQUISITE]` on one line. A driver exits 1 on any
FAIL; otherwise 77 when a leg was MISSING on Windows (the dev box, where every leg is owed: ctest reports the test
skipped, never passed), and 0 off Windows, where the Windows-compiler legs are MISSING by construction.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools" / "ci"))
sys.path.insert(0, str(REPO_ROOT / "tools"))
sys.path.insert(0, str(REPO_ROOT / "tests"))
import run_configure_matrix as matrix  # noqa: E402
import compile_flags  # noqa: E402
import u2_1_version_line_check as version_line  # noqa: E402

PIN_TOOL = REPO_ROOT / "tools" / "pin-superslm" / "pin_superslm.py"
LOCK = REPO_ROOT / "superslm.lock"
IDENTITY = "docs/certification-identity.json"
LIST = "docs/certified-builds.json"
EVIDENCE = "docs/certification/1.0.0"
WINDOWS = os.name == "nt"
DESCRIPTOR_FIELDS = version_line.DESCRIPTOR_FIELDS


# ---------------------------------------------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------------------------------------------
class Report:
    def __init__(self, title: str) -> None:
        self.title = title
        self.states: list[str] = []

    def leg(self, state: str, name: str, detail: str = "") -> str:
        print(f"[{state}] {name}" + (f" -- {detail}" if detail else ""), flush=True)
        self.states.append(state)
        return state

    def check(self, ok: bool, name: str, detail: str = "") -> bool:
        self.leg("PASS" if ok else "FAIL", name, detail)
        return ok

    def missing(self, name: str, why: str) -> None:
        self.leg("MISSING PREREQUISITE", name, why)

    def exit_code(self) -> int:
        failed = sum(s == "FAIL" for s in self.states)
        missing = sum(s == "MISSING PREREQUISITE" for s in self.states)
        print(f"TOTAL {self.title}: legs={len(self.states)} pass={sum(s == 'PASS' for s in self.states)} "
              f"fail={failed} missing={missing}", flush=True)
        if failed or not self.states:
            return 1
        return 77 if (missing and WINDOWS) else 0


def tail(text: str, n: int = 8) -> str:
    return " | ".join(text.strip().splitlines()[-n:])[-900:]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------------------------------------------
# Toolchains
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class Toolchain:
    name: str
    cxx: str
    cc: str
    family: str
    env: dict = field(default_factory=dict)
    member: bool = True

    def environ(self, extra: dict | None = None, drop: tuple[str, ...] = ()) -> dict:
        env = dict(self.env or os.environ)
        for k in ("CL", "_CL_", "CCC_OVERRIDE_OPTIONS", "CXXFLAGS", "CFLAGS"):
            env.pop(k, None)
        env["CXX"], env["CC"] = self.cxx, self.cc
        for k in drop:
            env.pop(k, None)
        env.update(extra or {})
        return env

    @property
    def avx2_flag(self) -> str:
        """The one added flag of (k-6)/(k-8): `/arch:AVX2` on the MSVC frontend, `-mavx2` on GCC and Clang."""
        return "/arch:AVX2" if self.family in ("msvc", "clangcl") else "-mavx2"


def _cc_beside(cxx: str) -> str:
    p = Path(cxx)
    name = p.name
    for a, b in (("clang++", "clang"), ("g++", "gcc"), ("c++", "cc")):
        if a in name:
            cand = p.with_name(name.replace(a, b)) if p.parent != Path("") else Path(name.replace(a, b))
            return str(cand)
    return cxx


def _capture_env(script: str) -> dict:
    proc = subprocess.run(f'cmd /d /s /c "call {script} >nul 2>&1 && set"', capture_output=True, text=True,
                          errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"the toolchain environment {script!r} could not be entered: {tail(proc.stderr)}")
    env = {}
    for line in proc.stdout.splitlines():
        if "=" in line and not line.startswith("="):
            k, v = line.split("=", 1)
            env[k] = v
    return env


def _version_text(cxx: str, env: dict | None = None) -> str | None:
    """The driver's `--version` stdout, stripped; None when it does not run."""
    try:
        return subprocess.run([cxx, "--version"], capture_output=True, text=True, env=env,
                              timeout=60).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None


def _compiler_identity(cxx: str, env: dict | None = None) -> tuple[str, str] | None:
    """(family, version) of a GCC- or Clang-style driver, from `--version`; None when it does not run."""
    try:
        out = subprocess.run([cxx, "--version"], capture_output=True, text=True, env=env, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"clang version (\d+\.\d+\.\d+)", out)
    if m:
        return ("clang", m.group(1))
    m = re.search(r"\(GCC\) (\d+\.\d+\.\d+)|g\+\+.* (\d+\.\d+\.\d+)", out)
    if m:
        return ("gcc", m.group(1) or m.group(2))
    return None


def self_toolchain(args) -> Toolchain:
    family = compile_flags.family_of(args.compiler_id, args.frontend)
    cxx = args.cxx
    cc = cxx if family in ("msvc", "clangcl") else _cc_beside(cxx)
    return Toolchain(name=f"{family}{args.compiler_version}", cxx=cxx, cc=cc, family=family, env=dict(os.environ))


def other_toolchains(args, me: Toolchain) -> tuple[list[Toolchain], str]:
    """The toolchains other than the tree's own, and how they were found."""
    if args.toolchains_file:
        doc = json.loads(Path(args.toolchains_file).read_text(encoding="utf-8"))
        out = []
        for t in doc.get("toolchains", []):
            env = _capture_env(t["env"]) if (WINDOWS and t.get("env")) else dict(os.environ)
            cxx = t["cxx"]
            fam = t.get("family")
            if not fam:
                low = Path(cxx).name.lower()
                fam = ("clangcl" if "clang-cl" in low else "msvc" if low in ("cl", "cl.exe") else
                       "clang" if "clang" in low else "gcc")
            cc = t.get("cc") or (cxx if fam in ("msvc", "clangcl") else _cc_beside(cxx))
            out.append(Toolchain(name=t["name"], cxx=cxx, cc=cc, family=fam, env=env,
                                 member=bool(t.get("member", True))))
        return [t for t in out if t.name != me.name], f"--toolchains-file {args.toolchains_file}"
    if WINDOWS:
        return [], "no --toolchains-file (SEMB_C51_TOOLCHAINS_FILE)"
    wanted = ("clang++-18", "clang++") if me.family == "gcc" else ("g++",)
    own_version = _version_text(me.cxx)
    same = []
    for name in wanted:
        path = shutil.which(name)
        ident = _compiler_identity(path) if path else None
        if ident:
            # A candidate whose --version is the tree's own compiler's is that
            # compiler under another name (AppleClang installs g++ as clang):
            # it is not another toolchain.
            if own_version and _version_text(path) == own_version:
                same.append(path)
                continue
            fam, ver = ident
            return [Toolchain(name=f"{fam}{ver}", cxx=path, cc=_cc_beside(path), family=fam,
                              env=dict(os.environ), member=False)], f"found {path} on PATH"
    if same:
        return [], (f"{same} on PATH report the same --version as the tree's own compiler {me.cxx}; "
                    f"no other compiler among {wanted}")
    return [], f"none of {wanted} on PATH"


def windows_members_note(report: Report, toolchains: list[Toolchain], leg: str) -> None:
    """Makes the dev box's share of a leg explicit: off Windows its MSVC and clang-cl members cannot run here."""
    fams = {t.family for t in toolchains}
    if not WINDOWS:
        report.missing(f"{leg} on the MSVC 19.33, clang-cl 18.1.8 and MSVC 19.44 members",
                       "Windows compilers; the dev box runs this leg (ctest -L c51_runtime in its MSVC tree, with "
                       "SEMB_C51_TOOLCHAINS_FILE naming the other two)")
    elif not {"msvc", "clangcl"} <= fams or sum(t.family == "msvc" for t in toolchains) < 2:
        report.missing(f"{leg} on every Windows member",
                       f"this run has {[t.name for t in toolchains]}; SEMB_C51_TOOLCHAINS_FILE names the others")


# ---------------------------------------------------------------------------------------------------------------
# Engine pins
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class Pin:
    rc: int
    output: str
    prefix: Path
    lock_copy: Path

    @property
    def ok(self) -> bool:
        return self.rc == 0 and (self.prefix / "share" / "superslm-provenance" / "provenance.json").is_file()

    def provenance(self) -> dict:
        return json.loads((self.prefix / "share" / "superslm-provenance" / "provenance.json").read_text("utf-8"))

    def lock_unchanged(self) -> bool:
        return self.lock_copy.is_file() and self.lock_copy.read_bytes() == LOCK.read_bytes()


def run_pin(tc: Toolchain, prefix: Path, workdir: Path, lock_copy: Path, engine_source: str,
            extra_env: dict | None = None, extra_args: tuple[str, ...] = (), cmake: str = "cmake",
            ninja: str = "ninja", drop_env: tuple[str, ...] = ()) -> Pin:
    lock_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(LOCK, lock_copy)
    cmd = [sys.executable, str(PIN_TOOL), "--lock", str(lock_copy), "--prefix", str(prefix),
           "--workdir", str(workdir), "--source", engine_source, "--cmake", cmake, "--ninja", ninja,
           *extra_args]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, errors="replace",
                          env=tc.environ(extra_env, drop_env))
    return Pin(proc.returncode, proc.stdout + proc.stderr, prefix, lock_copy)


class Engines:
    """Clean and flag-variant pins per toolchain, cached under <scratch>/engines (never edited in place)."""

    def __init__(self, scratch: Path, engine_source: str, cmake: str, ninja: str,
                 self_prefix: Path | None, me: Toolchain) -> None:
        self.root = scratch / "engines"
        self.source, self.cmake, self.ninja = engine_source, cmake, ninja
        self.self_prefix, self.me = self_prefix, me
        self.pins: dict[str, Pin] = {}

    def get(self, tc: Toolchain, variant: str = "clean", cxxflags: str | None = None) -> Pin:
        key = f"{tc.name}-{variant}"
        if key in self.pins:
            return self.pins[key]
        if variant == "clean" and tc.name == self.me.name and self.self_prefix and \
                (self.self_prefix / "share" / "superslm-provenance" / "provenance.json").is_file():
            pin = Pin(0, "the tree's own engine prefix", self.self_prefix, self.root / "locks" / f"{key}.lock")
            pin.lock_copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(LOCK, pin.lock_copy)
            self.pins[key] = pin
            return pin
        prefix = self.root / key
        stamp = prefix / "c51-pin.json"
        want = {"key": key, "lock": sha256(LOCK.read_bytes()), "cxxflags": cxxflags}
        lock_copy = self.root / "locks" / f"{key}.lock"
        if stamp.is_file() and json.loads(stamp.read_text("utf-8")) == want and lock_copy.is_file():
            pin = Pin(0, "cached", prefix, lock_copy)
        else:
            matrix.rmtree(self.root / "work" / key)
            pin = run_pin(tc, prefix, self.root / "work" / key, lock_copy, self.source,
                          extra_env={"CXXFLAGS": cxxflags} if cxxflags else None, cmake=self.cmake, ninja=self.ninja)
            if pin.ok:
                stamp.write_text(json.dumps(want), encoding="utf-8")
        self.pins[key] = pin
        return pin


# ---------------------------------------------------------------------------------------------------------------
# The product
# ---------------------------------------------------------------------------------------------------------------
class Product:
    def __init__(self, cmake: str, generator: str, ninja: str, python: str) -> None:
        self.cmake, self.generator, self.ninja, self.python = cmake, generator, ninja, python
        matrix.REPO_ROOT = REPO_ROOT

    @staticmethod
    def copy_source(dest: Path) -> Path:
        return matrix.copy_repo(dest)

    def configure(self, tc: Toolchain, src: Path, build: Path, prefix: Path, defines: dict | None = None,
                  fresh: bool = True, cmake: str | None = None) -> tuple[int, str]:
        if fresh:
            matrix.rmtree(build)
        cmd = [cmake or self.cmake, "-G", self.generator, "-S", str(src), "-B", str(build),
               f"-DCMAKE_PREFIX_PATH={prefix}", "-DCMAKE_BUILD_TYPE=Release", f"-DPython3_EXECUTABLE={self.python}",
               f"-DCMAKE_CXX_COMPILER={tc.cxx}"]
        if self.generator == "Ninja" and self.ninja:
            cmd.append(f"-DCMAKE_MAKE_PROGRAM={self.ninja}")
        for k, v in (defines or {}).items():
            cmd.append(f"-D{k}={v}")
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", env=tc.environ())
        return proc.returncode, proc.stdout + proc.stderr

    def build(self, tc: Toolchain, build: Path, target: str = "semb", extra_env: dict | None = None,
              cmake: str | None = None) -> tuple[int, str]:
        proc = subprocess.run([cmake or self.cmake, "--build", str(build), "--target", target], capture_output=True,
                              text=True, errors="replace", env=tc.environ(extra_env))
        return proc.returncode, proc.stdout + proc.stderr


def semb_exe(build: Path) -> Path:
    for cand in (build / "semb.exe", build / "semb"):
        if cand.is_file():
            return cand
    return build / ("semb.exe" if WINDOWS else "semb")


def objects_under(build: Path, targets: tuple[str, ...] = ("superembedder", "semb")) -> list[Path]:
    out = []
    for t in targets:
        d = build / "CMakeFiles" / f"{t}.dir"
        if d.is_dir():
            out += [p for p in d.rglob("*") if p.suffix in (".o", ".obj")]
    return out


def linked(build: Path) -> list[Path]:
    """Every product library or executable this build directory holds."""
    names = ("semb", "semb.exe", "libsuperembedder.a", "superembedder.lib", "libsuperembedder.so",
             "superembedder.dll")
    return [build / n for n in names if (build / n).exists()]


@dataclass
class Version:
    rc: int
    text: str
    descriptor: dict
    tier: str
    cell: str
    epoch: str
    check: str
    residual_flags: list

    @property
    def digests(self) -> tuple[str, str]:
        return self.descriptor.get("compileFlags", ""), self.descriptor.get("engineFlags", "")


def read_version(build: Path) -> Version:
    exe = semb_exe(build)
    proc = subprocess.run([str(exe), "--version"], capture_output=True, text=True, errors="replace")
    by = {}
    for line in proc.stdout.splitlines():
        for p in version_line.LINES:
            if line.startswith(p):
                by[p.strip()] = line[len(p):]
    d = version_line.fields(by.get("descriptor:", ""))
    cell_line = by.get("cell:", "")
    cell = cell_line.split(" ", 1)[0] if cell_line else ""
    epoch = version_line.fields(cell_line).get("epoch", "")
    check = version_line.fields(by.get("engine:", "")).get("check", "")
    residual = []
    rec = build / "generated" / "compile-flags.json"
    if rec.is_file():
        residual = json.loads(rec.read_text("utf-8")).get("residual", [])
    return Version(proc.returncode, proc.stdout + proc.stderr, d, by.get("tier:", "").strip(), cell, epoch, check,
                   residual)


def epochs(src: Path) -> tuple[str, str]:
    """(member epoch, uncertified epoch), computed here from the identity file's bytes (FORMAT.md sec 4)."""
    identity = (src / IDENTITY).read_bytes()
    return sha256(identity), sha256(b"SEMB-UNCERTIFIED\0" + identity)


def expected_cell(src: Path, v: Version) -> tuple[str, str]:
    """The cell and epoch this script's own matcher gives the build's descriptor and tier over `src`'s list."""
    return version_line.decide(v.descriptor, v.tier, (src / LIST).read_bytes(), (src / IDENTITY).read_bytes())


def certify_locally(src: Path, v: Version, cell_id: str) -> None:
    """A list variant in `src` that also lists this build's own cell, so a leg that must move a build from a cell
    to `uncertified` can be read on a host whose build no committed cell names (every Linux build: the interim
    list holds two Windows cells). The added cell carries a copy of the committed msvc19.33 evidence under its
    own id and one pair with each committed cell, so configure's structural check (C42 (a)/(b)) proves the list.
    On a host whose build a committed cell names, the drivers keep the committed list."""
    doc = json.loads((src / LIST).read_text("utf-8"))
    committed = [b["id"] for b in doc["builds"]]
    proof = doc["pairwiseProofs"][0]
    cell = {"id": cell_id, **{k: v.descriptor[k] for k in DESCRIPTOR_FIELDS}, "cpuTier": v.tier,
            "artifact": doc["builds"][0]["artifact"], "host": doc["builds"][0]["host"], "evidence": EVIDENCE}
    doc["builds"].append(cell)
    run_id = f"c51-local-{cell_id}"
    for other in committed:
        other_run = json.loads((src / EVIDENCE / other / "run.json").read_text("utf-8"))["runId"]
        doc["pairwiseProofs"].append({"a": other, "b": cell_id, "runIds": [other_run, run_id],
                                      "rowDigest": proof["rowDigest"], "tokenIdDigest": proof["tokenIdDigest"]})
    doc["release"] = str(doc.get("release", "")) + " (C51 runtime-leg list variant)"
    (src / LIST).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    dest = src / EVIDENCE / cell_id
    matrix.rmtree(dest)
    shutil.copytree(src / EVIDENCE / committed[0], dest)
    run = json.loads((dest / "run.json").read_text("utf-8"))
    run["cellId"], run["runId"] = cell_id, run_id
    run.pop("buildId", None)
    (dest / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------------------------------------------
# Opens on the synthetic pair
# ---------------------------------------------------------------------------------------------------------------
_PAIR: tuple[str, str] | None = None
_PAIR_ERROR = ""


def synthetic_pair() -> tuple[str, str] | None:
    global _PAIR, _PAIR_ERROR
    if _PAIR is None and not _PAIR_ERROR:
        try:
            import epoch_store_contract  # tests/epoch_store_contract.py: the cached u1 pair
            _PAIR = epoch_store_contract.ensure_synthetic_pair(REPO_ROOT)
        except Exception as exc:  # noqa: BLE001 -- the pair is a prerequisite, reported by name
            _PAIR_ERROR = f"{type(exc).__name__}: {str(exc)[-300:]}"
    return _PAIR


def bake_manifest(build: Path, scratch: Path) -> tuple[dict | None, str]:
    """`semb bake` of one document on the synthetic pair; (the bank manifest, detail). None when it cannot run."""
    pair = synthetic_pair()
    if pair is None:
        return None, f"no synthetic tokenizer pair ({_PAIR_ERROR})"
    scratch.mkdir(parents=True, exist_ok=True)
    corpus = scratch / "c51-one-document.jsonl"
    corpus.write_text('{"id": "d0", "text": "one document"}\n', encoding="utf-8", newline="\n")
    stem = scratch / "c51-bank"
    for suffix in (".semb.json", ".wvbank.json", ".wvbank.bin", ".skipped.json"):
        Path(str(stem) + suffix).unlink(missing_ok=True)
    proc = subprocess.run([str(semb_exe(build)), "bake", str(corpus), "--out", str(stem), "--model", pair[0],
                           "--tokenizer", pair[1]], capture_output=True, text=True, errors="replace")
    manifest = Path(str(stem) + ".semb.json")
    if proc.returncode != 0 or not manifest.is_file():
        return {"__exit__": proc.returncode}, tail(proc.stdout + proc.stderr)
    return json.loads(manifest.read_text("utf-8")), f"exit {proc.returncode}"


def add_common_arguments(ap) -> None:
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--generator", default="Ninja")
    ap.add_argument("--ninja-executable", default="ninja")
    ap.add_argument("--python-executable", default=sys.executable)
    ap.add_argument("--cxx", required=True, help="the tree's own CMAKE_CXX_COMPILER")
    ap.add_argument("--compiler-id", required=True)
    ap.add_argument("--compiler-version", required=True)
    ap.add_argument("--frontend", default="")
    ap.add_argument("--engine-prefix", default="", help="the tree's own engine prefix (SEMB_ENGINE_PREFIX)")
    ap.add_argument("--engine-source", default=os.environ.get("SEMB_TEST_ENGINE_SOURCE", ""),
                    help="git URL or path the pin tool clones the engine from (default: SEMB_TEST_ENGINE_SOURCE, "
                         "then the pin tool's own remote)")
    ap.add_argument("--toolchains-file", default="")
    ap.add_argument("--scratch", required=True)


def setup(args, title: str):
    """(report, me, others, how, engines, product, scratch) for a driver."""
    from pin_superslm import DEFAULT_REMOTE  # noqa: E402 -- tools/pin-superslm, on sys.path via matrix
    report = Report(title)
    me = self_toolchain(args)
    others, how = other_toolchains(args, me)
    scratch = Path(args.scratch).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    # Pins are shared by every C51 driver: <SEMB_C51_SCRATCH>/engines beside each driver's own <name>/ directory.
    engines = Engines(scratch.parent, args.engine_source or DEFAULT_REMOTE,
                      args.cmake_executable, args.ninja_executable,
                      Path(args.engine_prefix).resolve() if args.engine_prefix else None, me)
    product = Product(args.cmake_executable, args.generator, args.ninja_executable, args.python_executable)
    print(f"{title}: this tree's toolchain {me.name} ({me.cxx}); other toolchains {[t.name for t in others]} "
          f"({how}); host {platform.system()} {platform.machine()}", flush=True)
    return report, me, others, how, engines, product, scratch
