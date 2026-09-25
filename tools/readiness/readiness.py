"""U2-4's readiness reading tool (C20): runs `semb` and reads the process.

It takes the five readings plan U2-4 names, each written with its cell
(device, tier, artifact, corpus, cache state). The readings are published
measured values, never a build-failing guard (D-SLM7251), so this tool grades
nothing: it exits non-zero only when a reading could not be taken.

  1. warm time-to-ready   `semb query --stdin <bank>` spawned with its first
                          query already written; the reading is spawn -> that
                          query's result line (the encoder open, the checked
                          bank open, and one query). One discarded warm-up run,
                          then --warm-runs measured runs; the median is the
                          reading and every run is recorded.
  2. cold time-to-ready   the same single measurement with no warm-up and
                          nothing run before it (--cold). The cache state is
                          the operator's: take it as the first run after a
                          reboot, with --bank naming a bank baked before the
                          reboot. The host's uptime is recorded beside it.
  3. RSS at open          a session is spawned and nothing is written. When
                          the process has used no CPU for --idle-window
                          seconds it is blocked reading its first query, so the
                          encoder and bank opens have returned and no encode
                          has run: the peak working set and peak private bytes
                          read then are the peak across the open (Windows'
                          peak counters are cumulative from process start, so
                          they must be read here, before any encode), and the
                          working set and private bytes read --steady-delay
                          seconds later are the steady footprint with the
                          handle open. One query is then written and must be
                          answered, proving the handle was serviceable.
  4. median query         one `--stdin` session over C5's 239 query texts
                          (tests/fixtures/c12b/corpus-239.jsonl), each line
                          written only after the previous result arrived,
                          the first only once the open has returned (the
                          idle test of reading 3); each query's wall-clock is
                          write -> result line.
  5. span curve           for each of --span-tokens (default 256, 1024, 4096)
                          one document of exactly that many composed tokens,
                          checked against the bake manifest's
                          per_row_token_counts (so the document runs N + 1
                          positions with its end token). `semb bake` of that
                          one-document corpus minus the median of
                          --span-baseline-runs bakes of a one-unit document is
                          the encode time; tokens / encode time is the rate.
                          The document is --span-lead followed by
                          --span-unit repeated; the unit count is solved from
                          two one-document calibration bakes and every
                          measured bake is checked to hit N exactly.

What it needs on the box (Windows is the target):
  * Python 3.9+ (standard library only; the counters are read through ctypes
    from kernel32's K32GetProcessMemoryInfo, GetProcessTimes and
    GetTickCount64).
  * The member's `semb.exe` (--semb), the real model and tokenizer (--model,
    --tokenizer), and, for --cold, a bank of corpus-239 baked by that same
    binary before the reboot (--bank). Without --bank, the tool bakes one first
    (which is why --cold refuses to run without it).
  * Run from the repository root or pass --corpus. U2-9 must have landed, so
    reading 3 measures the footprint that ships (plan U2-4, TE-403).
  * The cell string (--cell, e.g. msvc19.33-auto@avx2) is recorded verbatim;
    `semb --version`'s output is recorded beside it when the binary has one.

On Linux the same code runs for a smoke of the mechanism; its memory fields
are /proc/<pid>/status's VmHWM, VmRSS and RssAnon (named as such in the
output), which are not the Windows counters the published readings use.

Output: one [READING] line per reading on stdout, and --out's readiness.json.
Exit codes: 0 every requested reading taken; 1 any reading could not be taken.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import queue
import shutil
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = ROOT / "tests" / "fixtures" / "c12b" / "corpus-239.jsonl"
IS_WINDOWS = os.name == "nt"


# --- process counters ------------------------------------------------------

if IS_WINDOWS:
    from ctypes import wintypes

    class _PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t)]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
    _kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
    _kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    _kernel32.GetProcessTimes.restype = wintypes.BOOL
    _kernel32.GetTickCount64.restype = ctypes.c_ulonglong


def memory(proc: subprocess.Popen) -> dict[str, int]:
    """The process's memory counters, in bytes, under their own platform names."""
    if IS_WINDOWS:
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        if not _kernel32.K32GetProcessMemoryInfo(int(proc._handle), ctypes.byref(pmc), pmc.cb):  # noqa: SLF001
            raise OSError(ctypes.get_last_error(), "K32GetProcessMemoryInfo failed")
        return {"PeakWorkingSetSize": pmc.PeakWorkingSetSize, "WorkingSetSize": pmc.WorkingSetSize,
                "PeakPagefileUsage": pmc.PeakPagefileUsage, "PrivateUsage": pmc.PrivateUsage}
    fields = {}
    for line in Path(f"/proc/{proc.pid}/status").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in ("VmHWM", "VmRSS", "RssAnon"):
            fields[key] = int(value.split()[0]) * 1024
    return fields


