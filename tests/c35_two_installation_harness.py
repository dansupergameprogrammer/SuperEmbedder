"""C35 -- the two-installation construction, at its 1.0 legs (TE-264; U1 Slice
7 step 6, `Claude/Plans/te140-u1-remainder-sequencing.md` sec 4.7;
`Claude/Plans/SuperEmbedder_Plan.md` sec 8 C35; D-SLM7198).

Two SuperEmbedder installations are built independently, each from its own
export of the product tree and against its own engine prefix from its own
`tools/pin-superslm` run.  The 239-document corpus is baked on one and its
bank is queried from the other with the real artifact.  Legs:

  (i)    B identical to A (same revision, same compiler, own engine prefix):
         the bank opens (VECTOR_EMITTED for every document), the five
         fingerprint components are equal, B's own baked rows over the
         corpus are byte-identical to A's, and B's query vectors for the
         corpus texts are byte-identical to A's (D-SLM7217 (1)).
  (vi)   B built by clang-cl, A by MSVC: as (i).
  (x)    B's PS-N epilogue arithmetic edited (src/superembedder/ps_n_pool.cpp),
         superslm.lib standing: SEMB_FINGERPRINT_MISMATCH at query open.
  (ix)   an arithmetic edit in a non-inline engine .cpp (src/silu_lut.cpp),
         B's library otherwise identical: SEMB_FINGERPRINT_MISMATCH.
  (xiii) B's docs/certified-builds.json differs by one byte:
         SEMB_FINGERPRINT_MISMATCH.
  (p)    a bank baked by the provisional build (an installation exported at the
         pre-change revision) queried by the final build:
         SEMB_FINGERPRINT_MISMATCH by name -- the upgrade path every U1-era
         bank takes.

A refusal leg passes only on exit 1 with the stderr line exactly
`semb query: SEMB_FINGERPRINT_MISMATCH (22)`, and only after its construction
has been shown to move the fingerprint component it targets (witness_sha for
(x) and (ix), certification_epoch for (xiii), encoder_fingerprint for (p)),
read from the two installations' own manifests.  A construction that leaves
its component equal is INEVALUABLE and is replaced, never passed (plan sec 4.7
step 6: "an edit that leaves it equal is replaced, never passed").

PLAN GAP G-1 (TE-264), RULED (D-SLM7217 (1)): the plan read (i) and (vi) as
"every vector byte-identical to A's row", with B querying every document.
`semb query` composes the query-prefix literal into every query
(src/superembedder/query.cpp ComposeQuery; `--raw` is an output mode of
`semb_query_encode`), while a bank row is the unprefixed document, so a
query vector is never a document row and the plan's own sentence was
unsatisfiable as written. The ruling keeps both readings rather than
picking one: (i) and (vi) additionally bake the corpus on B and compare its
baked rows to A's byte for byte, and additionally query the corpus texts on
A (as already done on B) and compare the two query-vector streams byte for
byte. Both checks cost minutes (TE-272; a full corpus bake plus a full
239-query run on each side), so a short-phase validation of this code path
uses a reduced document count; the recorded reading at the plan's own
document count is the conductor's, at step 10.

PHASES (each one command, none long-running, run inside a Visual Studio
developer shell so `cl`, `ninja` and `cmake` are on PATH):

  install  --name N [--rev REV] [--compiler msvc|clang-cl]
           [--construction none|epilogue|engine|cert-doc]
      exports the product tree at REV into <work>/N/src, applies the
      product-side construction, installs N's own engine prefix with
      tools/pin-superslm (for `engine`, from a scratch SuperSLM clone whose
      lock tag is moved onto the edited commit), configures and builds `semb`.
  bake     --name N --model M --tokenizer T
      bakes the 239-document corpus with N's `semb bake`.
  identity --name N --model M --tokenizer T
      bakes a two-document bank with N's `semb bake` to read N's five
      fingerprint components from its manifest.
  leg      --leg i|vi|x|ix|xiii|p --bank-from A --query-on B --model M --tokenizer T
      runs one leg; exit 0 PASS, 1 FAIL, 2 INEVALUABLE. For (i) and (vi) this
      phase also bakes the corpus on B, on every invocation (overwriting any
      earlier bake at B's bank/corpus), and queries A's bank with the corpus
      texts from both A and B, so every "leg i"/"leg vi" invocation takes B's
      full corpus bake plus a full corpus query on each installation.

Order for one full reading: install A (msvc, none), install P (--rev <the
provisional revision>), install B_i, B_vi, B_x, B_ix, B_xiii; bake A and P;
identity for every B; then the six legs.  Not run in CI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "fixtures" / "c12b" / "corpus-239.jsonl"
CORPUS_MANIFEST = ROOT / "tests" / "fixtures" / "c12b" / "corpus-239.manifest.json"
MISMATCH_LINE = "semb query: SEMB_FINGERPRINT_MISMATCH (22)"
COMPONENTS = ("model_sha", "tokenizer_sha", "template_sha256", "witness_sha", "certification_epoch")

# Constructions: (file relative to the tree, anchor that must occur exactly
# once, replacement).  Each is an arithmetic change on the path the leg names.
EPILOGUE_EDIT = ("src/superembedder/ps_n_pool.cpp",
                 "const BigUInt mag = BigUInt(abs_c).MulU64(abs_m);",
                 "const BigUInt mag = BigUInt(abs_c).MulU64(abs_m + 1u);")
ENGINE_EDIT = ("src/silu_lut.cpp",
               "pos_fixed += domain_hi / 2;",
               "pos_fixed += domain_hi / 2 + 1;")

LEGS = {
    "i": {"kind": "accept", "b_construction": "none", "same_compiler": True},
    "vi": {"kind": "accept", "b_construction": "none", "same_compiler": False},
    "x": {"kind": "refuse", "b_construction": "epilogue", "moves": "witness_sha"},
    "ix": {"kind": "refuse", "b_construction": "engine", "moves": "witness_sha"},
    "xiii": {"kind": "refuse", "b_construction": "cert-doc", "moves": "certification_epoch"},
    "p": {"kind": "refuse", "b_construction": "none", "moves": "encoder_fingerprint"},
}


def say(state: str, cell: str, detail: str) -> None:
    print(f"[{state}] {cell}: {detail}")
    sys.stdout.flush()


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None, timeout: int = 1800,
        stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, input=stdin, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def apply_edit(tree: Path, edit: tuple[str, str, str]) -> str:
    path, anchor, replacement = edit
    target = tree / path
    text = target.read_bytes().decode("utf-8")
    count = text.count(anchor)
    if count != 1:
        raise SystemExit(f"INEVALUABLE: construction anchor occurs {count} times in {path} (must be exactly once): "
                         f"{anchor!r}")
    target.write_bytes(text.replace(anchor, replacement).encode("utf-8"))
    return f"{path}: {anchor!r} -> {replacement!r}"


def edit_cert_doc(tree: Path) -> str:
    doc = tree / "docs" / "certified-builds.json"
    if not doc.is_file():
        raise SystemExit("RED: docs/certified-builds.json is absent from this revision -- the certification epoch is "
                         "still the pending sentinel (U1 Slice 7 step 4 unbuilt), so leg (xiii) has no document to "
                         "differ by one byte")
    original = doc.read_bytes()
    m = re.search(rb'"evidence"\s*:\s*"([^"\\]*)"', original)
    index = next((i for i in range(m.start(1), m.end(1)) if original[i:i + 1].isalpha()), None) if m else None
    if index is None:
        raise SystemExit("INEVALUABLE: the document carries no pairwiseProofs[].evidence string with a letter to edit")
    edited = original[:index] + original[index:index + 1].swapcase() + original[index + 1:]
    json.loads(edited.decode("utf-8"))
    doc.write_bytes(edited)
    return f"docs/certified-builds.json byte {index}: {original[index:index + 1]!r} -> {edited[index:index + 1]!r}"


def lock_fields(lock: Path) -> dict:
    return dict(line.split("=", 1) for line in lock.read_text(encoding="utf-8").splitlines() if "=" in line)


def export_tree(rev: str, dest: Path) -> None:
    archive = dest.parent / "export.zip"
    proc = run(["git", "-C", ROOT, "archive", "--format=zip", "-o", archive, rev])
    if proc.returncode:
        raise SystemExit(f"git archive {rev} failed: {proc.stderr}")
    with zipfile.ZipFile(archive) as z:
        z.extractall(dest)
    archive.unlink()


def compiler_env(compiler: str, clang_cl: str) -> tuple[dict, list[str]]:
    env = dict(os.environ)
    if compiler == "clang-cl":
        env["CC"] = env["CXX"] = clang_cl
        return env, [f"-DCMAKE_CXX_COMPILER={clang_cl}", f"-DCMAKE_C_COMPILER={clang_cl}"]
    env["CC"] = env["CXX"] = "cl"
    return env, ["-DCMAKE_CXX_COMPILER=cl"]


def find_semb(inst: Path) -> Path:
    for cand in (inst / "build" / "semb.exe", inst / "build" / "semb"):
        if cand.exists():
            return cand
    raise SystemExit(f"no semb executable under {inst / 'build'}; run install first")


def cmd_install(args) -> int:
    inst = args.work / args.name
    if inst.exists():
        shutil.rmtree(inst)
    (inst / "src").mkdir(parents=True)
    record = {"name": args.name, "rev": run(["git", "-C", ROOT, "rev-parse", args.rev]).stdout.strip(),
              "compiler": args.compiler, "construction": args.construction, "edits": []}
    export_tree(args.rev, inst / "src")
    src = inst / "src"
    if args.construction == "epilogue":
        record["edits"].append(apply_edit(src, EPILOGUE_EDIT))
    elif args.construction == "cert-doc":
        record["edits"].append(edit_cert_doc(src))

    env, cxx = compiler_env(args.compiler, args.clang_cl)
    engine_source = args.engine_source
    if args.construction == "engine":
        # Leg (ix)'s engine: a scratch SuperSLM clone, never the engine
        # checkout in place.  The edit is committed there and the lock's tag
        # is moved onto that commit in the scratch clone only, so the pin tool
        # (which clones at the lock's tag and refuses an uncommitted edit)
        # installs the edited engine and records its commit and tree in B's
        # lock, while B's compiled-in certification document still names A's
        # enginePin.
        tag = lock_fields(src / "superslm.lock")["tag"]
        clone = inst / "engine_clone"
        steps = [["git", "clone", "--no-hardlinks", "-c", "core.autocrlf=false", engine_source, clone],
                 ["git", "-C", clone, "checkout", "--detach", tag]]
        for step in steps:
            proc = run(step)
            if proc.returncode:
                raise SystemExit(f"{' '.join(map(str, step))} failed: {proc.stderr}")
        record["edits"].append("engine " + apply_edit(clone, ENGINE_EDIT))
        for step in (["git", "-C", clone, "-c", "user.name=c35", "-c", "user.email=c35@invalid", "commit", "-am",
                      "C35 (ix): engine arithmetic edit in a non-inline .cpp"],
                     ["git", "-C", clone, "tag", "-f", tag, "HEAD"]):
            proc = run(step)
            if proc.returncode:
                raise SystemExit(f"{' '.join(map(str, step))} failed: {proc.stderr}")
        engine_source = str(clone)
    record["engine_source"] = engine_source

    pin = run([sys.executable, src / "tools" / "pin-superslm" / "pin_superslm.py", "--lock", src / "superslm.lock",
               "--prefix", inst / "engine", "--source", engine_source, "--workdir", inst / "engine_work"],
              cwd=src, env=env)
    if pin.returncode:
        raise SystemExit(f"pin_superslm failed ({pin.returncode}):\n{(pin.stdout + pin.stderr)[-3000:]}")
    record["lock"] = lock_fields(src / "superslm.lock")
    configure = run(["cmake", "-S", src, "-B", inst / "build", "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
                     f"-DCMAKE_PREFIX_PATH={inst / 'engine'}", f"-DPython3_EXECUTABLE={sys.executable}", *cxx],
                    env=env)
    if configure.returncode:
        raise SystemExit(f"configure failed:\n{(configure.stdout + configure.stderr)[-3000:]}")
    build = run(["ninja", "-C", inst / "build", "-j8", "semb"], env=env)
    if build.returncode:
        raise SystemExit(f"build failed:\n{(build.stdout + build.stderr)[-3000:]}")
    (inst / "install.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    say("DONE", f"install {args.name}", json.dumps(record))
    return 0


def corpus_jsonl(work: Path) -> Path:
    """The committed corpus as `{"id", "text"}` rows (semb bake's JSONL form),
    after checking its bytes and count against the committed manifest."""
    data = CORPUS.read_bytes()
    manifest = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
    if hashlib.sha256(data).hexdigest() != manifest["files"]["corpus-239.jsonl"]:
        raise SystemExit("corpus-239.jsonl does not match its committed manifest")
    rows = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    if len(rows) != manifest["documents"] or any("\n" in r["text"] or "\r" in r["text"] for r in rows):
        raise SystemExit("corpus-239.jsonl: unexpected row count or a multi-line text")
    out = work / "corpus-239.idtext.jsonl"
    out.write_text("".join(json.dumps({"id": r["label"], "text": r["text"]}) + "\n" for r in rows), encoding="utf-8")
    return out


def bake(args, stem_name: str, corpus: Path) -> Path:
    inst = args.work / args.name
    stem = inst / "bank" / stem_name
    stem.parent.mkdir(parents=True, exist_ok=True)
    proc = run([find_semb(inst), "bake", corpus, "--out", stem, "--model", args.model, "--tokenizer", args.tokenizer])
    if proc.returncode or not Path(str(stem) + ".semb.json").is_file():
        raise SystemExit(f"semb bake on {args.name} failed ({proc.returncode}): {proc.stderr[-1500:]}")
    return stem


def cmd_bake(args) -> int:
    stem = bake(args, "corpus", corpus_jsonl(args.work))
    say("DONE", f"bake {args.name}", str(stem))
    return 0


def cmd_identity(args) -> int:
    tiny = args.work / "identity-corpus.jsonl"
    tiny.write_text(json.dumps({"id": "c35-a", "text": "a short identity document"}) + "\n" +
                    json.dumps({"id": "c35-b", "text": "another identity document"}) + "\n", encoding="utf-8")
    stem = bake(args, "identity", tiny)
    say("DONE", f"identity {args.name}", str(stem))
    return 0


def manifest(inst: Path, stem_name: str) -> dict:
    path = inst / "bank" / f"{stem_name}.semb.json"
    if not path.is_file():
        raise SystemExit(f"{path} is absent; run the bake/identity phase for {inst.name} first")
    return json.loads(path.read_text(encoding="utf-8"))


def read_wvbank(stem: Path) -> tuple[dict, bytes]:
    """The `.wvbank.json` header and the raw `.wvbank.bin` payload for a bake
    stem (src/superembedder/bank.cpp: a bank is the `.wvbank.json`/
    `.wvbank.bin`/`.semb.json` triple; this reads the first two, byte for
    byte, the same pair Claude/Brunel/te265-interim-evidence.py reads to
    compute its own per-row digest)."""
    header = json.loads(Path(str(stem) + ".wvbank.json").read_text(encoding="utf-8"))
    payload = Path(str(stem) + ".wvbank.bin").read_bytes()
    return header, payload


def cmd_leg(args) -> int:
    spec = LEGS[args.leg]
    a_inst, b_inst = args.work / args.bank_from, args.work / args.query_on
    a_rec = json.loads((a_inst / "install.json").read_text(encoding="utf-8"))
    b_rec = json.loads((b_inst / "install.json").read_text(encoding="utf-8"))
    cell = f"C35 ({args.leg})"
    # The pair must carry the leg's construction, so a reading cannot be
    # filed under a leg its installations do not realise.
    wrong = []
    if args.leg == "p":
        if a_rec["rev"] == b_rec["rev"]:
            wrong.append(f"the provisional installation {a_rec['name']} and the final {b_rec['name']} share revision "
                         f"{a_rec['rev']}")
        if a_rec["construction"] != "none" or b_rec["construction"] != "none":
            wrong.append("both installations must be unedited")
    else:
        if a_rec["construction"] != "none" or a_rec["compiler"] != "msvc":
            wrong.append(f"A must be the unedited MSVC installation (got {a_rec['construction']}/{a_rec['compiler']})")
        if b_rec["construction"] != spec["b_construction"]:
            wrong.append(f"B must carry construction {spec['b_construction']} (got {b_rec['construction']})")
        if b_rec["rev"] != a_rec["rev"]:
            wrong.append("A and B must be exported at the same revision")
        want_compiler = "msvc" if spec.get("same_compiler", True) else "clang-cl"
        if b_rec["compiler"] != want_compiler:
            wrong.append(f"B must be built by {want_compiler} (got {b_rec['compiler']})")
    if wrong:
        say("INEVALUABLE", cell, "; ".join(wrong))
        return 2

    a_bank = manifest(a_inst, "corpus")
    semb = find_semb(b_inst)
    stem = a_inst / "bank" / "corpus"
    rows = [json.loads(l) for l in corpus_jsonl(args.work).read_text(encoding="utf-8").splitlines()]
    base = ["--model", args.model, "--tokenizer", args.tokenizer]

    if spec["kind"] == "refuse":
        if args.leg == "p":
            b_fp = manifest(b_inst, "identity")["encoder_fingerprint"]
            moved = a_bank["encoder_fingerprint"] != b_fp
            detail = f"bank encoder_fingerprint={a_bank['encoder_fingerprint']} final encoder_fingerprint={b_fp}"
        else:
            b_id = manifest(b_inst, "identity")
            moved = a_bank[spec["moves"]] != b_id[spec["moves"]]
            detail = "; ".join(f"{c}: {'moved' if a_bank[c] != b_id[c] else 'equal'}" for c in COMPONENTS)
        if not moved and args.leg != "p":
            say("INEVALUABLE", f"{cell} precondition: the construction moves {spec['moves']}",
                f"{detail} -- replace the construction; an edit that leaves it equal is never passed")
            return 2
        # For (p) the two installations are unedited exports of two
        # revisions; an equal fingerprint is the product failing the leg (the
        # final fingerprint does not differ from the provisional one), so it
        # is RED and the query still runs to show what a user receives.
        say("PASS" if moved else "FAIL", f"{cell} precondition: {spec['moves']} differs between the installations",
            detail)
        proc = run([semb, "query", stem, rows[0]["text"], "--hex", *base])
        lines = [l.rstrip("\r") for l in proc.stderr.splitlines()]
        ok = proc.returncode == 1 and lines.count(MISMATCH_LINE) == 1 and "VECTOR_HEX=" not in proc.stdout
        say("PASS" if ok else "FAIL", f"{cell} {b_rec['name']} refuses {a_rec['name']}'s bank at query open by name",
            f"exit={proc.returncode}; vector emitted={'VECTOR_HEX=' in proc.stdout}; "
            f"'semb' stderr lines={[l for l in lines if l.startswith('semb')]}")
        return 0 if (ok and moved) else 1

    # Accept legs (i) and (vi).
    b_id = manifest(b_inst, "identity")
    unequal = [c for c in COMPONENTS + ("encoder_fingerprint",) if a_bank[c] != b_id[c]]
    say("PASS" if not unequal else "FAIL", f"{cell} fingerprint equal across the two installations",
        "all five components and encoder_fingerprint equal" if not unequal else f"unequal: {unequal}")

    # D-SLM7217 (1): both readings plan gap G-1 (TE-264) left open, since a
    # query vector (carries the query-prefix literal) and a bank row (does
    # not) are never the same bytes even on an identical pair.
    # bake() reads its install directory off args.name (the "bake"/"identity"
    # phases' own argument); the "leg" phase carries bank_from/query_on
    # instead, so B's own name is passed through a namespace bake() can read.
    b_stem = bake(argparse.Namespace(work=args.work, name=args.query_on, model=args.model, tokenizer=args.tokenizer),
                  "corpus", corpus_jsonl(args.work))
    a_header, a_payload = read_wvbank(stem)
    b_header, b_payload = read_wvbank(b_stem)
    rows_equal = (a_header.get("ids") == b_header.get("ids") and a_header.get("dims") == b_header.get("dims")
                  and a_header.get("dtype") == b_header.get("dtype") and a_payload == b_payload)
    say("PASS" if rows_equal else "FAIL", f"{cell} B's baked rows over the corpus are byte-identical to A's",
        f"ids equal={a_header.get('ids') == b_header.get('ids')}; dims {a_header.get('dims')} vs "
        f"{b_header.get('dims')}; dtype {a_header.get('dtype')} vs {b_header.get('dtype')}; "
        f"payload bytes {len(a_payload)} vs {len(b_payload)}, equal={a_payload == b_payload}")

    a_semb = find_semb(a_inst)
    query_stdin = "".join(r["text"] + "\n" for r in rows)
    proc_a = run([a_semb, "query", "--stdin", stem, "--hex", *base], stdin=query_stdin, timeout=3600)
    emitted_a = re.findall(r"^VECTOR_HEX=[0-9a-f]+$", proc_a.stdout, re.M)
    accepted_a = proc_a.returncode == 0 and len(emitted_a) == len(rows)

    proc = run([semb, "query", "--stdin", stem, "--hex", *base], stdin=query_stdin, timeout=3600)
    emitted = re.findall(r"^VECTOR_HEX=[0-9a-f]+$", proc.stdout, re.M)
    accepted = proc.returncode == 0 and len(emitted) == len(rows)
    say("PASS" if accepted else "FAIL", f"{cell} VECTOR_EMITTED for every one of the {len(rows)} documents on "
        f"{b_rec['name']}", f"exit={proc.returncode}; vectors={len(emitted)}; stderr tail={proc.stderr[-300:]!r}")

    query_vectors_equal = accepted and accepted_a and emitted_a == emitted
    say("PASS" if query_vectors_equal else "FAIL", f"{cell} B's query vectors for the corpus texts are "
        f"byte-identical to A's",
        f"A: accepted={accepted_a}, vectors={len(emitted_a)}; B: accepted={accepted}, vectors={len(emitted)}; "
        f"equal={(emitted_a == emitted) if (accepted_a and accepted) else 'not compared -- one side did not emit '
        'a vector for every document'}")

    return 1 if (unequal or not accepted or not rows_equal or not query_vectors_equal) else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work", type=Path, default=ROOT / "build" / "_c35")
    sub = ap.add_subparsers(dest="phase", required=True)
    p = sub.add_parser("install")
    p.add_argument("--name", required=True)
    p.add_argument("--rev", default="HEAD")
    p.add_argument("--compiler", choices=["msvc", "clang-cl"], default="msvc")
    p.add_argument("--construction", choices=["none", "epilogue", "engine", "cert-doc"], default="none")
    p.add_argument("--engine-source", default=os.environ.get("SEMB_TEST_ENGINE_SOURCE", ""))
    p.add_argument("--clang-cl", default="C:/Program Files/LLVM/bin/clang-cl.exe")
    for name in ("bake", "identity"):
        q = sub.add_parser(name)
        q.add_argument("--name", required=True)
        q.add_argument("--model", required=True)
        q.add_argument("--tokenizer", required=True)
    q = sub.add_parser("leg")
    q.add_argument("--leg", required=True, choices=sorted(LEGS))
    q.add_argument("--bank-from", required=True)
    q.add_argument("--query-on", required=True)
    q.add_argument("--model", required=True)
    q.add_argument("--tokenizer", required=True)
    args = ap.parse_args(argv)
    args.work = args.work.resolve()
    args.work.mkdir(parents=True, exist_ok=True)
    if args.phase == "install" and not args.engine_source:
        from importlib import import_module
        sys.path.insert(0, str(ROOT / "tools" / "pin-superslm"))
        args.engine_source = import_module("pin_superslm").DEFAULT_REMOTE
    return {"install": cmd_install, "bake": cmd_bake, "identity": cmd_identity, "leg": cmd_leg}[args.phase](args)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit as exc:
        if isinstance(exc.code, str):
            state = exc.code.split(":", 1)[0] if exc.code.startswith(("RED", "INEVALUABLE")) else "ERROR"
            print(f"[{state}] {exc.code}")
            raise SystemExit(1 if state in ("RED", "ERROR") else 2)
        raise
