"""Slice 6's executable `semb` CLI contract (C24, C18, and C5).

CLI choices where the plan deliberately leaves syntax/output open:
  * model selection is verb-local `--model <sslm> --tokenizer <sslm>`;
  * `query --hex` writes exactly one `VECTOR_HEX=<lowercase hex>` line;
  * `query --stdin --hex` reads one UTF-8 query per line and writes one such
    line per query, while stderr reports `query_handle_opens=1` once;
  * `query --top 5` writes one JSON object per input with five `hits`.
These are the smallest machine-readable forms that let this test compare the
CLI to the C ABI without parsing presentation text.  The planner owns their
ratification; this file pins the test-author choice until then.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from te230_c5_floor import FLOOR

ROOT = Path(__file__).resolve().parent.parent
STATUSES = {
    "fingerprint": "SEMB_FINGERPRINT_MISMATCH",
    "schema": "SEMB_MANIFEST_SCHEMA_UNSUPPORTED",
    "size": "SEMB_BANK_SIZE_MISMATCH",
    "artifact": "SEMB_ARTIFACT_SHA_MISMATCH",
}


def find(build: Path, name: str) -> Path | None:
    candidates = [build / f"{name}.exe", build / name, build / "tests" / f"{name}.exe", build / "tests" / name]
    return next((p for p in candidates if p.exists()), next(iter(build.rglob(f"{name}.exe")), None))


class Report:
    def __init__(self) -> None: self.failed = False
    def add(self, state: str, cell: str, detail: str) -> None:
        print(f"[{state}] {cell}: {detail}")
        self.failed |= state in {"FAIL", "RED-UNIMPLEMENTED"}


def call(args: list[str], stdin: str | None = None, timeout: int = 420) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, input=stdin, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def expect_status(report: Report, cell: str, proc: subprocess.CompletedProcess[str], status: str) -> None:
    text = proc.stdout + proc.stderr
    report.add("PASS" if proc.returncode != 0 and status in text else "FAIL", cell,
               f"exit={proc.returncode}; expected {status}; stderr={proc.stderr[-400:]!r}")


def copied_stem(source: Path, destination: Path) -> None:
    for suffix in (".wvbank.json", ".wvbank.bin", ".semb.json"):
        shutil.copyfile(Path(str(source) + suffix), Path(str(destination) + suffix))


def mutate(stem: Path, kind: str) -> None:
    if kind == "size":
        with Path(str(stem) + ".wvbank.bin").open("ab") as f: f.write(b"\0")
        return
    manifest = Path(str(stem) + ".semb.json")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if kind == "fingerprint": data["encoder_fingerprint"] = "00" * 32
    elif kind == "schema":
        bank = Path(str(stem) + ".wvbank.json")
        header = json.loads(bank.read_text(encoding="utf-8")); header["schemaVersion"] = 999
        bank.write_text(json.dumps(header), encoding="utf-8")
        return
    elif kind == "artifact": data.setdefault("provenance", {})["artifact_sha"] = "00" * 32
    manifest.write_text(json.dumps(data), encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", type=Path, required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--tokenizer", required=True)
    args = ap.parse_args(argv)
    report = Report(); scratch = args.build_dir / "_scratch" / "te230_cli"
    shutil.rmtree(scratch, ignore_errors=True); scratch.mkdir(parents=True)
    built = call([args.cmake_executable, "--build", str(args.build_dir), "--target", "semb", "te230_semb_cli_probe"], timeout=420)
    if built.returncode:
        report.add("FAIL", "CLI apparatus", (built.stdout + built.stderr)[-1000:]); return 1
    semb, probe = find(args.build_dir, "semb"), find(args.build_dir, "te230_semb_cli_probe")
    if not semb or not probe:
        report.add("FAIL", "CLI apparatus", "semb or te230_semb_cli_probe was not produced"); return 1
    help_run = call([str(semb), "query", "--help"])
    report.add("PASS" if help_run.returncode == 0 and "diagnostic" in (help_run.stdout + help_run.stderr).lower() else "FAIL",
               "CLI one-shot diagnostic help", "query --help must name one-shot query a diagnostic")
    corpus = ROOT / "tests" / "fixtures" / "wb" / "wb-corpus.jsonl"; good = scratch / "good"
    base = ["--model", args.model, "--tokenizer", args.tokenizer]
    bake = call([str(semb), "bake", str(corpus), "--out", str(good), *base])
    if bake.returncode != 0:
        report.add("RED-UNIMPLEMENTED" if "semb " in bake.stdout else "FAIL", "CLI bake baseline",
                   f"exit={bake.returncode}; {bake.stderr[-500:]!r}")
        return 1
    files_ok = all(Path(str(good) + s).is_file() for s in (".wvbank.json", ".wvbank.bin", ".semb.json"))
    report.add("PASS" if files_ok else "FAIL", "CLI bake triple",
               "writes exactly the bank pair plus manifest" if files_ok else
               "RED-UNIMPLEMENTED: the stub returned success without writing the required triple")
    if not files_ok:
        return 1
    text = "A concise query for the CLI contract."
    lib = call([str(probe), "--model", args.model, "--tokenizer", args.tokenizer, "--stem", str(good), "--text", text])
    lib_hex = re.search(r"^VECTOR_HEX=([0-9a-f]+)$", lib.stdout, re.M)
    report.add("PASS" if lib.returncode == 0 and lib_hex else "FAIL", "CLI bank opens through semb_bank_open", lib.stderr[-400:])
    one = call([str(semb), "query", str(good), text, "--hex", *base])
    one_hex = re.search(r"^VECTOR_HEX=([0-9a-f]+)$", one.stdout, re.M)
    report.add("PASS" if one.returncode == 0 and lib_hex and one_hex and one_hex.group(1) == lib_hex.group(1) else "FAIL",
               "CLI one-shot bytes equal library", "one-shot query is the documented diagnostic")
    lines = [text, "A second query proves session reuse."]
    session = call([str(semb), "query", "--stdin", str(good), "--hex", *base], stdin="\n".join(lines) + "\n")
    session_hex = re.findall(r"^VECTOR_HEX=([0-9a-f]+)$", session.stdout, re.M)
    report.add("PASS" if session.returncode == 0 and len(session_hex) == len(lines) and session_hex[0] == (lib_hex.group(1) if lib_hex else "") and "query_handle_opens=1" in session.stderr else "FAIL",
               "CLI stdin one handle", "observable=query_handle_opens=1; each stdin vector is library-equal")
    # C24: output directory begins empty; no final, partial, or temporary file survives refusal.
    empty = scratch / "empty.jsonl"; empty.write_text("", encoding="utf-8"); empty_stem = scratch / "empty" / "out"; empty_stem.parent.mkdir()
    c24 = call([str(semb), "bake", str(empty), "--out", str(empty_stem), *base])
    leftovers = list(empty_stem.parent.iterdir())
    report.add("PASS" if c24.returncode != 0 and "SEMB_CORPUS_EMPTY" in c24.stderr and not leftovers else "FAIL",
               "C24 empty corpus", f"exit={c24.returncode}; leftovers={[p.name for p in leftovers]}")
    # C18: bake has no bank/manifest input, so its four alleged crossings are unconstructible;
    # query, verify, and the direct bank-bound library path each consume the same mutated triple.
    for kind, status in STATUSES.items():
        stem = scratch / f"c18_{kind}"; copied_stem(good, stem); mutate(stem, kind)
        expect_status(report, f"C18/{kind}/query", call([str(semb), "query", str(stem), text, "--hex", *base]), status)
        expect_status(report, f"C18/{kind}/verify", call([str(semb), "verify", str(stem), *base]), status)
        expect_status(report, f"C18/{kind}/library", call([str(probe), "--model", args.model, "--tokenizer", args.tokenizer, "--stem", str(stem), "--text", text]), status)
    inspect_manifest = Path(str(good) + ".semb.json")
    inspect = call([str(semb), "inspect", str(inspect_manifest)])
    report.add("PASS" if inspect.returncode == 0 and inspect_manifest.read_text(encoding="utf-8") in inspect.stdout else "FAIL",
               "CLI inspect opens no encoder", "inspect succeeds while the configured model artifact is absent")
    # C5: the 239 real-document bake and one-handle query workload.  The floor
    # was committed by te230_c5_floor.py before this process was ever run.
    c5_rows = [json.loads(line) for line in (ROOT / "tests" / "fixtures" / "c12b" / "corpus-239.jsonl").read_text(encoding="utf-8").splitlines() if line]
    c5_stem = scratch / "c5"; started = time.monotonic()
    c5_bake = call([str(semb), "bake", str(ROOT / "tests" / "fixtures" / "c12b" / "corpus-239.jsonl"), "--out", str(c5_stem), *base], timeout=420)
    bake_s_per_document = (time.monotonic() - started) / len(c5_rows)
    if c5_bake.returncode:
        report.add("FAIL", "C5 real workload bake", c5_bake.stderr[-500:]); return 1
    q_started = time.monotonic()
    c5_query = call([str(semb), "query", "--stdin", str(c5_stem), "--top", "5", *base],
                    stdin="\n".join(row["text"] for row in c5_rows) + "\n", timeout=420)
    query_s_per_document = (time.monotonic() - q_started) / len(c5_rows)
    try:
        outputs = [json.loads(line) for line in c5_query.stdout.splitlines() if line]
        labels = {row["label"]: row["class"] for row in c5_rows}
        correct = sum(bool(out.get("hits")) and labels.get(out["hits"][0].get("id")) == c5_rows[i]["class"]
                      for i, out in enumerate(outputs))
        score = correct / len(c5_rows)
        shape = len(outputs) == len(c5_rows) and all(len(out.get("hits", [])) == 5 for out in outputs)
        report.add("PASS" if c5_query.returncode == 0 and shape and score >= float(FLOOR) else "FAIL", "C5 class-match@1",
                   f"score={correct}/{len(c5_rows)}={score:.12f}; floor={float(FLOOR):.12f}; "
                   f"bake_s_per_document={bake_s_per_document:.6f}; query_s_per_document={query_s_per_document:.6f}; top5_per_query={shape}")
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        report.add("FAIL", "C5 output", f"machine-readable top-5 JSONL required: {exc}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
