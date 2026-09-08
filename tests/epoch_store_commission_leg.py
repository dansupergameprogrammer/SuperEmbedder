"""tests/epoch_store_commission_leg.py -- TE-180 item 1 (D-SLM6427, ruled
D-SLM6433 item 1): two literal, cmd.exe-runnable commands for
`Claude/Tooling/instrument-commission.ps1 -Register`'s `must_accept`/
`must_reject` fields, distinguishing exit codes on their own -- which
`tests/epoch_store_constructions_check.py`'s own all-twelve aggregate
cannot do (it has no `--only` selector and always exits on the WHOLE
population's own combined verdict, D-SLM6427).

This file adds no new construction and reuses
`epoch_store_constructions_check.build_base_repo()` for its own base-repo
setup (mint fp1, copy fp2, base commit) verbatim, so the population
`epoch_store_constructions_check.py` runs stays exactly what it already is:
`--leg accept` drives construction 4 (an append that leaves fp1/fp2 byte-
identical, fp3 newly appended); `--leg reject` drives construction 1 (one
byte of fp1's own vectors.f32 flipped, lineage.tsv held fixed) -- both by
calling the SAME module-level helpers (`checkout_new_branch`, `copy_entry`,
`flip_one_byte`, `commit_all`, `captured_check_parent_commit`) construction
4 and construction 1 themselves call, against the SAME base commit, never a
re-implementation of either mutation.

EXIT MAPPING, stated here and fail-safe in both directions (D-SLM6433 item
1's own ruling):

  --leg accept  exits 0 ONLY when `check_parent_commit` reported zero FAIL
                rows for the construction-4 state AND fp3's own append was
                read (its fingerprint named in the "new appends" line) --
                exits 1 on every OTHER outcome, including any setup
                failure, so a broken host reads REJECTS_HEALTHY, never
                COMMISSIONED.
  --leg reject  exits 1 ONLY when `check_parent_commit` reported
                SEMB_EPOCH_BYTES_DIVERGED naming fp1 and did NOT also
                report SEMB_EPOCH_LINEAGE_DIVERGED (the construction-1
                signature) -- exits 0, with a printed reason, on every
                OTHER outcome, including any setup failure, so a broken
                host reads DEAD, never COMMISSIONED.

`instrument-commission.ps1`'s own `Invoke-Construction` runs whatever
command line the registry names through `cmd.exe /c`, reading ONLY the
process's own exit code as ACCEPTED (0) or REJECTED (non-zero) -- see that
script's own header comment and `Claude/Mendeleev/
te177-slice3-coverage-audit-2026-09-08.md` item 1 for why the constructions
check's own aggregate exit code cannot serve as either field: it always
runs all twelve constructions and always exits 0 only if every one of them
passed, which a must-reject leg can never distinguish (a single aggregate
exit code carries no information about WHICH construction produced it).
This script is two separate processes, one construction each, so each
leg's own exit code is genuinely that construction's own verdict.

USAGE
  epoch_store_commission_leg.py --leg accept|reject --emit-binary <exe>
    --repo-root <root> --scratch-dir <dir>
    [--synthetic-model <.sslm> --synthetic-tokenizer <.sslm>
     --synthetic-dims <n> --synthetic-tokens <tsv>
     --synthetic-terminator-id <n> --git <git-exe> --doc-id <id>]
  (the same flags epoch_store_constructions_check.py accepts, same
  defaults -- see that script's own --help.)

Exit codes: see EXIT MAPPING above -- deliberately leg-dependent, never a
uniform "0 success, 1 failure" the way every OTHER script in this suite
reads, because this file's whole reason to exist is standing in for one
construction's own accept/reject signal, not reporting its own success.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import epoch_store_constructions_check as constructions  # noqa: E402
import epoch_store_contract as contract  # noqa: E402


def run_accept_leg(base: "constructions.BaseRepo") -> int:
    """Construction 4: an append that leaves fp1/fp2 byte-identical to the
    base commit; fp3 newly appended. Exits 0 only on a genuine accept."""
    try:
        constructions.checkout_new_branch(base.repo, base.git, "commission-accept", base.base_sha)
        constructions.copy_entry(base.repo, base.fp1, base.fp3)
        constructions.commit_all(base.repo, base.git, "commission accept leg: append fp3, fp1/fp2 untouched")
        out = constructions.captured_check_parent_commit(base.repo, base.base_sha)
    except Exception as ex:  # noqa: BLE001 -- ANY setup failure fails safe: exit 1, never COMMISSIONED on a broken host
        print(f"[FAIL] (accept leg setup) {ex}")
        return 1
    print(out)
    ok = ("FAIL" not in out) and (base.fp3 in out)
    print(f"[{'PASS' if ok else 'FAIL'}] accept leg: construction 4 (append fp3, fp1/fp2 untouched) reports zero "
          f"FAIL rows and fp3's own append was read")
    return 0 if ok else 1


def run_reject_leg(base: "constructions.BaseRepo") -> int:
    """Construction 1: one byte of fp1's own vectors.f32 flipped, lineage.tsv
    held fixed. Exits 1 ONLY on the genuine, named SEMB_EPOCH_BYTES_DIVERGED
    signature -- exits 0 (with a printed reason) on every other outcome, so
    a broken host reads DEAD rather than a coincidental REJECTED."""
    try:
        constructions.checkout_new_branch(base.repo, base.git, "commission-reject", base.base_sha)
        constructions.flip_one_byte(
            contract.entry_dir(base.repo, contract.LIVE_DIR, base.fp1) / contract.VECTORS_FILE_NAME)
        constructions.commit_all(base.repo, base.git, "commission reject leg: flip a byte in fp1 vectors.f32")
        out = constructions.captured_check_parent_commit(base.repo, base.base_sha)
    except Exception as ex:  # noqa: BLE001 -- ANY setup failure fails safe: exit 0, never COMMISSIONED on a broken host
        print(f"[FAIL-SAFE] (reject leg setup failure -- must read DEAD, never COMMISSIONED) {ex}")
        return 0
    print(out)
    fires = (
        contract.STATUS_BYTES_DIVERGED in out
        and base.fp1 in out
        and contract.STATUS_LINEAGE_DIVERGED not in out
    )
    if fires:
        print("[REJECT-FIRED] reject leg: construction 1 (fp1 vectors.f32 flipped) reports "
              "SEMB_EPOCH_BYTES_DIVERGED naming fp1 and no SEMB_EPOCH_LINEAGE_DIVERGED")
        return 1
    print("[FAIL-SAFE] reject leg did not observe the named SEMB_EPOCH_BYTES_DIVERGED-only signature -- "
          "must read DEAD, never COMMISSIONED")
    return 0


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--leg", required=True, choices=["accept", "reject"])
    constructions.add_shared_args(p)
    args = p.parse_args()

    try:
        base = constructions.build_base_repo(args)
    except RuntimeError as ex:
        # Setup failure before either leg's own mutation ran -- fails safe
        # per leg, exactly as a failure INSIDE the leg's own try block does
        # (the two code paths must agree, or a host that dies during base-
        # repo setup would commission on a coin flip of WHICH leg ran first).
        print(f"[FAIL] {ex}")
        return 1 if args.leg == "accept" else 0

    if args.leg == "accept":
        return run_accept_leg(base)
    return run_reject_leg(base)


if __name__ == "__main__":
    sys.exit(main())
