#!/usr/bin/env python3
"""tools/pin-superslm/verify_provenance.py — invoked by cmake/EngineGuards.cmake
at EVERY configure. Reads whatever provenance.json currently sits under the
found engine's install prefix, and recomputes engine_tree_sha fresh from the
ACTUAL BYTES on disk right now — never trusting the manifest's own declared
digest — using the identical formula pin_superslm.py used to write it
(provenance_lib.digest_members). This is "the digest recomputed at configure
from the prefix's own bytes" (§4.1).

Always exits 0 and prints one JSON object to stdout; cmake/EngineGuards.cmake
does all the policy branching (which discrepancy maps to which named error).
Keeping this script exit-0-always keeps a real execute_process() failure
(this script crashing) distinguishable, in the CMake code, from an honest
"the bytes disagree" reading — CMake checks RESULT_VARIABLE for the former
and the JSON body for the latter.

Fields on success:
  provenance_present:     bool
  provenance:              the raw parsed provenance.json object, or null
  recomputed_engine_tree_sha:  digest recomputed from the CURRENT on-disk
                                bytes under the prefix, or null if provenance
                                was absent (nothing to recompute against)
  member_read_errors:      paths a member claimed to cover but that are not
                            currently readable on disk (§8 C34-style "covered
                            file missing")
  dirty_members:            compiled-root members (TE-65 F-3) whose CURRENT
                             on-disk SHA-256 disagrees with the
                             tag_content_sha256 pin_superslm.py recorded from
                             git's own tag content at pin time -- computed
                             fresh on every call, never read from the
                             manifest's own `clean` flag, which a hand-edit
                             could otherwise satisfy trivially
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from provenance_lib import digest_members  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: verify_provenance.py <engine_install_prefix>"}))
        return 0
    prefix = Path(sys.argv[1]).resolve()
    manifest_path = prefix / "share" / "superslm-provenance" / "provenance.json"

    result = {
        "provenance_present": False,
        "provenance": None,
        "recomputed_engine_tree_sha": None,
        "member_read_errors": [],
        "dirty_members": [],
    }

    if not manifest_path.exists():
        print(json.dumps(result))
        return 0

    try:
        provenance = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — reported to CMake as a JSON parse failure
        result["provenance_present"] = True
        result["parse_error"] = str(exc)
        print(json.dumps(result))
        return 0

    result["provenance_present"] = True
    result["provenance"] = provenance

    members = []
    errors = []
    dirty_members = []
    for m in provenance.get("members_index", []):
        root = m["root"]
        relpath = m["path"]
        if root == "compiled":
            actual = prefix / "share" / "superslm-provenance" / "compiled" / relpath
        elif root == "installed":
            actual = prefix / relpath
        else:
            errors.append(f"unknown root '{root}' for {relpath}")
            continue
        if not actual.exists():
            errors.append(f"{root}:{relpath} (missing at {actual})")
            continue
        content = actual.read_bytes()
        members.append((root, relpath, content))
        if root == "compiled":
            # TE-67 N-1: a missing KEY (a hand-deleted manifest field) and a
            # null VALUE (a file the clone added that the tag has no
            # content for) are now the SAME refusal, not two different
            # readings -- "cannot be verified against the tag" is the
            # condition, and both shapes produce it. The prior code's
            # `expected is not None` treated a missing/null field as
            # nothing to check, which a hand-edit could produce by deleting
            # one JSON key, and which an ordinary uncommitted new file
            # produced with no edit at all (git_clean_check never recorded
            # a tag_content_sha256 for a path the tag doesn't have).
            if "tag_content_sha256" not in m or m["tag_content_sha256"] is None:
                dirty_members.append(relpath)
            elif hashlib.sha256(content).hexdigest() != m["tag_content_sha256"]:
                dirty_members.append(relpath)

    result["member_read_errors"] = errors
    result["dirty_members"] = dirty_members
    if not errors and members:
        result["recomputed_engine_tree_sha"] = digest_members(members)

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
