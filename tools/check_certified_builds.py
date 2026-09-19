"""C42's release checker for a certification package (plan sec 4.1a, sec 8 C42;
D-SLM7206, D-SLM7217).

    python tools/check_certified_builds.py --root <package root>

reads `<root>/docs/certified-builds.json`, `<root>/superslm.lock` (lines `tag=`,
`commit=`, `tree=`; `tree` is the engine_tree_sha) and each member's evidence at
`<root>/<pairwiseProofs[].evidence>/<build id>/`: `row-digests.tsv`,
`token-id-digest.txt` and `run.json`. Run against the repository root it checks
the committed package.

Three clauses, each refused on its own output line:

  C42 (a)  Membership. The document names at least two builds with unique ids,
           and every one of the n(n-1)/2 unordered member pairs has exactly one
           `pairwiseProofs` entry, naming two distinct members. For each pair,
           the two members' row digests -- each the SHA-256 of that member's own
           `row-digests.tsv` -- are equal. Transitivity is never assumed: every
           pair is checked on its own evidence.
  C42 (b)  Evidence. Every digest the package records is recomputed from the
           members' evidence files, never taken from the JSON: each member's
           `run.json` names that member and records the SHA-256 of its
           `row-digests.tsv` and the digest in its `token-id-digest.txt`; each
           pair's `rowDigest` and `tokenIdDigest` equal both members'
           recomputed values; each evidence path stays inside the root.
  C42 (c)  Engine pin. Each member run's `enginePin` equals the document's
           `enginePin`, and the document's equals the lock's.

C42 (d) is not this checker's: the runtime equality of certification_epoch to
the compiled-in document's bytes belongs to the runtime test
(tests/te264_fingerprint_final_check.py, cells epoch and epoch-edit).

Output: one `REFUSED C42(x): ...` line per refused clause, naming every failing
item; `ACCEPTED ...` when nothing is refused. Exit 0 accepted, 1 refused (a
package that cannot be read at all is refused with a `REFUSED C42: ...` line).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from itertools import combinations
from pathlib import Path

HEX64 = re.compile(r"^[0-9a-f]{64}$")
PIN_FIELDS = ("tag", "commit", "engine_tree_sha")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_lock(path: Path) -> dict:
    fields = dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line)
    return {"tag": fields.get("tag"), "commit": fields.get("commit"), "engine_tree_sha": fields.get("tree")}


def pin_of(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    return {k: value.get(k) for k in PIN_FIELDS}


class Evidence:
    """One member's evidence directory, recomputed from its files."""

    def __init__(self, root: Path, evidence: str, member: str) -> None:
        self.member = member
        self.problems: list[str] = []
        self.row_digest = self.token_digest = None
        self.run: dict | None = None
        base = (root / evidence).resolve()
        directory = (base / member).resolve()
        if root.resolve() not in directory.parents:
            self.problems.append(f"{member}: evidence path {evidence!r} leaves the package root")
            return
        try:
            tsv = (directory / "row-digests.tsv").read_bytes()
            token = (directory / "token-id-digest.txt").read_bytes().decode("utf-8")
            self.run = json.loads((directory / "run.json").read_bytes().decode("utf-8"))
        except (OSError, ValueError) as exc:
            self.problems.append(f"{member}: evidence at {directory} is unreadable: {exc}")
            return
        lines = tsv.decode("utf-8").split("\n")
        if not tsv or lines[-1] != "" or any(len(l.split("\t")) != 2 or not HEX64.match(l.split("\t")[1])
                                             for l in lines[:-1]):
            self.problems.append(f"{member}: row-digests.tsv is not LF-terminated '<id>\\t<sha256>' lines")
        self.row_digest = sha256(tsv)
        self.token_digest = token.strip()
        if not HEX64.match(self.token_digest) or token != self.token_digest + "\n":
            self.problems.append(f"{member}: token-id-digest.txt is not one SHA-256 line")
        if not isinstance(self.run, dict):
            self.problems.append(f"{member}: run.json is not an object")
            self.run = None
            return
        if self.run.get("buildId") != member:
            self.problems.append(f"{member}: run.json buildId is {self.run.get('buildId')!r}")
        if self.run.get("rowDigest") != self.row_digest:
            self.problems.append(f"{member}: run.json rowDigest {self.run.get('rowDigest')} != SHA-256 of "
                                 f"row-digests.tsv {self.row_digest}")
        if self.run.get("tokenIdDigest") != self.token_digest:
            self.problems.append(f"{member}: run.json tokenIdDigest {self.run.get('tokenIdDigest')} != "
                                 f"token-id-digest.txt {self.token_digest}")


