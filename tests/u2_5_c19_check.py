"""U2 cloud build: U2-5's C19 (te267 sec 5 U2-5), the cells the frozen 1.0
reader needs.

C19-a (a pin with a vitality mutant): a well-formed bank manifest
(`<stem>.semb.json`) with one unknown top-level member is accepted by
`semb_bank_open` (SEMB_OK) and by `semb verify` (exit 0). Its vitality mutant is
a reader that rejects unknown keys: this cell builds it on every run -- the
shipped `bank.cpp` with one inserted check that refuses any manifest member
outside the set a fresh bake writes, compiled by the build's own compile
command into a copy of the certified archive -- and requires the mutant to
accept the unmodified bank and to REFUSE the one with the unknown member, both
through `semb_bank_open` and through a `semb` CLI relinked against it. A pin
whose mutant stays green is dead.

C19-b: a bank header (`<stem>.wvbank.json`) at `schemaVersion` 2 refuses
SEMB_MANIFEST_SCHEMA_UNSUPPORTED, and a header at `schemaVersion` 2 carrying
`channels` is refused by that name, through `semb_bank_open` and through
`semb verify`'s refusal line.

Green by construction today (the reader ignores unknown manifest members and
refuses both headers); these are pins for the 1.0 reader, not red-first.
Synthetic pair fixture; no real artifact.
"""
from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UNKNOWN = "zz_c19_member_added_in_1_1"
ANCHOR = "    if (!header.IsObject() || !manifest.IsObject()) return SEMB_ARTIFACT_UNREADABLE;\n"

OPEN_APP = r'''
#include <stdio.h>
#include <string.h>
#include "superembedder/semb.h"
int main(int argc, char** argv) {
  if (argc != 2) return 2;
  semb_bank b = NULL;
  semb_status s = semb_bank_open(argv[1], strlen(argv[1]), &b);
  printf("%s\n", semb_status_name(s));
  if (b) semb_bank_close(b);
  return 0;
}
'''


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", **kw)


def copy_triple(src: str, dst: str) -> None:
    for suf in (".wvbank.json", ".wvbank.bin", ".semb.json"):
        shutil.copy2(src + suf, dst + suf)


