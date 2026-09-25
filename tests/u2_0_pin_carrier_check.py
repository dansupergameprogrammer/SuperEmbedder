"""U2 cloud build: U2-0 item 1's pin-carrier cell (te267 sec 5 U2-0, "The
pin-carrier cell").

The tokenizer manifest's `converter.engine_tag` and `converter.engine_commit`
must equal `superslm.lock`'s `tag=` and `commit=`, and the README's pin word
must equal the lock's `tag=`. Nothing else holds those two files to the lock.

Must-reject, mutation-proven in this cell on every run:
  - the v1.7.0 step's tip (7c706ac), read from git: its lock at v1.7.0 with
    its README (v1.5.0) and its manifest (v1.5.0) both stale;
  - this tree with the manifest's converter fields edited back to the previous
    tag (v1.7.0, d35a8fab...), the README untouched;
  - this tree with the README's pin word edited back to v1.7.0, the manifest
    untouched.
Each must be refused, or the cell is dead. Mutations live only in memory.

Green on this tree (both files moved with the v1.7.1 step); it is U2-0 item
1's check from the v1.8.0 step on, and a user observes its absence as a public
README naming the wrong engine.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = "tests/fixtures/tokenizer/qwen3-embedding-0.6b-tokenizer.manifest.json"
PREV_TIP = "7c706ac"
PREV_TAG = "v1.7.0"
PREV_COMMIT = "d35a8fab4e39101c1d81298e31baa401b5465298"
PIN_WORD = re.compile(r"pinned to SuperSLM\s+(v\d+\.\d+\.\d+)")


def lock_fields(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def check(lock_text: str, manifest_text: str, readme_text: str) -> list[str]:
    """The cell's rule. Returns the refusals (empty = accepted)."""
    lock = lock_fields(lock_text)
    refusals = []
    try:
        conv = json.loads(manifest_text)["converter"]
    except (ValueError, KeyError, TypeError):
        return ["tokenizer manifest has no converter object"]
    if conv.get("engine_tag") != lock.get("tag"):
        refusals.append(f"manifest converter.engine_tag {conv.get('engine_tag')} != lock tag {lock.get('tag')}")
    if conv.get("engine_commit") != lock.get("commit"):
        refusals.append(f"manifest converter.engine_commit {conv.get('engine_commit')} != lock commit "
                        f"{lock.get('commit')}")
    words = PIN_WORD.findall(readme_text)
    if len(words) != 1:
        refusals.append(f"README carries {len(words)} pin words (want exactly one 'pinned to SuperSLM vX.Y.Z')")
    elif words[0] != lock.get("tag"):
        refusals.append(f"README pin word {words[0]} != lock tag {lock.get('tag')}")
    return refusals


def git_show(rev: str, path: str) -> str | None:
    r = subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"{rev}:{path}"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.stdout if r.returncode == 0 else None


def main() -> int:
    fails = 0

    def verdict(ok: bool, cell: str, detail: str) -> None:
        nonlocal fails
        fails += 0 if ok else 1
        print(f"[{'PASS' if ok else 'FAIL'}] {cell}: {detail}")

    lock = (REPO_ROOT / "superslm.lock").read_text(encoding="utf-8")
    manifest = (REPO_ROOT / MANIFEST).read_text(encoding="utf-8")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    live = check(lock, manifest, readme)
    verdict(not live, "pin-carrier: manifest converter fields and README pin word equal the lock",
            "; ".join(live) or f"all equal {lock_fields(lock).get('tag')}")

    # Must-reject 1: the v1.7.0 step's tip, where both were stale with the sweep green.
    prev = [git_show(PREV_TIP, p) for p in ("superslm.lock", MANIFEST, "README.md")]
    if any(p is None for p in prev):
        verdict(False, f"pin-carrier must-reject: the {PREV_TAG} step's tip {PREV_TIP}",
                "not readable from git in this clone (the construction needs it)")
    else:
        r = check(*prev)
        verdict(len(r) >= 2, f"pin-carrier must-reject: the {PREV_TAG} step's tip {PREV_TIP} is refused",
                "; ".join(r) or "ACCEPTED (the cell is dead)")
    # Must-reject 2: the manifest alone edited back to the previous tag.
    m = json.loads(manifest)
    m["converter"]["engine_tag"] = PREV_TAG
    m["converter"]["engine_commit"] = PREV_COMMIT
    r = check(lock, json.dumps(m), readme)
    verdict(bool(r), f"pin-carrier must-reject: manifest converter fields edited back to {PREV_TAG}",
            "; ".join(r) or "ACCEPTED (the cell is dead)")
    # Must-reject 3: the README alone edited back to the previous tag.
    stale = PIN_WORD.sub(lambda mm: mm.group(0).replace(mm.group(1), PREV_TAG), readme)
    r = check(lock, manifest, stale)
    verdict(bool(r), f"pin-carrier must-reject: README pin word edited back to {PREV_TAG}",
            "; ".join(r) or "ACCEPTED (the cell is dead)")
    print(f"TOTAL fail={fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