def check(root: Path) -> dict[str, list[str]]:
    refused: dict[str, list[str]] = {"a": [], "b": [], "c": []}
    doc = json.loads((root / "docs" / "certified-builds.json").read_bytes().decode("utf-8"))
    lock = read_lock(root / "superslm.lock")
    builds = doc.get("builds") if isinstance(doc, dict) else None
    proofs = doc.get("pairwiseProofs") if isinstance(doc, dict) else None
    if not isinstance(builds, list) or not isinstance(proofs, list):
        raise ValueError("the document carries no builds/pairwiseProofs arrays")

    # (a) membership: every unordered pair of enumerated members, exactly once.
    members = [b.get("id") if isinstance(b, dict) else None for b in builds]
    if any(not isinstance(m, str) or not m for m in members) or len(set(members)) != len(members):
        refused["a"].append(f"build ids are not unique non-empty strings: {members}")
    member_set = {m for m in members if isinstance(m, str)}
    if len(member_set) < 2:
        refused["a"].append(f"{len(member_set)} member(s); a certified set has at least two")
    seen: dict[frozenset, int] = {}
    for i, proof in enumerate(proofs):
        a, b = (proof.get("a"), proof.get("b")) if isinstance(proof, dict) else (None, None)
        if a not in member_set or b not in member_set or a == b:
            refused["a"].append(f"pairwiseProofs[{i}] names {a!r} and {b!r}, not two distinct members")
            continue
        seen[frozenset((a, b))] = seen.get(frozenset((a, b)), 0) + 1
    for a, b in combinations(sorted(member_set), 2):
        count = seen.get(frozenset((a, b)), 0)
        if count != 1:
            refused["a"].append(f"pair ({a}, {b}) has {count} pairwiseProofs entries (exactly one required)")

    # (b) evidence: every recorded digest recomputed from the members' files.
    evidence: dict[tuple[str, str], Evidence] = {}
    for i, proof in enumerate(proofs):
        if not isinstance(proof, dict) or not isinstance(proof.get("evidence"), str):
            refused["b"].append(f"pairwiseProofs[{i}] names no evidence path")
            continue
        for side in ("a", "b"):
            member = proof.get(side)
            if member not in member_set:
                continue
            key = (proof["evidence"], member)
            if key not in evidence:
                evidence[key] = Evidence(root, proof["evidence"], member)
                refused["b"].extend(evidence[key].problems)
            ev = evidence[key]
            if ev.row_digest is not None and proof.get("rowDigest") != ev.row_digest:
                refused["b"].append(f"pairwiseProofs[{i}] ({proof.get('a')}, {proof.get('b')}) rowDigest "
                                    f"{proof.get('rowDigest')} != {member}'s recomputed {ev.row_digest}")
            if ev.token_digest is not None and proof.get("tokenIdDigest") != ev.token_digest:
                refused["b"].append(f"pairwiseProofs[{i}] ({proof.get('a')}, {proof.get('b')}) tokenIdDigest "
                                    f"{proof.get('tokenIdDigest')} != {member}'s recomputed {ev.token_digest}")
        # (a)'s equal-rowDigest half: the two members' own recomputed digests.
        ea = evidence.get((proof["evidence"], proof.get("a")))
        eb = evidence.get((proof["evidence"], proof.get("b")))
        if ea and eb and ea.row_digest and eb.row_digest and ea.row_digest != eb.row_digest:
            refused["a"].append(f"pair ({proof.get('a')}, {proof.get('b')}): the members' row-digests.tsv differ "
                                f"({ea.row_digest} vs {eb.row_digest})")

    # (c) engine pin: every run, the document and the lock name one pin.
    doc_pin = pin_of(doc.get("enginePin"))
    if doc_pin != lock:
        refused["c"].append(f"document enginePin {doc_pin} != superslm.lock {lock}")
    for ev in evidence.values():
        if ev.run is None:
            continue
        run_pin = pin_of(ev.run.get("enginePin"))
        if run_pin != doc_pin:
            refused["c"].append(f"{ev.member}: run enginePin {run_pin} != document enginePin {doc_pin}")
        if run_pin != lock:
            refused["c"].append(f"{ev.member}: run enginePin {run_pin} != superslm.lock {lock}")
    return refused


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, required=True, help="the package root (the repository root for the "
                                                              "committed package)")
    args = ap.parse_args(argv)
    try:
        refused = check(args.root)
    except (OSError, ValueError, AttributeError) as exc:
        print(f"REFUSED C42: the package at {args.root} cannot be read: {exc}")
        return 1
    failed = False
    for clause in ("a", "b", "c"):
        if refused[clause]:
            failed = True
            print(f"REFUSED C42({clause}): " + "; ".join(refused[clause]))
    if not failed:
        print(f"ACCEPTED: {args.root / 'docs' / 'certified-builds.json'} -- every member pair present and "
              f"agreeing on recomputed evidence, at the lock's engine pin")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