def add_member(path: Path) -> None:
    text = path.read_text(encoding="utf-8").rstrip()
    assert text.endswith("}")
    path.write_text(text[:-1].rstrip() + f',\n  "{UNKNOWN}": {{"note": "a member a 1.1 writer added"}}\n}}\n',
                    encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--archive", required=True)
    ap.add_argument("--engine-lib", required=True)
    args = ap.parse_args(argv)
    build = Path(args.build_dir)
    work = build / "_scratch" / "c19"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    fails = 0

    def verdict(ok: bool, cell: str, detail: str) -> None:
        nonlocal fails
        fails += 0 if ok else 1
        print(f"[{'PASS' if ok else 'FAIL'}] {cell}: {detail}")

    b = run([args.cmake_executable, "--build", str(build), "--target", "semb"], cwd=REPO_ROOT)
    semb = build / "semb"
    if b.returncode or not semb.exists():
        print(f"[FAIL] C19 setup: the semb CLI did not build\n{(b.stdout + b.stderr)[-2000:]}")
        return 1
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import u2_9_workspace_cells_check as u29  # noqa: E402
    pair = REPO_ROOT / "build" / "_scratch" / "u2_9_min_pair"
    u29.ensure_pair(pair)
    model, tok = str(pair / "u1_pair_model.sslm"), str(pair / "u1_pair_tokenizer.sslm")
    corpus = work / "corpus.txt"
    corpus.write_text("a first short document\nthe second one\nand a third\n", encoding="utf-8")
    good = str(work / "good")
    r = run([str(semb), "bake", str(corpus), "--out", good, "--model", model, "--tokenizer", tok])
    if r.returncode:
        print(f"[FAIL] C19 setup: bake failed: {(r.stdout + r.stderr)[-800:]}")
        return 1
    known = list(json.loads(Path(good + ".semb.json").read_text(encoding="utf-8")).keys())

    # The two readers: the shipped archive, and the unknown-key-rejecting mutant.
    app_src = work / "open_app.c"
    app_src.write_text(OPEN_APP, encoding="utf-8")
    comp = json.loads(run(["ninja", "-C", str(build), "-t", "compdb"]).stdout)
    entry = next(e for e in comp if e["file"].endswith("src/superembedder/bank.cpp")
                 and "superembedder.dir" in e["output"])
    bank_src = Path(entry["file"]).read_text(encoding="utf-8")
    if bank_src.count(ANCHOR) != 1:
        print("[FAIL] C19-a vitality mutant: bank.cpp's insertion anchor is not unique; the mutant cannot be built")
        return 1
    check = ("    { static const char* kKnown[] = {" + ", ".join(json.dumps(k) for k in known) + "};\n"
             "      for (const auto& kv : manifest.as_object) { bool ok = false;\n"
             "        for (const char* k : kKnown) ok = ok || kv.first == k;\n"
             "        if (!ok) return SEMB_ARTIFACT_UNREADABLE; } }  // C19-a MUTANT: rejects unknown keys\n")
    mutant_src = work / "bank_c19_mutant.cpp"
    mutant_src.write_text(bank_src.replace(ANCHOR, ANCHOR + check), encoding="utf-8")
    argv_c = shlex.split(entry["command"])
    obj = work / "bank.cpp.o"
    for i, a in enumerate(argv_c):
        if a == "-o":
            argv_c[i + 1] = str(obj)
        elif a == "-c":
            argv_c[i + 1] = str(mutant_src)
        elif a in ("-MF", "-MT", "-MQ"):
            argv_c[i + 1] = str(work / "bank.d")
    argv_c.insert(1, f"-I{Path(entry['file']).parent}")
    cm = run(argv_c, cwd=entry["directory"])
    mutant_archive = work / "libsuperembedder_c19_mutant.a"
    shutil.copy2(args.archive, mutant_archive)
    members = run(["ar", "t", str(mutant_archive)]).stdout.split()
    ar = run(["ar", "r", str(mutant_archive), str(obj)]) if cm.returncode == 0 else cm
    readers = {}
    for name, archive in (("shipped", args.archive), ("mutant", str(mutant_archive))):
        exe = work / f"open_{name}"
        lk = run(["c++", "-O2", "-x", "c", str(app_src), "-x", "none", "-o", str(exe), f"-I{REPO_ROOT / 'include'}",
                  archive, args.engine_lib, "-lpthread", "-lm"])
        cli = work / f"semb_{name}"
        lc = run(["c++", "-O2", str(build / "CMakeFiles" / "semb.dir" / "src" / "main.cpp.o"), "-o", str(cli),
                  archive, args.engine_lib, "-lpthread"])
        readers[name] = (exe if lk.returncode == 0 else None, cli if lc.returncode == 0 else None,
                         (lk.stderr + lc.stderr)[-400:])
    if cm.returncode or "bank.cpp.o" not in members or readers["mutant"][0] is None:
        verdict(False, "C19-a vitality mutant built", f"compile {cm.returncode}: {cm.stderr[-400:]} "
                f"members-has-bank.cpp.o={'bank.cpp.o' in members} {readers['mutant'][2]}")

    def bank_open(reader: str, stem: str) -> str:
        exe = readers[reader][0]
        return run([str(exe), stem]).stdout.strip() if exe else "reader-absent"

    def verify(reader: str, stem: str) -> tuple[int, str]:
        cli = readers[reader][1]
        if not cli:
            return -1, "cli-absent"
        r = run([str(cli), "verify", stem, "--corpus", str(corpus), "--model", model, "--tokenizer", tok])
        lines = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.startswith("semb ")]
        return r.returncode, " | ".join(lines)[-200:]

    unknown = str(work / "unknown_member")
    copy_triple(good, unknown)
    add_member(Path(unknown + ".semb.json"))
    json.loads(Path(unknown + ".semb.json").read_text(encoding="utf-8"))  # well-formed
    s = bank_open("shipped", unknown)
    verdict(s == "SEMB_OK", "C19-a semb_bank_open accepts a manifest with one unknown top-level member", s)
    rc, out = verify("shipped", unknown)
    verdict(rc == 0, "C19-a semb verify accepts it", f"exit {rc} {out}")
    if readers["mutant"][0] is not None:
        s0, s1 = bank_open("mutant", good), bank_open("mutant", unknown)
        verdict(s0 == "SEMB_OK" and s1 != "SEMB_OK",
                "C19-a vitality: the unknown-key-rejecting reader accepts the plain bank and refuses the unknown member",
                f"plain {s0}, unknown {s1}")
        rc0, _ = verify("mutant", good)
        rc1, out1 = verify("mutant", unknown)
        verdict(rc0 == 0 and rc1 != 0, "C19-a vitality: semb verify on that reader refuses the unknown member",
                f"plain exit {rc0}, unknown exit {rc1} {out1}")

    for label, mutate in (
            ("schemaVersion 2", lambda h: dict(h, schemaVersion=2)),
            ("schemaVersion 2 with channels",
             lambda h: dict(h, schemaVersion=2, channels=[{"name": "x", "offset": 0, "dims": h.get("dims", 1)}]))):
        stem = str(work / ("b_" + label.replace(" ", "_")))
        copy_triple(good, stem)
        hp = Path(stem + ".wvbank.json")
        hp.write_text(json.dumps(mutate(json.loads(hp.read_text(encoding="utf-8")))), encoding="utf-8")
        s = bank_open("shipped", stem)
        verdict(s == "SEMB_MANIFEST_SCHEMA_UNSUPPORTED", f"C19-b bank header at {label} -> SEMB_MANIFEST_SCHEMA_UNSUPPORTED",
                s)
        rc, out = verify("shipped", stem)
        verdict(rc != 0 and "SEMB_MANIFEST_SCHEMA_UNSUPPORTED" in out, f"C19-b semb verify refuses {label} by name",
                f"exit {rc} {out}")
    print(f"TOTAL fail={fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
