"""U3: C11, cost after the verb (te266 sec 4.5 C11, P:4188-4205). MEASUREMENT:
readings for a person, no threshold. Dev box only (Windows, SEMB_BUILD_GPU=ON,
the real artifact); elsewhere MISSING PREREQUISITE, exit 77.

Method (P:4196): --pilot runs every reading over 10 documents first.

--leg tokps    tok/s by length third, on the 239-document corpus and on the FiQA
               slice (--fiqa-corpus; see below), for the CPU at one worker
               (--max-concurrency 1), the CPU at the CLI's default of 8, and the
               GPU. The corpus is split into thirds by each document's token
               count (read from a CPU bake's manifest, per_row_token_counts), and
               each third is baked and timed on its own; tok/s counts forward
               positions (tokens + 1 per row). Plus the long-document band
               (P:4203): the 4,096-token row on each device.
--leg query    query latency on an open handle over 100 FiQA queries
               (--fiqa-queries), CPU and GPU: one `semb query --stdin` session
               with 1 query and one with 101, latency = (t101 - t1) / 100; the
               one-shot `semb query` process end to end on each device (P:4192);
               open time per device (P:4193) = t1 - latency.
--leg device   VRAM after the model map and at the cap row's peak, and the longest
               witness forward (P:4194-4195): u3_gpu_cells_test --cell c11_device
               --positions 32767.

Every reading is appended to build/_u3_logs/c11_<leg>.log as `READING ...` lines.

THE FIQA SLICE: the plan's "80-document FiQA slice (sec 2.2)" was replaced by
the fiqa-long80 cell (D-SLM7873); which population C11 reads is a PENDING
planner decision. This driver reads whatever --fiqa-corpus names and records
its SHA-256 beside every reading.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import u3_cells_check as cells  # noqa: E402

CORPUS = ROOT / "tests" / "fixtures" / "c12b" / "corpus-239.jsonl"
LOG = None


def reading(text: str) -> None:
    line = f"READING {text}"
    print(line, flush=True)
    if LOG:
        LOG.write(line + "\n")
        LOG.flush()


def timed(cmd: list[str], stdin: bytes | None = None, timeout: int = 6 * 3600) -> tuple[float, int, str]:
    t0 = time.perf_counter()
    p = subprocess.run(cmd, cwd=ROOT, input=stdin, capture_output=True, timeout=timeout)
    return time.perf_counter() - t0, p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")[-400:]


def docs(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def write(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def main(argv: list[str]) -> int:
    global LOG
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--leg", required=True, choices=["tokps", "query", "device"])
    ap.add_argument("--real-model", default="")
    ap.add_argument("--real-tokenizer", default="")
    ap.add_argument("--fiqa-corpus", default="")
    ap.add_argument("--fiqa-queries", default="")
    ap.add_argument("--pilot", action="store_true")
    args = ap.parse_args(argv)
    build = Path(args.build_dir).resolve()
    if platform.system() != "Windows":
        return cells.missing(f"C11 {args.leg}: GPU measurement needs Windows and D3D12 (this host is {platform.system()})")
    if cells.cache_value(build, "SEMB_BUILD_GPU").upper() not in ("ON", "TRUE", "1", "YES"):
        return cells.missing(f"C11 {args.leg}: the build tree is not configured with SEMB_BUILD_GPU=ON")
    if not (args.real_model and Path(args.real_model).is_file() and args.real_tokenizer
            and Path(args.real_tokenizer).is_file()):
        return cells.missing(f"C11 {args.leg}: the real artifact (SEMB_C12B_MODEL / SEMB_U1_TOKENIZER) is not configured")
    (build / "_u3_logs").mkdir(parents=True, exist_ok=True)
    LOG = open(build / "_u3_logs" / f"c11_{args.leg}.log", "a", encoding="utf-8")
    base = ["--model", args.real_model, "--tokenizer", args.real_tokenizer]
    r = subprocess.run([args.cmake_executable, "--build", str(build), "--target", "semb", "u3_gpu_cells_test"],
                       capture_output=True, text=True, errors="replace")
    if r.returncode:
        print(f"[FAIL] C11 apparatus\n{(r.stdout + r.stderr)[-1500:]}")
        return 1
    semb = str(cells.find_exe(build, "semb"))
    work = build / "_u3_c11"
    n = 10 if args.pilot else None
    tag = "pilot " if args.pilot else ""
    failed = False

    if args.leg == "tokps":
        corpora = [("corpus239", CORPUS)]
        if args.fiqa_corpus and Path(args.fiqa_corpus).is_file():
            corpora.append(("fiqa", Path(args.fiqa_corpus)))
        else:
            print("[MISSING PREREQUISITE] C11 FiQA slice: --fiqa-corpus not given (PENDING: fiqa-long80, D-SLM7873)")
        for label, path in corpora:
            rows = docs(path)[:n] if n else docs(path)
            sha = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            probe = work / label / "probe"
            t, rc, out = timed([semb, "bake", str(write(work / label / "all.jsonl", rows)), "--out", str(probe),
                                "--max-concurrency", "1", "--device", "cpu", *base])
            if rc:
                print(f"[FAIL] C11 {label} token-count probe: {out}")
                failed = True
                continue
            counts = json.loads(Path(str(probe) + ".semb.json").read_text(encoding="utf-8"))["per_row_token_counts"]
            order = sorted(range(len(rows)), key=lambda i: counts[i])
            k = len(order)
            thirds = [order[: k // 3], order[k // 3: 2 * k // 3], order[2 * k // 3:]]
            for ti, idx in enumerate(thirds):
                sub = write(work / label / f"third{ti}.jsonl", [rows[i] for i in idx])
                positions = sum(counts[i] + 1 for i in idx)
                for dev, mc in (("cpu", "1"), ("cpu", "8"), ("gpu", "1")):
                    t, rc, out = timed([semb, "bake", str(sub), "--out", str(work / label / f"t{ti}_{dev}{mc}"),
                                        "--max-concurrency", mc, "--device", dev, *base])
                    reading(f"{tag}tokps corpus={label} sha={sha} third={ti} docs={len(idx)} positions={positions} "
                            f"device={dev} workers={mc} seconds={t:.2f} tok_per_s={positions / t if t else 0:.2f} "
                            f"exit={rc} (wall time includes one open)")
                    failed |= rc != 0
        long_doc = write(work / "long4096.jsonl", [{"id": "long", "text": "the" + " the" * 4095}])
        for dev, mc in (("cpu", "1"), ("gpu", "1")):
            t, rc, out = timed([semb, "bake", str(long_doc), "--out", str(work / f"long_{dev}"),
                                "--max-concurrency", mc, "--device", dev, *base])
            reading(f"{tag}tokps band=4096 device={dev} seconds={t:.2f} tok_per_s={4097 / t if t else 0:.2f} exit={rc}")
            failed |= rc != 0
    elif args.leg == "query":
        qpath = Path(args.fiqa_queries) if args.fiqa_queries else None
        if not qpath or not qpath.is_file():
            return cells.missing("C11 query: --fiqa-queries (100 FiQA queries, jsonl) not given")
        qs = [d["text"] for d in docs(qpath)][: (10 if args.pilot else 100)]
        stem = work / "qbank"
        if not Path(str(stem) + ".semb.json").is_file():
            timed([semb, "bake", str(CORPUS), "--out", str(stem), "--device", "cpu", *base])
        for dev in ("cpu", "gpu"):
            t1, rc1, _ = timed([semb, "query", "--stdin", str(stem), "--hex", "--device", dev, *base],
                               stdin=(qs[0] + "\n").encode())
            tn, rcn, _ = timed([semb, "query", "--stdin", str(stem), "--hex", "--device", dev, *base],
                               stdin=("\n".join([qs[0], *qs]) + "\n").encode())
            lat = (tn - t1) / len(qs)
            one, rco, _ = timed([semb, "query", str(stem), "--hex", "--device", dev, *base, "--", qs[0]])
            reading(f"{tag}query device={dev} queries={len(qs)} latency_s={lat:.4f} open_s={t1 - lat:.2f} "
                    f"one_shot_process_s={one:.2f} exits={rc1},{rcn},{rco}")
            failed |= bool(rc1 or rcn or rco)
    else:
        gcells = str(cells.find_exe(build, "u3_gpu_cells_test"))
        cmd = [gcells, "--cell", "c11_device", *base, "--scratch", str(work / "device"),
               "--log", str(build / "_u3_logs" / "c11_device.cells.log")]
        if not args.pilot:
            cmd += ["--positions", "32767"]
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=8 * 3600)
        print(p.stdout)
        for line in p.stdout.splitlines():
            if "READING" in line and LOG:
                LOG.write(line + "\n")
        failed |= p.returncode != 0
    print(f"[{'FAIL' if failed else 'PASS'}] C11 {args.leg}: readings {'incomplete' if failed else 'taken'} "
          f"(measurement: read by a person, P:4220)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