def cpu_seconds(proc: subprocess.Popen) -> float:
    if IS_WINDOWS:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not _kernel32.GetProcessTimes(int(proc._handle), *[ctypes.byref(t) for t in times]):  # noqa: SLF001
            raise OSError(ctypes.get_last_error(), "GetProcessTimes failed")
        kernel, user = times[2], times[3]
        return ((kernel.dwHighDateTime << 32 | kernel.dwLowDateTime) +
                (user.dwHighDateTime << 32 | user.dwLowDateTime)) / 1e7
    stat = Path(f"/proc/{proc.pid}/stat").read_text()
    parts = stat[stat.rindex(")") + 2:].split()
    return (int(parts[11]) + int(parts[12])) / os.sysconf("SC_CLK_TCK")


def uptime_seconds() -> float:
    if IS_WINDOWS:
        return _kernel32.GetTickCount64() / 1000.0
    return float(Path("/proc/uptime").read_text().split()[0])


# --- a semb query session --------------------------------------------------

class Session:
    """`semb query --stdin`, stdout and stderr read on their own threads with arrival times."""

    def __init__(self, semb: Path, bank: Path, model: str, tokenizer: str, first: str | None = None):
        self.lines: queue.Queue[tuple[float, bytes]] = queue.Queue()
        self.stderr: list[tuple[float, str]] = []
        self.started = time.perf_counter()
        self.proc = subprocess.Popen([str(semb), "query", "--stdin", str(bank), "--model", model,
                                      "--tokenizer", tokenizer],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if first is not None:
            self.write(first)
        threading.Thread(target=self._read_out, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()

    def _read_out(self) -> None:
        for line in iter(self.proc.stdout.readline, b""):
            self.lines.put((time.perf_counter(), line))
        self.lines.put((time.perf_counter(), b""))

    def _read_err(self) -> None:
        for line in iter(self.proc.stderr.readline, b""):
            self.stderr.append((time.perf_counter() - self.started, line.decode("utf-8", "replace").rstrip()))

    def write(self, text: str) -> float:
        # Bytes, LF only: the CLI's line ends at LF and a CR is text (F19).
        self.proc.stdin.write(text.encode("utf-8") + b"\n")
        self.proc.stdin.flush()
        return time.perf_counter()

    def result(self, timeout: float) -> tuple[float, str]:
        at, line = self.lines.get(timeout=timeout)
        if not line:
            raise RuntimeError(f"semb exited before answering (exit {self.proc.wait()}): "
                               f"{[s for _, s in self.stderr][-3:]}")
        return at, line.decode("utf-8", "replace").rstrip("\n")

    def close(self, timeout: float = 120.0) -> int:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            return self.proc.wait()


# --- readings ----------------------------------------------------------------

def time_to_ready(args, bank: Path, text: str) -> dict:
    session = Session(args.semb, bank, args.model, args.tokenizer, first=text)
    at, line = session.result(args.timeout)
    code = session.close()
    if code != 0 or not line.startswith("VECTOR_HEX="):
        raise RuntimeError(f"time-to-ready session exited {code}, first line {line[:40]!r}")
    preflight = next((t for t, s in session.stderr if s.startswith("preflight:")), None)
    return {"seconds": at - session.started, "preflight_line_at_seconds": preflight}


def wait_open(args, session: Session) -> float:
    """Block until the process has used no CPU for --idle-window seconds with nothing written
    to it: it is then waiting on its first query line, so its opens have returned."""
    last_cpu, quiet_since = cpu_seconds(session.proc), time.perf_counter()
    deadline = session.started + args.timeout
    while True:
        time.sleep(0.05)
        if session.proc.poll() is not None:
            raise RuntimeError(f"semb exited during the open: {[s for _, s in session.stderr][-3:]}")
        now, cpu = time.perf_counter(), cpu_seconds(session.proc)
        if cpu != last_cpu:
            last_cpu, quiet_since = cpu, now
        elif now - quiet_since >= args.idle_window:
            return last_cpu
        if now > deadline:
            raise RuntimeError("the process never went idle before the timeout")


def rss_at_open(args, bank: Path, text: str) -> dict:
    session = Session(args.semb, bank, args.model, args.tokenizer)
    last_cpu = wait_open(args, session)
    at_open = memory(session.proc)
    idle_at = time.perf_counter() - session.started
    time.sleep(args.steady_delay)
    steady = memory(session.proc)
    if not session.lines.empty():
        raise RuntimeError("semb wrote output before any query was written")
    session.write(text)
    _, line = session.result(args.timeout)
    code = session.close()
    if code != 0 or not line.startswith("VECTOR_HEX="):
        raise RuntimeError(f"the handle did not serve the confirming query (exit {code})")
    return {"idle_detected_at_seconds": idle_at, "idle_window_seconds": args.idle_window,
            "cpu_seconds_at_idle": last_cpu, "counters_as_open_returns": at_open,
            "counters_steady_after_seconds": args.steady_delay, "counters_steady": steady}


def query_median(args, bank: Path, texts: list[str]) -> dict:
    session = Session(args.semb, bank, args.model, args.tokenizer)
    wait_open(args, session)  # so no query's wall-clock carries the open
    walls = []
    for text in texts:
        sent = session.write(text)
        at, line = session.result(args.timeout)
        if not line.startswith("VECTOR_HEX="):
            raise RuntimeError(f"unexpected query output {line[:40]!r}")
        walls.append(at - sent)
    code = session.close()
    if code != 0:
        raise RuntimeError(f"the session exited {code}")
    return {"queries": len(walls), "median_seconds": statistics.median(walls),
            "min_seconds": min(walls), "max_seconds": max(walls), "per_query_seconds": walls}


def bake_one(args, scratch: Path, name: str, text: str) -> tuple[float, int]:
    corpus = scratch / f"{name}.jsonl"
    corpus.write_bytes((json.dumps({"id": name, "text": text}) + "\n").encode("utf-8"))
    stem = scratch / name
    started = time.perf_counter()
    done = subprocess.run([str(args.semb), "bake", str(corpus), "--out", str(stem), "--model", args.model,
                           "--tokenizer", args.tokenizer, "--max-concurrency", "1"],
                          capture_output=True, timeout=args.timeout)
    seconds = time.perf_counter() - started
    if done.returncode:
        raise RuntimeError(f"semb bake of {name} exited {done.returncode}: "
                           f"{(done.stdout + done.stderr).decode('utf-8', 'replace')[-300:]}")
    manifest = json.loads(Path(str(stem) + ".semb.json").read_text(encoding="utf-8"))
    return seconds, int(manifest["per_row_token_counts"][0])


def span_curve(args, scratch: Path) -> dict:
    def document(units: int) -> str:
        return args.span_lead + args.span_unit * (units - 1)

    t_one, tokens_one = bake_one(args, scratch, "span-calibrate-1", document(1))
    _, tokens_nine = bake_one(args, scratch, "span-calibrate-9", document(9))
    per_unit, rem = divmod(tokens_nine - tokens_one, 8)
    if per_unit <= 0 or rem:
        raise RuntimeError(f"the span unit is not a whole number of tokens ({tokens_one} for 1 unit, "
                           f"{tokens_nine} for 9); choose another --span-unit")
    baseline = [t_one] + [bake_one(args, scratch, f"span-baseline-{i}", document(1))[0]
                          for i in range(1, args.span_baseline_runs)]
    base = statistics.median(baseline)
    points = []
    for target in args.span_tokens:
        units, rem = divmod(target - tokens_one, per_unit)
        if rem or units < 0:
            raise RuntimeError(f"{target} tokens is not reachable with this unit ({tokens_one} + k x {per_unit})")
        seconds, tokens = bake_one(args, scratch, f"span-{target}", document(units + 1))
        if tokens != target:
            raise RuntimeError(f"the {target}-token document tokenized to {tokens}; the unit is not additive")
        encode = seconds - base
        points.append({"tokens": tokens, "positions": tokens + 1, "bake_seconds": seconds,
                       "encode_seconds": encode, "tokens_per_second": tokens / encode if encode > 0 else None,
                       "seconds_per_token": encode / tokens})
    return {"method": "one-document semb bake minus the median one-unit-document bake",
            "baseline_bake_seconds": baseline, "baseline_tokens": tokens_one,
            "span_lead": args.span_lead, "span_unit": args.span_unit, "points": points}


# --- driver ------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--semb", type=Path, required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--tokenizer", required=True)
    ap.add_argument("--cell", required=True, help="the member cell the readings are for, e.g. msvc19.33-auto@avx2")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--bank", type=Path, default=None, help="stem of a corpus-239 bank baked by this semb")
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--readings", default="warm,rss,query,span",
                    help="comma-separated subset of warm, rss, query, span")
    ap.add_argument("--cold", action="store_true", help="take only the cold time-to-ready, first thing")
    ap.add_argument("--warm-runs", type=int, default=3)
    ap.add_argument("--idle-window", type=float, default=2.0)
    ap.add_argument("--steady-delay", type=float, default=5.0)
    ap.add_argument("--span-tokens", default="256,1024,4096")
    ap.add_argument("--span-lead", default="the")
    ap.add_argument("--span-unit", default=" the")
    ap.add_argument("--span-baseline-runs", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=7200.0)
    args = ap.parse_args(argv)
    args.span_tokens = [int(v) for v in args.span_tokens.split(",") if v]
    wanted = {"cold"} if args.cold else {r.strip() for r in args.readings.split(",") if r.strip()}
    if wanted - {"warm", "rss", "query", "span", "cold"}:
        ap.error(f"unknown readings: {sorted(wanted - {'warm', 'rss', 'query', 'span'})}")
    if args.cold and args.bank is None:
        ap.error("--cold needs --bank: baking first would warm the file cache the reading must not have")
    args.out.mkdir(parents=True, exist_ok=True)
    scratch = args.out / "scratch"

    rows = [json.loads(line) for line in args.corpus.read_text(encoding="utf-8").splitlines() if line]
    texts = [row["text"] for row in rows]
    result: dict = {"cell": {"cell": args.cell, "device": "cpu", "cache_state": "cold" if args.cold else "warm",
                             "corpus": str(args.corpus.name), "corpus_sha256": sha256_file(args.corpus),
                             "platform": platform.platform(), "processor": platform.processor(),
                             "counters": "Windows process counters" if IS_WINDOWS else
                                         "Linux /proc status fields (smoke only, not the published counters)",
                             "uptime_seconds_at_start": uptime_seconds()},
                    "readings": {}, "failures": []}
    started = time.perf_counter()

    def take(name: str, fn):
        try:
            value = fn()
            result["readings"][name] = value
            print(f"[READING] {name}: {json.dumps(value if name != 'query' else {k: v for k, v in value.items() if k != 'per_query_seconds'})}", flush=True)
        except Exception as exc:  # noqa: BLE001 -- a reading not taken is reported, never dropped
            result["failures"].append({"reading": name, "error": f"{type(exc).__name__}: {exc}"})
            print(f"[NOT TAKEN] {name}: {type(exc).__name__}: {exc}", flush=True)

    bank = args.bank
    if args.cold:
        take("cold_time_to_ready", lambda: time_to_ready(args, bank, texts[0]))
    else:
        if bank is None and wanted & {"warm", "rss", "query"}:
            shutil.rmtree(scratch, ignore_errors=True)
            scratch.mkdir(parents=True)
            corpus = scratch / "corpus-239-cli.jsonl"
            corpus.write_bytes("".join(json.dumps({"id": r["label"], "text": r["text"]}) + "\n"
                                       for r in rows).encode("utf-8"))
            bank = scratch / "corpus-239"
            baked = subprocess.run([str(args.semb), "bake", str(corpus), "--out", str(bank), "--model", args.model,
                                    "--tokenizer", args.tokenizer], capture_output=True, timeout=args.timeout)
            if baked.returncode:
                print(f"[NOT TAKEN] all: the corpus bake exited {baked.returncode}", flush=True)
                return 1
        scratch.mkdir(parents=True, exist_ok=True)
        if "warm" in wanted:
            def warm():
                time_to_ready(args, bank, texts[0])  # discarded: warms the file cache
                runs = [time_to_ready(args, bank, texts[0]) for _ in range(args.warm_runs)]
                return {"median_seconds": statistics.median(r["seconds"] for r in runs), "runs": runs,
                        "discarded_warmup_runs": 1}
            take("warm_time_to_ready", warm)
        if "rss" in wanted:
            take("rss_at_open", lambda: rss_at_open(args, bank, texts[0]))
        if "query" in wanted:
            take("query", lambda: query_median(args, bank, texts))
        if "span" in wanted:
            take("span_curve", lambda: span_curve(args, scratch))
    if bank is not None:
        manifest_path = Path(str(bank) + ".semb.json")
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            result["cell"].update({k: manifest.get(k) for k in ("encoder_fingerprint", "model_sha", "tokenizer_sha",
                                                                "machine_tier")})
    version = subprocess.run([str(args.semb), "--version"], capture_output=True, timeout=120)
    result["cell"]["semb_version_output"] = (version.stdout + version.stderr).decode("utf-8", "replace").strip()
    result["cell"]["semb_sha256"] = sha256_file(args.semb)
    result["wall_seconds"] = time.perf_counter() - started
    (args.out / "readiness.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {args.out / 'readiness.json'}", flush=True)
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
