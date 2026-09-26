"""tests/u2_1_version_line_check.py -- U2-1's `semb --version` build line (plan U2-1, the installed-CLI item;
U2-3 item 1; U2-3 item 14's (k-14); C51 (r-1) and item 13's (k-6), which read the uncertified epoch "in
`semb --version`").

The plan's required output: the version, the engine pin, the build descriptor U2-3 defines (os, architecture,
compiler, configuration, build system, forced tier or `auto`, standard library, the product's and the engine's
compile-flag digests, and the engine's recorded compiler), the CPU tier this process dispatches to on this
host, the cell verdict (the matching certified cell's id, or `uncertified`) with its epoch, the certification
line (the identity file's `line` and SHA-256) and the SHA-256 of the list this binary compiled in, and the
linked engine's own report: its build record (beside the one this build expects), forced tier, required
extensions, and the check's status.

Each value is graded against a producer the CLI does not write:
  - the pin and the certification line against the source tree's own superslm.lock, identity file and list;
  - dispatch, engineFlags, the engine's toolchain and standard library, and the expected build record against
    the engine install's own provenance.json (the pin tool's record);
  - compileFlags against the build step's own generated header;
  - the cell and its epoch by this script's own matcher over the committed list (FORMAT.md sec 4's rule);
  - an auto build's tier, on Linux, against /proc/cpuinfo (the engine resolver's avx512f+avx512bw / avx2 rule).
When the linked-engine check refuses, the tier and the cell must name the check's status and no cell or epoch
may be printed (item 14: the tier probe runs only after the check has passed; never a borrowed cell).

Exit 0 only when every leg passes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LINES = ["semb ", "build: ", "descriptor: ", "tier: ", "cell: ", "certification: ", "engine: "]
DESCRIPTOR_FIELDS = ["os", "isa", "toolchain", "stdlib", "configuration", "buildSystem", "dispatch",
                     "compileFlags", "engineFlags"]
TIERS = {"sse2", "avx2", "avx512", "scalar"}

failures: list[str] = []


def leg(ok: bool, name: str, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def fields(text: str) -> dict[str, str]:
    """key=value pairs; a value is a bare token or a JSON string literal."""
    out: dict[str, str] = {}
    for m in re.finditer(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)', text):
        v = m.group(2)
        out[m.group(1)] = json.loads(v) if v.startswith('"') else v
    return out


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decide(descriptor: dict[str, str], tier: str, list_bytes: bytes, identity: bytes) -> tuple[str, str]:
    uncertified = ("uncertified", sha256(b"SEMB-UNCERTIFIED\0" + identity))
    try:
        doc = json.loads(list_bytes)
        builds, proofs = doc["builds"], doc["pairwiseProofs"]
    except (ValueError, KeyError, TypeError):
        return uncertified
    ids = {b.get("id", "") for b in builds if isinstance(b, dict)}

    def paired(cell: str) -> bool:
        partners: dict[str, int] = {}
        digests = set()
        for p in proofs:
            a, b = p.get("a", ""), p.get("b", "")
            if cell not in (a, b):
                continue
            other = b if a == cell else a
            if other == cell or other not in ids or not p.get("rowDigest"):
                return False
            digests.add(p["rowDigest"])
            partners[other] = partners.get(other, 0) + 1
        return len(digests) <= 1 and all(partners.get(o) == 1 for o in ids if o != cell)

    matched = [b["id"] for b in builds
               if isinstance(b, dict) and b.get("id") and b.get("cpuTier") == tier
               and all(b.get(k) == descriptor.get(k) for k in DESCRIPTOR_FIELDS) and paired(b["id"])]
    if len(matched) != 1:
        return uncertified
    return matched[0], sha256(identity)


def linux_best_tier() -> str | None:
    try:
        text = Path("/proc/cpuinfo").read_text()
    except OSError:
        return None
    m = re.search(r"^flags\s*:\s*(.*)$", text, re.M)
    if not m:
        return None
    flags = set(m.group(1).split())
    if {"avx512f", "avx512bw"} <= flags:
        return "avx512"
    if "avx2" in flags:
        return "avx2"
    return "sse2"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--semb", required=True, type=Path)
    ap.add_argument("--build-dir", required=True, type=Path)
    ap.add_argument("--engine-provenance", required=True, type=Path)
    ap.add_argument("--configuration", required=True)
    args = ap.parse_args()

    proc = subprocess.run([str(args.semb), "--version"], capture_output=True, text=True)
    print(proc.stdout, end="")
    leg(proc.returncode == 0, "EXIT", f"exit {proc.returncode}, stderr {proc.stderr.strip()!r}")
    lines = proc.stdout.splitlines()
    leg([ln.split(" ", 1)[0] + " " for ln in lines] == LINES, "LINES",
        f"want the lines {[p.strip() for p in LINES]} in that order")
    by = {p.strip(): ln[len(p):] for p in LINES for ln in lines if ln.startswith(p)}
    if set(by) != {p.strip() for p in LINES}:
        print("a required line is missing; nothing further is graded")
        return 1

    lock = dict(ln.split("=", 1) for ln in (REPO_ROOT / "superslm.lock").read_text().split() if "=" in ln)
    identity = (REPO_ROOT / "docs" / "certification-identity.json").read_bytes()
    list_bytes = (REPO_ROOT / "docs" / "certified-builds.json").read_bytes()
    prov = json.loads(args.engine_provenance.read_text(encoding="utf-8"))["engine_build"]
    flags_header = (args.build_dir / "generated" / "semb_compile_flags.h").read_text()
    m = re.search(r'#define SEMB_COMPILE_FLAGS_SHA "([^"]*)"', flags_header)
    compile_flags = m.group(1) if m else None

    head = by["semb"]
    leg(f"(engine pin {lock.get('tag')} @ {lock.get('commit')}," in head, "PIN",
        f"the lock's tag {lock.get('tag')} and commit {lock.get('commit')}")

    d = fields(by["descriptor:"])
    leg(all(k in d for k in DESCRIPTOR_FIELDS + ["engineToolchain", "engineStdlib"]), "DESCRIPTOR FIELDS",
        f"got {sorted(d)}")
    leg(d.get("configuration") == args.configuration, "DESCRIPTOR configuration",
        f"{d.get('configuration')!r} vs the build's {args.configuration!r}")
    leg(d.get("buildSystem") == "cmake", "DESCRIPTOR buildSystem", repr(d.get("buildSystem")))
    leg(d.get("dispatch") == prov.get("dispatch"), "DESCRIPTOR dispatch",
        f"{d.get('dispatch')!r} vs the engine's recorded {prov.get('dispatch')!r}")
    leg(d.get("engineFlags") == prov.get("flagsSha"), "DESCRIPTOR engineFlags",
        f"{d.get('engineFlags')!r} vs {prov.get('flagsSha')!r}")
    leg(d.get("engineToolchain") == prov.get("toolchain") and d.get("engineStdlib") == prov.get("stdlib"),
        "DESCRIPTOR engine compiler",
        f"{d.get('engineToolchain')!r}/{d.get('engineStdlib')!r} vs {prov.get('toolchain')!r}/{prov.get('stdlib')!r}")
    leg(compile_flags is not None and d.get("compileFlags") == compile_flags, "DESCRIPTOR compileFlags",
        f"{d.get('compileFlags')!r} vs the build step's {compile_flags!r}")

    c = fields(by["certification:"])
    leg(c.get("line") == str(json.loads(identity)["line"]), "CERTIFICATION line", repr(c.get("line")))
    leg(c.get("identity_sha256") == sha256(identity), "CERTIFICATION identity_sha256",
        f"{c.get('identity_sha256')!r} vs {sha256(identity)}")
    leg(c.get("certified_builds_sha256") == sha256(list_bytes), "CERTIFICATION certified_builds_sha256",
        f"{c.get('certified_builds_sha256')!r} vs {sha256(list_bytes)}")

    e = fields(by["engine:"])
    check = e.get("check", "")
    leg(e.get("expected") == prov.get("buildRecord"), "ENGINE expected",
        f"{e.get('expected')!r} vs the engine's recorded {prov.get('buildRecord')!r}")
    leg(e.get("forced_tier") == d.get("dispatch"), "ENGINE forced_tier",
        f"{e.get('forced_tier')!r} vs dispatch {d.get('dispatch')!r}")
    leg(bool(e.get("required_isa")), "ENGINE required_isa", repr(e.get("required_isa")))
    leg(check.startswith("SEMB_"), "ENGINE check", repr(check))

    tier_text, cell_text = by["tier:"].strip(), by["cell:"].strip()
    if check != "SEMB_OK":
        # The check refused: nothing past it runs, so no tier is read and no cell is decided.
        leg(tier_text == f"refused {check}", "TIER (refused)", repr(tier_text))
        leg(cell_text == f"refused {check}", "CELL (refused)", repr(cell_text))
        leg(bool(e.get("missing_isa")) == (check == "SEMB_CPU_TIER_UNSUPPORTED"), "ENGINE missing_isa",
            repr(e.get("missing_isa")))
    else:
        leg(e.get("build_record") == e.get("expected"), "ENGINE build_record",
            f"{e.get('build_record')!r} vs expected {e.get('expected')!r}")
        leg(tier_text in TIERS, "TIER value", repr(tier_text))
        if d.get("dispatch") != "auto":
            leg(tier_text == d.get("dispatch"), "TIER forced", f"{tier_text!r} vs dispatch {d.get('dispatch')!r}")
        elif sys.platform.startswith("linux"):
            best = linux_best_tier()
            leg(best is not None and tier_text == best, "TIER auto", f"{tier_text!r} vs /proc/cpuinfo's {best!r}")
        want_cell, want_epoch = decide(d, tier_text, list_bytes, identity)
        cf = fields(cell_text)
        got_cell = cell_text.split(" ", 1)[0]
        leg(got_cell == want_cell, "CELL", f"{got_cell!r} vs the committed list's {want_cell!r}")
        leg(cf.get("epoch") == want_epoch, "CELL epoch", f"{cf.get('epoch')!r} vs {want_epoch}")

    print(f"{len(failures)} failed" + (f": {failures}" if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
