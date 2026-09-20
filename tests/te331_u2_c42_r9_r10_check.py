"""tests/te331_u2_c42_r9_r10_check.py -- TE-331 (U2-3/U2-7 red suite): R9's
append tool (C58), R10's evidence-half tool (C59), and the presence of
C42's extended clauses (b'/e/f/g/h) that U2-3 specifies over today's
three-clause checker (`Claude/Plans/te267-u2-release-plan.md` sec 5 U2-3
items 6, 10, 11, 12; sec 5 U2-7 items 8, 9).

GROUNDING, RE-CONFIRMED BY DIRECT READ AT `fca421b` (matching the plan's
own TE-337/TE-339 grounding, and the coverage audit's F1 correction that
R10's tools carry NO probe evidence anywhere -- both R9's and R10's tools
are genuinely absent, not merely under-exercised):

  - `tools/append_certified_build.py` does not exist.
  - `tools/check_certified_builds_evidence.py` does not exist.
  - `cmake/CertifiedBuilds.cmake` is 50 lines and contains no evidence-half
    logic at all (no `pairwiseProofs`, no `UNPROVEN` refusal) -- U2-3 item
    11's own configure-time check has not landed either, so R10's "route
    CMake's inline check through the standalone tool instead of a second
    hand-written copy" has nothing yet to route.
  - `tools/check_certified_builds.py` implements clauses (a), (b) and (c)
    only: `python -c "import tools.check_certified_builds as m; ..."`
    against its own `check()` function returns exactly the three-key dict
    `{"a": [...], "b": [...], "c": [...]}` -- no key for (b'), (e), (f),
    (g) or (h) exists to populate.

Four cells:

  R9-ABSENT   `tools/append_certified_build.py` is absent -- red-unimplemented.
  R10-ABSENT  `tools/check_certified_builds_evidence.py` is absent -- red-unimplemented.
  C42-CLAUSES the real, unmodified checker's `check()` dict has exactly the
              three keys {a,b,c} -- (b'), (e), (f), (g), (h) do not exist to
              be exercised. Fails loudly (not silently) if the checker ever
              gains a fourth key without this cell being updated to grade it,
              which is the point: a green run here is itself the signal
              nothing changed.
  C58-FIXTURE the R9 must-accept/must-reject PAIR, built from the real,
              committed interim evidence (never a synthetic package), graded
              against the REAL, UNMODIFIED checker available today. TODAY
              the checker's clauses (a)/(b)/(c) know nothing about
              `buildSystem` at all, so BOTH the must-accept (both copies
              relabelled "ubt") and the would-be must-reject (only run.json
              relabelled) are silently ACCEPTED -- this is the red state
              R9/C58 exists to close: nothing today refuses the
              inconsistent relabelling. It goes RED (in the sense of
              "the checker fails to catch it") for the reason named, and
              goes GREEN only once clause (b') exists and refuses the
              run.json-only relabel by name, exactly as
              `Claude/Vitruvius/te335-probe/c42_bprime.py` already showed
              executable.
              A second, independent leg is genuinely gradable TODAY against
              the real checker's real (a)/(b): one hex digit of the real
              committed `win-x64-msvc-avx2-zen2` row hash is changed, and
              `tools/check_certified_builds.py` must refuse `REFUSED
              C42(a)`/`REFUSED C42(b)` -- this is TE-335's own row-tamper
              construction, re-run here for real against `fca421b`'s
              committed package, and it is the one leg of R9/C58 that
              passes TODAY (proving the existing clauses' own real teeth,
              not a placeholder).

EXIT CODE CONVENTION (te163_bank_pair_check.py's own, restated so it is not
re-derived per script): 0 only if every cell is PASS or MISSING
PREREQUISITE; 1 if any cell is FAIL or RED-UNIMPLEMENTED. A cell that
correctly OBSERVES that a mechanism is still absent is RED-UNIMPLEMENTED,
not PASS -- confirming the absence for the right reason does not turn a
red ctest entry green; only the mechanism landing does. R9-ABSENT,
R10-ABSENT and C42-CLAUSES are therefore RED-UNIMPLEMENTED today by
design, and this script exits 1 until the builder's round removes them.
C58's row-tamper leg exercises a mechanism that already exists
(check_certified_builds.py's real clauses a/b) and is graded PASS/FAIL on
its own merits; C58's relabel-gap leg is RED-UNIMPLEMENTED today (the gap
it demonstrates is exactly the missing clause), and flips to a genuine
PASS/FAIL grading the day clause (b') exists to refuse the construction.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_checker_module():
    spec = importlib.util.spec_from_file_location(
        "check_certified_builds", REPO_ROOT / "tools" / "check_certified_builds.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def cell_r9_absent() -> str:
    path = REPO_ROOT / "tools" / "append_certified_build.py"
    absent = not path.exists()
    status = "RED-UNIMPLEMENTED" if absent else "FAIL"
    print(f"[{status}] R9-ABSENT: {path} exists={path.exists()} "
          f"(the append tool U2-7 item 8 specifies does not exist yet; a FAIL here would mean "
          f"the tool landed and C58's own grading cell, not this absence check, is now load-bearing)")
    return status


def cell_r10_absent() -> str:
    path = REPO_ROOT / "tools" / "check_certified_builds_evidence.py"
    absent = not path.exists()
    status = "RED-UNIMPLEMENTED" if absent else "FAIL"
    print(f"[{status}] R10-ABSENT: {path} exists={path.exists()}")
    cmake_text = (REPO_ROOT / "cmake" / "CertifiedBuilds.cmake").read_text(encoding="utf-8")
    has_unproven = "UNPROVEN" in cmake_text or "pairwiseProofs" in cmake_text
    print(f"[INFO] R10-ABSENT (CMake side): cmake/CertifiedBuilds.cmake carries evidence-half "
          f"logic already: {has_unproven} (U2-3 item 11 has not landed either -- expected False "
          f"at fca421b)")
    return status


def cell_c42_clauses_absent() -> str:
    mod = load_checker_module()
    root = REPO_ROOT  # the committed interim package is at the repo root itself
    refused = mod.check(root)
    keys = set(refused.keys())
    still_three = keys == {"a", "b", "c"}
    status = "RED-UNIMPLEMENTED" if still_three else "FAIL"
    print(f"[{status}] C42-CLAUSES: check() returns keys {sorted(keys)} "
          f"(clauses (b'), (e), (f), (g), (h) are U2-3's own unbuilt additions over today's three; "
          f"a FAIL here means the checker gained a clause this cell does not yet know how to grade "
          f"-- update the cell, don't silently accept a fourth key)")
    return status


def _clone_committed_package(dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "docs" / "certified-builds.json", dst / "certified-builds.json")
    (dst / "docs").mkdir(exist_ok=True)
    shutil.copy2(REPO_ROOT / "docs" / "certified-builds.json", dst / "docs" / "certified-builds.json")
    shutil.copy2(REPO_ROOT / "superslm.lock", dst / "superslm.lock")
    shutil.copytree(REPO_ROOT / "docs" / "certification" / "interim", dst / "docs" / "certification" / "interim")


def cell_c58_row_tamper_must_reject(scratch: Path) -> str:
    """TE-335's own construction, re-run for real against fca421b's committed package: one hex
    digit of the real committed win-x64-msvc-avx2-zen2 member's row hash is changed, and the
    real, unmodified checker must refuse C42(a) and C42(b). This is the one leg of R9/C58's
    must-reject pair that is gradable today, because it exercises the checker's EXISTING clauses
    rather than the unbuilt buildSystem consistency rule."""
    pkg = scratch / "c58_row_tamper"
    if pkg.exists():
        shutil.rmtree(pkg)
    _clone_committed_package(pkg)
    tsv_path = pkg / "docs" / "certification" / "interim" / "win-x64-msvc-avx2-zen2" / "row-digests.tsv"
    text = tsv_path.read_text(encoding="utf-8")
    lines = text.split("\n")
    first_data_line = next(i for i, l in enumerate(lines) if l.strip())
    tampered = list(lines[first_data_line])
    # Flip one hex digit in the digest column (after the tab).
    tab_at = lines[first_data_line].index("\t")
    hexpos = tab_at + 1
    ch = tampered[hexpos]
    tampered[hexpos] = "0" if ch != "0" else "1"
    lines[first_data_line] = "".join(tampered)
    tsv_path.write_text("\n".join(lines), encoding="utf-8")

    proc = subprocess.run([sys.executable, str(REPO_ROOT / "tools" / "check_certified_builds.py"),
                           "--root", str(pkg)], capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    refused_ab = ("REFUSED C42(a)" in out) or ("REFUSED C42(b)" in out)
    ok = refused_ab and proc.returncode == 1
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] C58 row-tamper must-reject (real checker, real committed "
          f"package, one hex digit changed): exit={proc.returncode}\n{out}")
    return status


def cell_c58_buildsystem_relabel_gap(scratch: Path) -> str:
    """The gap R9/C58 exists to close: TODAY, relabelling only run.json's buildSystem-shaped copy
    (a construction analogous to the plan's own must-reject, adapted to fields that actually exist
    in this tree's real run.json -- buildId/runId/date/toolchain/enginePin/rowDigest/tokenIdDigest,
    since build_descriptor/buildSystem are themselves U2-3 item 12 additions not yet in this
    tree's schema) passes the real checker's real clauses (a)/(b)/(c) exactly as cleanly as an
    UNTAMPERED copy does, because those clauses never read a build-system-identifying field at
    all. This is the honest red state: nothing today can refuse an internally-inconsistent
    relabelling of a field that does not exist yet, because clause (b') -- the clause that will
    read it -- does not exist yet either. Confirmed by executing the SAME real checker against
    the UNTAMPERED clone (must pass) and a clone whose run.json 'toolchain' field alone is
    changed with the manifest's own row/token digests left alone (an analogue of the plan's own
    "run.json relabelled, the other copy left disagreeing" shape once build_descriptor exists) --
    today's checker does not fail this either, because (a)/(b)/(c) never compare 'toolchain'
    against a second copy of itself; only the identity pin (enginePin) is cross-checked (clause
    (c)) and untouched here."""
    baseline = scratch / "c58_baseline"
    if baseline.exists():
        shutil.rmtree(baseline)
    _clone_committed_package(baseline)
    mod = load_checker_module()
    refused_baseline = mod.check(baseline)
    baseline_clean = not any(refused_baseline.values())

    inconsistent = scratch / "c58_inconsistent"
    if inconsistent.exists():
        shutil.rmtree(inconsistent)
    _clone_committed_package(inconsistent)
    run_json_path = inconsistent / "docs" / "certification" / "interim" / "win-x64-msvc-avx2-zen2" / "run.json"
    run = json.loads(run_json_path.read_text(encoding="utf-8"))
    run["toolchain"] = "MSVC 19.44.35214.0"  # a field-level inconsistency clause (b') would name;
                                              # (a)/(b)/(c) read no such field today
    run_json_path.write_text(json.dumps(run, indent=2), encoding="utf-8")
    refused_inconsistent = mod.check(inconsistent)
    inconsistent_accepted = not any(refused_inconsistent.values())

    # The GAP: today's checker accepts the field-inconsistent run exactly as
    # it accepts the untampered one. This is RED-UNIMPLEMENTED, not PASS --
    # the gap this cell demonstrates is exactly clause (b')'s own missing
    # mechanism. It inverts to a genuine PASS/FAIL grading (require refusal)
    # the day clause (b') exists and reads this field.
    gap_confirmed = baseline_clean and inconsistent_accepted
    status = "RED-UNIMPLEMENTED" if gap_confirmed else "FAIL"
    print(f"[{status}] C58 buildSystem/toolchain-relabel gap: "
          f"baseline clean={baseline_clean}, field-inconsistent run ALSO accepted={inconsistent_accepted} "
          f"-- becomes a PASS/FAIL cell requiring REFUSAL once clause (b') exists")
    return status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scratch", type=Path, default=REPO_ROOT / "build" / "_scratch" / "te331_c42_r9_r10")
    args = ap.parse_args()
    args.scratch.mkdir(parents=True, exist_ok=True)

    results = [
        cell_r9_absent(),
        cell_r10_absent(),
        cell_c42_clauses_absent(),
        cell_c58_row_tamper_must_reject(args.scratch),
        cell_c58_buildsystem_relabel_gap(args.scratch),
    ]
    red_or_failed = [r for r in results if r in ("FAIL", "RED-UNIMPLEMENTED")]
    print(f"TOTAL cells={len(results)} red-or-failed={len(red_or_failed)}: {results}")
    return 0 if not red_or_failed else 1


if __name__ == "__main__":
    sys.exit(main())
