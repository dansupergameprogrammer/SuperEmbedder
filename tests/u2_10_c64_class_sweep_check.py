"""U2 cloud build: U2-10's C64, the class sweep -- build and run the sweep
executable over every row of tools/c_boundary_table.json and every driver the
table lists for it, and print (and optionally record) the per-row, per-driver,
per-arm reading.

Expected statuses come from item 3 in the executable's own source (its
--print-expected); this script refuses a table row whose recorded family or
statuses differ from that source, and never takes an expectation from the
table. `--write-table` fills the table's `c64_pre_build` column from this run
(the pre-build reading, te267 U2-10 C64).

Red on today's library by the plan's predictions (C64, "Red today"); on GCC
the cl.exe-only (c) reds do not apply.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TABLE = REPO_ROOT / "tools" / "c_boundary_table.json"
TARGET = "u2_10_c64_class_sweep_test"
# Short drivers on a handle run at max_concurrency 1 and 2 (C64 setup).
HANDLE_ROWS = {
    "semb_encoder_open", "semb_encoder_close", "semb_encoder_dims", "semb_encode", "semb_encode_batch",
    "semb_query_open", "semb_query_encode", "semb_query_close", "semb_fingerprint_of", "semb_bake_to_path",
    "semb_wb_digest", "semb_wq_digest", "semb_interim_encoder_open_from_memory", "semb_interim_encode_batch_ps_n",
    "semb_interim_release_workspaces",
}


def find_exe(build_dir: Path) -> Path | None:
    for c in (build_dir / "tests" / TARGET, build_dir / "tests" / (TARGET + ".exe")):
        if c.exists():
            return c
    return None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--rows", default="")
    ap.add_argument("--write-table", action="store_true")
    ap.add_argument("--json-out", default="")
    ap.add_argument("--full", action="store_true",
                    help="grade every k (the verdict run); default samples k to --budget seconds per driver")
    ap.add_argument("--budget", type=float, default=60.0)
    args = ap.parse_args(argv)
    build_dir = Path(args.build_dir)
    pair_dir = REPO_ROOT / "build" / "_scratch" / "u2_9_min_pair"
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import u2_9_workspace_cells_check as u29  # noqa: E402
    try:
        u29.ensure_pair(pair_dir)
    except Exception as ex:  # noqa: BLE001
        print(f"[FAIL] minimal cap-5,000 pair could not be minted: {ex}")
        return 1
    b = subprocess.run([args.cmake_executable, "--build", str(build_dir), "--target", TARGET], cwd=REPO_ROOT,
                       capture_output=True, text=True, errors="replace")
    if b.returncode:
        print(f"[FAIL] {TARGET} build failed\n{(b.stdout + b.stderr)[-3000:]}")
        return 1
    exe = find_exe(build_dir)
    if exe is None:
        print(f"[FAIL] {TARGET} absent after build")
        return 1
    table = json.loads(TABLE.read_text(encoding="utf-8"))
    exp = {}
    for line in subprocess.run([str(exe), "--print-expected"], capture_output=True, text=True).stdout.splitlines():
        _, row, fam, alloc, catch = line.split()
        exp[row] = (fam, alloc, catch)
    failures = 0
    names = [r["name"] for r in table["rows"]]
    if sorted(names) != sorted(exp):
        print(f"[FAIL] table rows and the sweep's item-3 rows differ: table-only {sorted(set(names) - set(exp))}, "
              f"source-only {sorted(set(exp) - set(names))}")
        failures += 1
    for r in table["rows"]:
        fam, alloc, catch = exp.get(r["name"], ("?", "?", "?"))
        if r["disposition"] == "leaf":
            if fam != "leaf":
                print(f"[FAIL] {r['name']}: table says leaf, item 3 names family {fam}")
                failures += 1
            continue
        if (r["status_family"], r["allocation_status"], r["catch_all_status"]) != (fam, alloc, catch):
            print(f"[FAIL] {r['name']}: table statuses {r['status_family']}/{r['allocation_status']}/"
                  f"{r['catch_all_status']} differ from item 3's {fam}/{alloc}/{catch}")
            failures += 1
    want_rows = set(args.rows.split(",")) if args.rows else None
    scratch = build_dir / "_scratch" / "c64"
    scratch.mkdir(parents=True, exist_ok=True)
    results: dict = {}
    t_all = time.time()
    for r in table["rows"]:
        name = r["name"]
        if want_rows and name not in want_rows:
            continue
        results[name] = {}
        for drv in r["c64_drivers"]:
            mcs = [1, 2] if drv == "short" and name in HANDLE_ROWS else [1]
            for mc in mcs:
                key = drv if len(mcs) == 1 else f"{drv}@mc{mc}"
                base = [str(exe), "--model", str(pair_dir / "u1_pair_model.sslm"),
                        "--tokenizer", str(pair_dir / "u1_pair_tokenizer.sslm"),
                        "--scratch", str(scratch), "--row", name, "--driver", drv, "--mc", str(mc)]
                # The count pass: K, and the cost of one warm-up plus one counted call.
                t0 = time.time()
                cnt = subprocess.run(base + ["--count-only"], cwd=REPO_ROOT, capture_output=True, text=True,
                                     errors="replace", timeout=3600)
                t_count = time.time() - t0
                m = re.search(r"COUNT \S+ \S+ \d+ K=(\d+)", cnt.stdout) or re.search(r"leaf K=(\d+)", cnt.stdout)
                k_count = int(m.group(1)) if m else 0
                stride = 1
                per_k = 0.0
                if not args.full and k_count > 0:
                    pk = re.search(r"PERK ([0-9.]+)", cnt.stdout)
                    per_k = max(float(pk.group(1)) if pk else t_count / 2.0, 0.0005)
                    stride = max(1, int(-(-3 * k_count * per_k // args.budget)))
                t0 = time.time()
                run = subprocess.run(base + ["--k-stride", str(stride)], cwd=REPO_ROOT, capture_output=True,
                                     text=True, errors="replace", timeout=7200)
                secs = round(time.time() - t0, 1)
                entry: dict = {"seconds": secs}
                if stride > 1:
                    entry["sampled"] = (f"every {stride}th k and K (not the verdict: full sweep est. "
                                        f"{round(3 * k_count * per_k / 60, 1)} min)")
                if "NO-DRIVER" in run.stdout:
                    entry["error"] = "no driver in the sweep for this table driver"
                for line in run.stdout.splitlines():
                    m = re.match(r"SUMMARY \S+ \S+ \d+ leaf K=(\d+) (\w+)", line)
                    if m:
                        entry["K"] = int(m.group(1))
                        entry["leaf"] = "K=0" if m.group(2) == "pass" else "red: K>0"
                        continue
                    m = re.match(r"SUMMARY \S+ \S+ \d+ (\w+) K=(\d+) pass=(\d+) fail=(\d+) first_fail_k=(\d+) "
                                 r"first_fail=(.*)", line)
                    if m:
                        arm, K, p, f, fk, ff = m.groups()
                        entry["K"] = int(K)
                        graded = int(p) + int(f)
                        if int(K) == 0:
                            entry[arm] = "K=0 (graded by reading)"
                        elif int(f) == 0:
                            entry[arm] = f"green {p} of {graded} graded"
                        else:
                            entry[arm] = f"red {f} of {graded} graded (first k={fk}: {ff.strip()[:160]})"
                    elif line.startswith("TERMINATED"):
                        entry.setdefault("terminated", []).append(line)
                red = [k for k, v in entry.items() if isinstance(v, str) and v.startswith("red")] or \
                    (["error"] if "error" in entry else []) or (["terminated"] if "terminated" in entry else [])
                if red or run.returncode:
                    failures += 1
                results[name][key] = entry
                print(f"{'[FAIL]' if red or run.returncode else '[PASS]'} C64 {name} {key}: " +
                      "; ".join(f"{k}={v}" for k, v in entry.items() if k != "terminated") +
                      (f" terminated={entry['terminated'][:3]}" if "terminated" in entry else ""))
                sys.stdout.flush()
    print(f"C64 sweep wall time {round(time.time() - t_all, 1)} s")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, indent=1), encoding="utf-8")
    if args.write_table:
        for r in table["rows"]:
            if r["name"] in results:
                r["c64_pre_build"] = results[r["name"]]
        TABLE.write_text(json.dumps(table, indent=2) + "\n", encoding="utf-8")
    print(f"TOTAL fail={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
