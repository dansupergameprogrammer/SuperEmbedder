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
from pathlib import Path

from u1_raw_text_cells_check import ensure_pair

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
        self.failed |= state in {"FAIL", "RED-UNIMPLEMENTED", "BLOCKED"}


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
    args = ap.parse_args(argv)
    report = Report(); scratch = args.build_dir / "_scratch" / "te230_cli"
    shutil.rmtree(scratch, ignore_errors=True); scratch.mkdir(parents=True)
    try:
        pair = args.build_dir / "_scratch" / "u1_pair"
        ensure_pair(pair)
        model, tokenizer = str(pair / "u1_pair_model.sslm"), str(pair / "u1_pair_tokenizer.sslm")
        report.add("PASS", "synthetic tokenizer-pair fixture", str(pair))
    except Exception as exc:
        model = tokenizer = ""
        report.add("FAIL", "synthetic tokenizer-pair fixture", f"{type(exc).__name__}: {exc}")
    built = call([args.cmake_executable, "--build", str(args.build_dir), "--target", "semb", "te230_semb_cli_probe"], timeout=420)
    if built.returncode:
        report.add("FAIL", "CLI apparatus", (built.stdout + built.stderr)[-1000:])
    semb, probe = find(args.build_dir, "semb"), find(args.build_dir, "te230_semb_cli_probe")
    if not semb or not probe:
        report.add("FAIL", "CLI apparatus", "semb or te230_semb_cli_probe was not produced")
        return 1
    help_run = call([str(semb), "query", "--help"])
    report.add("PASS" if help_run.returncode == 0 and "diagnostic" in (help_run.stdout + help_run.stderr).lower() else "FAIL",
               "CLI one-shot diagnostic help", "query --help must name one-shot query a diagnostic")
    corpus = ROOT / "tests" / "fixtures" / "wb" / "wb-corpus.jsonl"; good = scratch / "good"
    base = ["--model", model, "--tokenizer", tokenizer]
    bake = call([str(semb), "bake", str(corpus), "--out", str(good), *base])
    if bake.returncode != 0:
        report.add("RED-UNIMPLEMENTED" if "semb " in bake.stdout else "FAIL", "CLI bake baseline",
                   f"exit={bake.returncode}; {bake.stderr[-500:]!r}")
    files_ok = all(Path(str(good) + s).is_file() for s in (".wvbank.json", ".wvbank.bin", ".semb.json"))
    report.add("PASS" if files_ok else "FAIL", "CLI bake triple",
               "writes exactly the bank pair plus manifest" if files_ok else
               "RED-UNIMPLEMENTED: the stub returned success without writing the required triple")
    text = "A concise query for the CLI contract."
    library_good = scratch / "library_good"
    library_bake = call([str(probe), "--model", model, "--tokenizer", tokenizer, "--stem", str(library_good),
                         "--bake-corpus", str(corpus)])
    library_ok = library_bake.returncode == 0 and all(Path(str(library_good) + s).is_file()
                                                       for s in (".wvbank.json", ".wvbank.bin", ".semb.json"))
    report.add("PASS" if library_ok else "FAIL", "library bake baseline",
               (library_bake.stdout + library_bake.stderr)[-400:])
    lib = call([str(probe), "--model", model, "--tokenizer", tokenizer, "--stem", str(library_good), "--text", text]) if library_ok else None
    lib_hex = re.search(r"^VECTOR_HEX=([0-9a-f]+)$", lib.stdout, re.M) if lib else None
    report.add("PASS" if lib and lib.returncode == 0 and lib_hex else "FAIL", "library bank opens through semb_bank_open",
               lib.stderr[-400:] if lib else "library bake did not produce a triple")
    if files_ok and lib_hex:
        one = call([str(semb), "query", str(good), text, "--hex", *base])
        one_hex = re.search(r"^VECTOR_HEX=([0-9a-f]+)$", one.stdout, re.M)
        report.add("PASS" if one.returncode == 0 and one_hex and one_hex.group(1) == lib_hex.group(1) else "FAIL",
                   "CLI one-shot bytes equal library", "one-shot query is the documented diagnostic")
        lines = [text, "A second query proves session reuse."]
        session = call([str(semb), "query", "--stdin", str(good), "--hex", *base], stdin="\n".join(lines) + "\n")
        session_hex = re.findall(r"^VECTOR_HEX=([0-9a-f]+)$", session.stdout, re.M)
        report.add("PASS" if session.returncode == 0 and len(session_hex) == len(lines) and session_hex[0] == lib_hex.group(1) and "query_handle_opens=1" in session.stderr else "FAIL",
                   "CLI stdin one handle", "observable=query_handle_opens=1; each stdin vector is library-equal")
    else:
        report.add("BLOCKED", "CLI one-shot bytes equal library", "CLI baseline triple and library vector are required")
        report.add("BLOCKED", "CLI stdin one handle", "CLI baseline triple and library vector are required")
    # C24: output directory begins empty; no final, partial, or temporary file survives refusal.
    empty = scratch / "empty.jsonl"; empty.write_text("", encoding="utf-8"); empty_stem = scratch / "empty" / "out"; empty_stem.parent.mkdir()
    c24 = call([str(semb), "bake", str(empty), "--out", str(empty_stem), *base])
    leftovers = list(empty_stem.parent.iterdir())
    report.add("PASS" if c24.returncode != 0 and "SEMB_CORPUS_EMPTY" in c24.stderr and not leftovers else "FAIL",
               "C24 empty corpus", f"exit={c24.returncode}; leftovers={[p.name for p in leftovers]}")
    for kind, status in STATUSES.items():
        if library_ok:
            stem = scratch / f"library_c18_{kind}"; copied_stem(library_good, stem); mutate(stem, kind)
            expect_status(report, f"C18/{kind}/library", call([str(probe), "--model", model, "--tokenizer", tokenizer, "--stem", str(stem), "--text", text]), status)
        else:
            report.add("BLOCKED", f"C18/{kind}/library", "synthetic pair refuses the W-B corpus at its context cap")
        if files_ok:
            cli_stem = scratch / f"cli_c18_{kind}"; copied_stem(good, cli_stem); mutate(cli_stem, kind)
            expect_status(report, f"C18/{kind}/query", call([str(semb), "query", str(cli_stem), text, "--hex", *base]), status)
            expect_status(report, f"C18/{kind}/verify", call([str(semb), "verify", str(cli_stem), *base]), status)
        else:
            report.add("BLOCKED", f"C18/{kind}/query", "CLI baseline triple was not produced")
            report.add("BLOCKED", f"C18/{kind}/verify", "CLI baseline triple was not produced")
    if files_ok:
        accepted = call([str(semb), "verify", str(good), *base])
        report.add("PASS" if accepted.returncode == 0 else "FAIL", "verify untouched bank accepts", (accepted.stdout + accepted.stderr)[-400:])
        digest_stem = scratch / "same_size_digest"; copied_stem(good, digest_stem)
        payload = Path(str(digest_stem) + ".wvbank.bin"); data = bytearray(payload.read_bytes()); data[len(data) // 2] ^= 1; payload.write_bytes(data)
        expect_status(report, "verify same-size payload digest", call([str(semb), "verify", str(digest_stem), *base]), "SEMB_BANK_DIGEST_MISMATCH")
        inspect_manifest = Path(str(good) + ".semb.json"); inspect = call([str(semb), "inspect", str(inspect_manifest)])
        report.add("PASS" if inspect.returncode == 0 and inspect_manifest.read_text(encoding="utf-8") in inspect.stdout else "FAIL",
                   "CLI inspect opens no encoder", "inspect succeeds while the configured model artifact is absent")
    else:
        report.add("BLOCKED", "verify untouched bank accepts", "CLI baseline triple was not produced")
        report.add("BLOCKED", "verify same-size payload digest", "CLI baseline triple was not produced")
        report.add("BLOCKED", "CLI inspect opens no encoder", "CLI baseline manifest was not produced")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
