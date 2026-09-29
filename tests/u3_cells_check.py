"""U3 red suite: build and run one U3 C++ cell binary (te266 sec 4.5-4.6).

One ctest per invocation. The driver:

  1. For a GPU-execution binary (--gpu): requires Windows and a build tree
     configured with SEMB_BUILD_GPU=ON; otherwise prints MISSING PREREQUISITE
     and exits 77 (ctest SKIP_RETURN_CODE), never PASS.
  2. Mints the synthetic fixtures the binary reads when absent (the U1 pair,
     U2-9's minimal cap-5,000 pair, row 5(a)'s guard pair) under
     build/_scratch/ with the repository's own regenerators.
  3. Builds the EXCLUDE_FROM_ALL target. A link failure on undefined symbols
     is the suite's red: it prints [RED-UNIMPLEMENTED] naming each undefined
     symbol (the builder's items) and exits 1. Any other build failure is
     [FAIL].
  4. Runs the binary with the fixture arguments, appending every output line
     to build/_u3_logs/<log name>.log as it arrives (the dev box can crash;
     the log survives up to the last line), and exits with the binary's code
     (77 passes through; any [FAIL] or [RED-UNIMPLEMENTED] line is exit 1).

USAGE:
  python tests/u3_cells_check.py --build-dir <b> --cmake-executable <cmake> --target <t>
      [--gpu] [--fixtures u1,min5k,guard|guardmain] [--real-model <m> --real-tokenizer <t>]
      [--log-name <name>] [-- <extra args passed to the binary>]
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
SCRATCH = REPO_ROOT / "build" / "_scratch"

PAIRS = {
    # The U1 pair, minted into U3's own directory: build/_scratch/u1_pair belongs to
    # u1_raw_text_cells_check's fixture (semb_u1_pair), and a second writer would race it.
    "u1": ("u3_u1_pair", "regenerate_tokenizer_pair_fixture.py"),
    "min5k": ("u2_9_min_pair", "regenerate_u2_9_minimal_cap5000_pair_fixture.py"),
    "guard": ("u3_guard_pair", "regenerate_u3_guard_pair_fixture.py"),
    "guardmain": ("u3_guard_pair", "regenerate_u3_guard_pair_fixture.py"),
}
PAIR_ARGS = {
    "u1": ("--model", "--tokenizer"),
    "min5k": ("--model5k", "--tokenizer5k"),
    "guard": ("--guard-model", None),
    "guardmain": ("--model", "--tokenizer"),  # the guard pair as the binary's main pair
}

UNDEFINED = [
    re.compile(r"undefined reference to [`']([^'`]+)'"),
    re.compile(r"unresolved external symbol \"?(?:[^\"]*?)\b(\w+)\"? referenced"),
    re.compile(r"unresolved external symbol (\w+)"),
    re.compile(r"undefined symbol: (\S+)"),
]


def missing(why: str) -> int:
    print(f"MISSING PREREQUISITE: {why}")
    return 77


def cache_value(build_dir: Path, name: str) -> str:
    cache = build_dir / "CMakeCache.txt"
    if not cache.is_file():
        return ""
    for line in cache.read_text(errors="replace").splitlines():
        if line.startswith(name + ":"):
            return line.split("=", 1)[1].strip()
    return ""


def ensure_pair(key: str) -> Path:
    sub, script = PAIRS[key]
    out = SCRATCH / sub
    if (out / "u1_pair_model.sslm").is_file() and (out / "u1_pair_tokenizer.sslm").is_file():
        return out
    subprocess.run([sys.executable, str(FIXTURES / script), "--lock", "superslm.lock", "--out-dir", str(out)],
                   cwd=REPO_ROOT, check=True, timeout=1800)
    return out


def find_exe(build_dir: Path, target: str) -> Path | None:
    for name in (target + ".exe", target):
        for sub in ("tests", ""):
            cand = build_dir / sub / name if sub else build_dir / name
            if cand.is_file():
                return cand
    hits = [h for h in build_dir.rglob(target + "*") if h.is_file() and h.suffix in ("", ".exe") and h.stem == target]
    return hits[0] if hits else None


def undefined_symbols(text: str) -> list[str]:
    out: list[str] = []
    for rx in UNDEFINED:
        for m in rx.finditer(text):
            sym = m.group(1)
            if sym not in out:
                out.append(sym)
    return out


def main(argv: list[str]) -> int:
    extra: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, extra = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--gpu", action="store_true", help="a GPU-execution binary: Windows and SEMB_BUILD_GPU=ON only")
    ap.add_argument("--fixtures", default="u1")
    ap.add_argument("--real-model", default="")
    ap.add_argument("--real-tokenizer", default="")
    ap.add_argument("--need-real", action="store_true", help="the cell runs on the real artifact")
    ap.add_argument("--log-name", default="")
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args(argv)
    build_dir = Path(args.build_dir).resolve()
    log_dir = build_dir / "_u3_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_name = args.log_name or args.target

    if args.gpu:
        if platform.system() != "Windows":
            return missing(f"{args.target}: GPU execution needs Windows and D3D12 (this host is {platform.system()})")
        if cache_value(build_dir, "SEMB_BUILD_GPU").upper() not in ("ON", "TRUE", "1", "YES"):
            return missing(f"{args.target}: the build tree is not configured with SEMB_BUILD_GPU=ON")
    if args.need_real and not (args.real_model and Path(args.real_model).is_file()
                               and args.real_tokenizer and Path(args.real_tokenizer).is_file()):
        return missing(f"{log_name}: the real artifact (SEMB_C12B_MODEL / SEMB_U1_TOKENIZER) is not configured")

    cmd_args: list[str] = []
    try:
        for key in [k for k in args.fixtures.split(",") if k]:
            d = ensure_pair(key)
            m_flag, t_flag = PAIR_ARGS[key]
            cmd_args += [m_flag, str(d / "u1_pair_model.sslm")]
            if t_flag:
                cmd_args += [t_flag, str(d / "u1_pair_tokenizer.sslm")]
    except Exception as ex:  # noqa: BLE001
        print(f"[FAIL] a fixture could not be minted: {type(ex).__name__}: {ex}")
        return 1
    if args.need_real:
        cmd_args += ["--model", args.real_model, "--tokenizer", args.real_tokenizer]

    build = subprocess.run([args.cmake_executable, "--build", str(build_dir), "--target", args.target],
                           cwd=REPO_ROOT, capture_output=True, text=True, errors="replace")
    if build.returncode:
        text = build.stdout + build.stderr
        syms = undefined_symbols(text)
        if syms:
            print(f"[RED-UNIMPLEMENTED] {args.target}: link fails on {len(syms)} undefined symbol(s), "
                  f"the builder's items: {', '.join(syms)}")
            return 1
        if re.search(r"(unknown target|No rule to make target|ninja: error: unknown target)", text):
            print(f"[RED-UNIMPLEMENTED] {args.target}: the target is not defined in this build tree")
            return 1
        print(f"[FAIL] {args.target} build failed")
        print(text[-4000:])
        return 1
    exe = find_exe(build_dir, args.target)
    if exe is None:
        print(f"[FAIL] {args.target} is absent after a successful build")
        return 1

    cmd = [str(exe), *cmd_args, *extra, "--log", str(log_dir / f"{log_name}.cells.log")]
    red_or_fail = False
    with open(log_dir / f"{log_name}.log", "a", encoding="utf-8", errors="replace") as log:
        log.write(f"=== {' '.join(cmd)}\n")
        log.flush()
        proc = subprocess.Popen(cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", env=os.environ.copy())
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            log.write(line)
            log.flush()
            if line.startswith("[FAIL]") or line.startswith("[RED-UNIMPLEMENTED]"):
                red_or_fail = True
        try:
            rc = proc.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            print(f"[FAIL] {args.target}: timed out after {args.timeout} s")
            return 1
    if rc == 77 and not red_or_fail:
        return 77
    if rc != 0 or red_or_fail:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
