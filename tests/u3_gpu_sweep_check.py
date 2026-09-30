"""U3 red suite: the resumable driver for the two per-site sweeps.

  --binary alloc   tests/u3_gpu_alloc_test.cpp, sec 4.6 row 5(d)'s real-allocation
                   legs (te266 P:4215): --leg count|d1|d2|d3h|d3d|d4|mr_removed.
  --binary c64     tests/u3_c64_gpu_leg_test.cpp, C64's GPU leg (te267 P:3757, J12):
                   --row <verb> --arm a|a2|b.

Both write BEGIN before each armed site and SITE/ARM after it, flushed per line,
to build/_u3_logs/<step>.sweep.log. The dev box's RAM is faulty, so this driver
is built to be killed at any moment: re-running the same ctest reads the log,
skips every site that already has a result, reports a BEGIN with no result as
CRASHED at that site (a termination is a verdict for that k, never the harness
dying), and continues at the next site. d4 runs one fresh process per site, as
the plan requires ("in a fresh process").

Verdict: [PASS] when every graded site passed and none crashed; [FAIL] with the
counts otherwise. OUTSIDE-MAP sites (d3) are listed, not graded.

--commission grades the must-reject population instead (P:4215): run against
the engine at v1.7.1, a leg that reads no non-conforming site is DEAD ([FAIL]);
the reading is printed beside the plan's figures (d1 530 = 50 + 480, d2 120, d4
a permanent loss).

Off Windows, or in a tree without SEMB_BUILD_GPU=ON: MISSING PREREQUISITE, 77.
"""
from __future__ import annotations

import argparse
import functools
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import u3_cells_check as cells  # noqa: E402

print = functools.partial(print, flush=True)  # noqa: A001 -- every line reaches ctest as written

TARGETS = {"alloc": "u3_gpu_alloc_test", "c64": "u3_c64_gpu_leg_test"}
PLAN_FIGURES = {"d1": "530 (50 + 480)", "d2": "120", "d4": "a permanent loss"}
RESULT = re.compile(r"^(SITE|ARM) .*?\bk=(\d+)\b.*\b(PASS|FAIL|OUTSIDE-MAP)\s*$")
BEGIN = re.compile(r"^BEGIN .*?\bk=(\d+)\b")
END = re.compile(r"^END .*?\bk=(\d+)\b")


def read_state(log: Path) -> tuple[dict[int, str], set[int], int | None, list[str]]:
    results: dict[int, str] = {}
    begun: set[int] = set()
    end_k: int | None = None
    lines: list[str] = []
    if log.is_file():
        for line in log.read_text(errors="replace").splitlines():
            m = RESULT.match(line)
            if m:
                results[int(m.group(2))] = m.group(3)
                lines.append(line)
                continue
            m = BEGIN.match(line)
            if m:
                begun.add(int(m.group(1)))
                continue
            m = END.match(line)
            if m:
                end_k = int(m.group(1))
    crashed = {k for k in begun if k not in results and (end_k is None or k < end_k)}
    for k in crashed:
        results[k] = "CRASHED"
    return results, crashed, end_k, lines


