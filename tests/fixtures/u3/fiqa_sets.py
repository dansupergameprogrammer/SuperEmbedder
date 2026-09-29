"""tests/fixtures/u3/fiqa_sets.py -- U3's two FiQA inputs (te266 C10 (h) and C11;
the planner's U3 build-time rulings 3 and 4), and the script that mints the
query set.

THE DOCUMENTS: fiqa-long80 (D-SLM7873). One file serves C10 (h) and C11's
tok/s leg. It is not copied into this repository: it lives in the records
repository at Claude/Brunel/te439-runs/fiqa-long80/fiqa-long80.jsonl (commit
9fa21eb9), 80 documents, 15-511 content tokens, 11,964 in total. Every reader
checks its sha256 against FIQA_LONG80_SHA256 before it runs and refuses on a
mismatch. Obtain it with
  git -C <records repo> show 9fa21eb9:Claude/Brunel/te439-runs/fiqa-long80/fiqa-long80.jsonl > fiqa-long80.jsonl

THE QUERIES: C11's 100-query set, minted here.
  RULE  the first 100 queries, in file order, of mteb/fiqa's queries at
        revision 5e59eeb3a7df6b85882112b747008547c21587ea (the revision
        fiqa-long80 was drawn from).
  FORM  one line per query, {"id": "fiqa-q-<_id>", "text": <text>},
        json.dumps(ensure_ascii=False), UTF-8, LF after every line. A query
        whose text holds a CR or LF is refused, not altered: C11's query leg
        feeds the set through a line-delimited `semb query --stdin` session.
  SHA   QUERIES100_SHA256 below is the recorded sha256 of the output. It is
        EMPTY until the set is minted on a host that can reach Hugging Face
        (the cloud build cannot). While it is empty, C11's query leg reports
        MISSING PREREQUISITE. After the first mint, commit the printed sha256
        into QUERIES100_SHA256; a second mint must print the same value.

USAGE
  python fiqa_sets.py mint --out <fiqa-queries100.jsonl> --from-hub
      datasets.load_dataset("mteb/fiqa", "queries", revision=QUERIES_REVISION);
      the dataset's own row order is the file order.
  python fiqa_sets.py mint --out <file> --source <local copy>
      the same queries from a local file: a Hugging Face datasets cache arrow
      stream (the form select_fiqa_long80.py read the corpus in), a .parquet,
      or a .jsonl / .jsonl.gz with `_id` and `text` per line.
  python fiqa_sets.py check-queries <file>     the sha256 slot's verdict
  python fiqa_sets.py check-long80 <file>      fiqa-long80's sha256 verdict
  python fiqa_sets.py selftest                 the mint's commissioning, portable
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import tempfile
from pathlib import Path

FIQA_LONG80_SHA256 = "831cf2ed0718dede12e7129b74f15b7ddcc8c5d3a2e10cff0f7b1c50ab1da896"
FIQA_LONG80_ROWS = 80
QUERIES_DATASET = "mteb/fiqa"
QUERIES_REVISION = "5e59eeb3a7df6b85882112b747008547c21587ea"
QUERIES_COUNT = 100
# The recorded sha256 of the minted fiqa-queries100.jsonl (minted twice on the dev box with
# --from-hub, byte-identical). EMPTY would mean not yet minted.
QUERIES100_SHA256 = "6e14d9c710438c598f2cb27496e4e388c199f9e79f706b4b3c2586ceab6b7acd"


class Refused(Exception):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---- verdicts the drivers read: (state, detail), state PASS / FAIL / MISSING ---
def check_long80(path: Path | str | None) -> tuple[str, str]:
    if not path or not Path(path).is_file():
        return "MISSING", (f"fiqa-long80.jsonl is not given or absent ({path or 'unset'}); it lives in the records "
                           "repository, Claude/Brunel/te439-runs/fiqa-long80/ (commit 9fa21eb9)")
    got = sha256_file(Path(path))
    if got != FIQA_LONG80_SHA256:
        return "FAIL", f"{path}: sha256 {got}, want fiqa-long80's {FIQA_LONG80_SHA256}; refused before any run"
    rows = [x for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(rows) != FIQA_LONG80_ROWS:
        return "FAIL", f"{path}: {len(rows)} rows, want {FIQA_LONG80_ROWS}"
    return "PASS", f"fiqa-long80 sha256 {got}, {len(rows)} rows"


def check_queries(path: Path | str | None, want: str | None = None) -> tuple[str, str]:
    want = QUERIES100_SHA256 if want is None else want
    if not want:
        return "MISSING", ("the 100-query set's sha256 slot (tests/fixtures/u3/fiqa_sets.py QUERIES100_SHA256) is "
                           "unfilled: mint it with `fiqa_sets.py mint --from-hub` on a host that reaches Hugging "
                           "Face and commit the printed sha256")
    if not path or not Path(path).is_file():
        return "MISSING", f"the 100-query set is not given or absent ({path or 'unset'})"
    got = sha256_file(Path(path))
    if got != want:
        return "FAIL", f"{path}: sha256 {got}, want the recorded {want}; refused before any run"
    return "PASS", f"fiqa-queries100 sha256 {got}"


# ---- the mint -----------------------------------------------------------------
def _rows_from_file(src: Path) -> list[tuple[str, str]]:
    name = src.name.lower()
    if name.endswith(".jsonl") or name.endswith(".jsonl.gz"):
        opener = gzip.open if name.endswith(".gz") else open
        with opener(src, "rt", encoding="utf-8") as f:
            return [(str(o["_id"]), o["text"]) for o in (json.loads(x) for x in f if x.strip())]
    import pyarrow as pa  # only the arrow / parquet forms need it

    if name.endswith(".parquet"):
        import pyarrow.parquet as pq

        table = pq.read_table(str(src))
    else:
        with pa.memory_map(str(src)) as m:
            table = pa.ipc.open_stream(m).read_all()
    return list(zip(map(str, table.column("_id").to_pylist()), table.column("text").to_pylist()))


def _rows_from_hub() -> list[tuple[str, str]]:
    import datasets

    d = datasets.load_dataset(QUERIES_DATASET, "queries", revision=QUERIES_REVISION)
    split = d["queries"] if "queries" in d else (d[next(iter(d))] if len(d) == 1 else None)
    if split is None:
        raise Refused(f"{QUERIES_DATASET}@{QUERIES_REVISION} 'queries' has splits {list(d)}; none is the queries")
    return [(str(r["_id"]), r["text"]) for r in split]


def render(rows: list[tuple[str, str]]) -> bytes:
    if len(rows) < QUERIES_COUNT:
        raise Refused(f"the source holds {len(rows)} queries, fewer than {QUERIES_COUNT}")
    out = []
    for qid, text in rows[:QUERIES_COUNT]:
        if not isinstance(text, str) or not text.strip():
            raise Refused(f"query {qid}: empty text")
        if "\n" in text or "\r" in text:
            raise Refused(f"query {qid}: its text holds a line break, which C11's line-delimited --stdin session "
                          "cannot carry (the rule takes queries unaltered)")
        out.append(json.dumps({"id": f"fiqa-q-{qid}", "text": text}, ensure_ascii=False) + "\n")
    return "".join(out).encode("utf-8")


def mint(out: Path, source: Path | None) -> str:
    rows = _rows_from_file(source) if source else _rows_from_hub()
    data = render(rows)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


# ---- commissioning (portable: jsonl / jsonl.gz sources, no network) ------------
def selftest() -> int:
    ok = True

    def verdict(passed: bool, cell: str, observed: str) -> None:
        nonlocal ok
        ok = ok and passed
        print(f"[{'PASS' if passed else 'FAIL'}] {cell}: {observed}")

    def refused(fn) -> str:
        try:
            fn()
            return ""
        except Refused as ex:
            return str(ex)

    with tempfile.TemporaryDirectory(prefix="u3_fiqa_") as tmp:
        t = Path(tmp)
        src = [{"_id": str(9000 - i), "text": f"query number {i} café “quoted”"} for i in range(130)]
        (t / "q.jsonl").write_text("".join(json.dumps(r) + "\n" for r in src), encoding="utf-8")
        with gzip.open(t / "q.jsonl.gz", "wt", encoding="utf-8") as f:
            f.write("".join(json.dumps(r) + "\n" for r in src))
        s1 = mint(t / "a.jsonl", t / "q.jsonl")
        s2 = mint(t / "b.jsonl", t / "q.jsonl")
        s3 = mint(t / "c.jsonl", t / "q.jsonl.gz")
        verdict(s1 == s2 == s3, "mint is deterministic and source-form independent", f"{s1[:16]} x3")
        lines = (t / "a.jsonl").read_text(encoding="utf-8").split("\n")
        got = [json.loads(x) for x in lines if x]
        verdict(len(got) == 100 and lines[-1] == "" and [g["id"] for g in got] == [f"fiqa-q-{r['_id']}" for r in
                src[:100]] and [g["text"] for g in got] == [r["text"] for r in src[:100]],
                "the first 100 in file order (not sorted by id), text unaltered, LF-terminated",
                f"{len(got)} rows, first {got[0]['id']}, last {got[-1]['id']}")
        verdict("café" in (t / "a.jsonl").read_text(encoding="utf-8"), "non-ASCII written as UTF-8, unescaped",
                "ensure_ascii=False")
        st, _ = check_queries(t / "a.jsonl", want=s1)
        verdict(st == "PASS", "check-queries must-accept: the recorded sha256", st)
        st, d = check_queries(t / "a.jsonl", want="0" * 64)
        verdict(st == "FAIL", "check-queries must-reject: a different recorded sha256", d[:80])
        st, d = check_queries(t / "a.jsonl", want="")
        verdict(st == "MISSING", "check-queries: an unfilled slot is MISSING PREREQUISITE, never PASS", st)
        (t / "short.jsonl").write_text("".join(json.dumps(r) + "\n" for r in src[:99]), encoding="utf-8")
        why = refused(lambda: mint(t / "x.jsonl", t / "short.jsonl"))
        verdict(bool(why), "mint must-reject: 99 queries", why or "ACCEPTED")
        bent = [dict(r) for r in src]
        bent[57]["text"] = "two\nlines"
        (t / "nl.jsonl").write_text("".join(json.dumps(r) + "\n" for r in bent), encoding="utf-8")
        why = refused(lambda: mint(t / "x.jsonl", t / "nl.jsonl"))
        verdict(bool(why), "mint must-reject: a line break inside one of the first 100", why or "ACCEPTED")
        bent[57]["text"] = "two lines"
        bent[117]["text"] = "past\nthe cut"
        (t / "nl2.jsonl").write_text("".join(json.dumps(r) + "\n" for r in bent), encoding="utf-8")
        why = refused(lambda: mint(t / "x.jsonl", t / "nl2.jsonl"))
        verdict(not why, "mint must-accept: a line break past the first 100 is not read", why or "ACCEPTED")
        (t / "l80.jsonl").write_text("x\n", encoding="utf-8")
        st, d = check_long80(t / "l80.jsonl")
        verdict(st == "FAIL", "check-long80 must-reject: a file that is not fiqa-long80", d[:80])
        st, _ = check_long80(None)
        verdict(st == "MISSING", "check-long80: an unset path is MISSING PREREQUISITE", st)
    verdict(len(FIQA_LONG80_SHA256) == 64 and len(QUERIES_REVISION) == 40, "the recorded identifiers are whole",
            f"long80 {FIQA_LONG80_SHA256[:8]}, revision {QUERIES_REVISION[:8]}, queries slot "
            f"{QUERIES100_SHA256 or '(unfilled)'}")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mint")
    m.add_argument("--out", required=True)
    g = m.add_mutually_exclusive_group(required=True)
    g.add_argument("--from-hub", action="store_true")
    g.add_argument("--source")
    sub.add_parser("check-queries").add_argument("path")
    sub.add_parser("check-long80").add_argument("path")
    sub.add_parser("selftest")
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        return selftest()
    if a.cmd == "mint":
        try:
            sha = mint(Path(a.out), Path(a.source) if a.source else None)
        except Refused as ex:
            print(f"REFUSED: {ex}")
            return 1
        src = f"source {a.source} sha256 {sha256_file(Path(a.source))}" if a.source else \
            f"source {QUERIES_DATASET}@{QUERIES_REVISION}"
        print(f"minted {a.out}: {QUERIES_COUNT} queries, sha256 {sha} ({src})")
        if QUERIES100_SHA256 and sha != QUERIES100_SHA256:
            print(f"MISMATCH: the recorded QUERIES100_SHA256 is {QUERIES100_SHA256}")
            return 1
        if not QUERIES100_SHA256:
            print("record it: set QUERIES100_SHA256 in tests/fixtures/u3/fiqa_sets.py to the sha256 above, and commit")
        return 0
    st, detail = (check_queries if a.cmd == "check-queries" else check_long80)(a.path)
    print(f"[{'MISSING PREREQUISITE' if st == 'MISSING' else st}] {a.cmd}: {detail}")
    return {"PASS": 0, "FAIL": 1, "MISSING": 77}[st]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
