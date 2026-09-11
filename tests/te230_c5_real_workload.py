"""C5's quarantined real-artifact class-match workload.

This intentionally measures rather than gates the class-match floor: a
non-regression result needs a calibrated product population, while a bad
score remains a conductor-owned quarantine observation.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from te230_c5_floor import FLOOR

ROOT = Path(__file__).resolve().parent.parent


def first_nonself_hit(query_id: str, hits: list[dict]) -> dict | None:
    """Return the nearest neighbor that is not the query document itself."""
    return next((hit for hit in hits if hit.get("id") != query_id), None)


def c5_exclusion_selftest() -> int:
    query_id = "correction-001"
    hits = [{"id": query_id}, {"id": "plain-002"}, {"id": "negation-003"}]
    got = first_nonself_hit(query_id, hits)
    ok = got == {"id": "plain-002"}
    print(f"[{'PASS' if ok else 'FAIL'}] C5 self-hit exclusion: selected={got!r}")
    return 0 if ok else 1


def find(build: Path, name: str) -> Path | None:
    candidates = [build / f"{name}.exe", build / name]
    return next((p for p in candidates if p.exists()), next(iter(build.rglob(f"{name}.exe")), None))


def call(args: list[str], stdin: str | None = None, timeout: int = 420) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, input=stdin, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def main(argv: list[str]) -> int:
    if argv == ["--selftest"]:
        return c5_exclusion_selftest()
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", type=Path, required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--tokenizer", required=True)
    args = ap.parse_args(argv)
    scratch = args.build_dir / "_scratch" / "te230_c5"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    built = call([args.cmake_executable, "--build", str(args.build_dir), "--target", "semb"])
    semb = find(args.build_dir, "semb")
    if built.returncode or not semb:
        print(f"[BLOCKED] C5 apparatus: semb build unavailable: {(built.stdout + built.stderr)[-400:]!r}")
        return 1

    rows = [json.loads(line) for line in
            (ROOT / "tests" / "fixtures" / "c12b" / "corpus-239.jsonl").read_text(encoding="utf-8").splitlines()
            if line]
    labels = {row["label"]: row["class"] for row in rows}
    texts = {row["label"]: row["text"] for row in rows}
    corpus = scratch / "c5-cli-corpus.jsonl"
    corpus.write_text("".join(json.dumps({"id": row["label"], "text": row["text"]}) + "\n"
                              for row in rows), encoding="utf-8")
    stem = scratch / "c5"
    base = ["--model", args.model, "--tokenizer", args.tokenizer]
    bake_started = time.monotonic()
    bake = call([str(semb), "bake", str(corpus),
                 "--out", str(stem), *base])
    bake_s_per_document = (time.monotonic() - bake_started) / len(rows)
    triple = all(Path(str(stem) + suffix).is_file()
                 for suffix in (".wvbank.json", ".wvbank.bin", ".semb.json"))
    if bake.returncode or not triple:
        print("[BLOCKED] C5 class-match@1: bake did not produce the required triple; "
              f"exit={bake.returncode}; stderr={bake.stderr[-400:]!r}")
        return 1

    query_started = time.monotonic()
    query = subprocess.Popen(
        [str(semb), "query", "--stdin", str(stem), "--top", "6", *base],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace")
    assert query.stdin is not None and query.stdout is not None and query.stderr is not None
    # Feed standard input from its own thread: the CLI answers each line as it
    # reads it, so writing all 239 lines before reading any output fills both
    # pipes and deadlocks (executed: hung at 60 s where a concurrent reader
    # finished 239 queries in 10.3 s on the synthetic pair).
    def feed() -> None:
        query.stdin.write("\n".join(row["text"] for row in rows) + "\n")
        query.stdin.close()

    threading.Thread(target=feed, daemon=True).start()
    try:
        outputs: list[dict] = []
        displayed = []
        correct = 0
        for index, line in enumerate(query.stdout):
            emitted_s = time.monotonic() - query_started
            output = json.loads(line)
            if index >= len(rows):
                raise ValueError(f"received unexpected query output {index + 1}")
            row = rows[index]
            nonself = [hit for hit in output["hits"] if hit.get("id") != row["label"]][:5]
            displayed.append(nonself)
            first = first_nonself_hit(row["label"], output["hits"])
            correct += bool(first) and labels.get(first.get("id")) == row["class"]
            outputs.append(output)
            observation = ", ".join(
                f"{hit.get('id')} class={labels.get(hit.get('id'))!r} "
                f"text={texts.get(hit.get('id'), str(hit.get('text', '')))[:48]!r}"
                for hit in nonself)
            print(f"[OBSERVED] C5 query={row['label']} query_wall_s={emitted_s:.6f} "
                  f"top5 excluding self: {observation}", flush=True)
        stderr = query.stderr.read()
        returncode = query.wait()
        query_s_per_document = (time.monotonic() - query_started) / len(rows)
        shaped = len(outputs) == len(rows) and all(len(hits) == 5 for hits in displayed)
        score = correct / len(rows)
        apparatus = returncode == 0 and shaped
        print(f"[{'QUARANTINED' if apparatus else 'BLOCKED'}] C5 class-match@1: "
              f"score={correct}/{len(rows)}={score:.12f}; floor={float(FLOOR):.12f}; "
              f"bake_s_per_document={bake_s_per_document:.6f}; "
              f"query_s_per_document={query_s_per_document:.6f}; stderr={stderr[-240:]!r}")
        return 0 if apparatus else 1
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        query.kill()
        query.wait()
        print(f"[BLOCKED] C5 class-match@1: machine-readable top-6 JSONL required: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