class Streamed:
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def run_streamed(cmd: list[str]) -> Streamed:
    """Runs the sweep binary with its output passed through line by line as it is written, flushed, so
    ctest (and the dev box's console) sees each site as it lands rather than the whole sweep at exit (the
    box read nothing for 88 minutes of a C64 sweep). stderr is merged into stdout; the tail is kept for
    the failure messages below."""
    tail: list[str] = []
    with subprocess.Popen(cmd, cwd=cells.REPO_ROOT, text=True, errors="replace", stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, bufsize=1) as p:
        assert p.stdout is not None
        for line in p.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            tail.append(line)
            if len(tail) > 400:
                del tail[:200]
        rc = p.wait()
    return Streamed(rc, "".join(tail), "")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--binary", choices=sorted(TARGETS), required=True)
    ap.add_argument("--leg", default="d1")
    ap.add_argument("--row", default="semb_encode")
    ap.add_argument("--arm", default="a")
    ap.add_argument("--artifact", choices=["real", "u1"], default="real")
    ap.add_argument("--real-model", default="")
    ap.add_argument("--real-tokenizer", default="")
    ap.add_argument("--commission", action="store_true")
    ap.add_argument("--max-sites", type=int, default=100000)
    args = ap.parse_args(argv)
    build_dir = Path(args.build_dir).resolve()
    target = TARGETS[args.binary]
    step = (f"alloc_{args.leg}" if args.binary == "alloc" else f"c64gpu_{args.row}_{args.arm}") + (
        "_commission" if args.commission else "")

    import platform
    if platform.system() != "Windows":
        return cells.missing(f"{step}: GPU execution needs Windows and D3D12 (this host is {platform.system()})")
    if cells.cache_value(build_dir, "SEMB_BUILD_GPU").upper() not in ("ON", "TRUE", "1", "YES"):
        return cells.missing(f"{step}: the build tree is not configured with SEMB_BUILD_GPU=ON")
    if args.artifact == "real":
        if not (args.real_model and Path(args.real_model).is_file() and args.real_tokenizer
                and Path(args.real_tokenizer).is_file()):
            return cells.missing(f"{step}: the real artifact (SEMB_C12B_MODEL / SEMB_U1_TOKENIZER) is not configured")
        art = ["--model", args.real_model, "--tokenizer", args.real_tokenizer]
    else:
        d = cells.ensure_pair("u1")
        art = ["--model", str(d / "u1_pair_model.sslm"), "--tokenizer", str(d / "u1_pair_tokenizer.sslm")]

    build = subprocess.run([args.cmake_executable, "--build", str(build_dir), "--target", target],
                           cwd=cells.REPO_ROOT, capture_output=True, text=True, errors="replace")
    if build.returncode:
        syms = cells.undefined_symbols(build.stdout + build.stderr)
        if syms:
            print(f"[RED-UNIMPLEMENTED] {target}: link fails on undefined symbol(s): {', '.join(syms)}")
        else:
            print(f"[FAIL] {target} build failed\n{(build.stdout + build.stderr)[-4000:]}")
        return 1
    exe = cells.find_exe(build_dir, target)
    if exe is None:
        print(f"[FAIL] {target} is absent after a successful build")
        return 1

    log_dir = build_dir / "_u3_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / f"{step}.sweep.log"
    one_shot = args.binary == "alloc" and args.leg in ("count", "mr_removed")
    fresh_per_site = args.binary == "alloc" and args.leg == "d4"
    launched = 0
    while True:
        results, crashed, end_k, _ = read_state(log)
        if end_k is not None:
            break
        done = max(results) if results else 0
        nxt = done + 1
        if launched >= args.max_sites:
            print(f"[NOTE] {step}: stopped after {launched} launches; re-run this step to resume at k={nxt}")
            return 1
        if args.binary == "alloc":
            cmd = [str(exe), "--leg", args.leg, *art, "--log", str(log)]
            cmd += ["--site", str(nxt)] if fresh_per_site else ["--first", str(nxt)]
        else:
            cmd = [str(exe), "--row", args.row, "--arm", args.arm, *art, "--first", str(nxt), "--log", str(log)]
        launched += 1
        proc = run_streamed(cmd)
        if proc.returncode == 77 and "MISSING PREREQUISITE" in proc.stdout:
            return 77
        if one_shot:
            return proc.returncode
        after, _, end_after, _ = read_state(log)
        if end_after is None and (max(after) if after else 0) <= done:
            print(f"[FAIL] {step}: the binary made no progress at k={nxt} (exit {proc.returncode})")
            print(proc.stdout[-3000:] + proc.stderr[-2000:])
            return 1
        if not fresh_per_site and end_after is None and proc.returncode not in (0, 1):
            print(f"[NOTE] {step}: process ended with {proc.returncode:#x}; resuming after the crashed site")

    results, crashed, end_k, lines = read_state(log)
    graded = {k: v for k, v in results.items() if v != "OUTSIDE-MAP"}
    fails = sorted(k for k, v in graded.items() if v == "FAIL")
    outside = sorted(k for k, v in results.items() if v == "OUTSIDE-MAP")
    summary = (f"{len(graded)} graded site(s): {sum(v == 'PASS' for v in graded.values())} pass, {len(fails)} fail, "
               f"{len(crashed)} crashed" + (f"; {len(outside)} outside the model map (not graded)" if outside else ""))
    if args.commission:
        nonconf = len(fails) + len(crashed)
        ok = nonconf > 0
        print(f"[{'PASS' if ok else 'FAIL'}] {step} commissioning at the must-reject engine: {nonconf} non-conforming "
              f"site(s) read (the plan's figure: {PLAN_FIGURES.get(args.leg, '-')}); "
              f"{'the leg is alive' if ok else 'DEAD: it passes on the must-reject population'}")
        return 0 if ok else 1
    ok = bool(graded) and not fails and not crashed
    first_fail = next((ln for ln in lines if ln.endswith("FAIL")), "")
    print(f"[{'PASS' if ok else 'FAIL'}] {step}: {summary}"
          + (f"; crashed at k={sorted(crashed)[:10]}" if crashed else "")
          + (f"; first failure: {first_fail}" if first_fail else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
