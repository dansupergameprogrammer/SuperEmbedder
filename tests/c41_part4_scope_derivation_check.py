#!/usr/bin/env python3
"""Structural gate for C41 part 4's source-population derivation.

The object-code scan remains quarantined and returns zero for every completed
reading.  This separate cell instead fails when the scan's TU population is
not exactly the root CMake SEMB_LIBRARY_SOURCES population.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path


def cmake_library_tus(repo_root: Path) -> list[str]:
    text = (repo_root / "CMakeLists.txt").read_text(encoding="utf-8")
    match = re.search(r"set\s*\(\s*SEMB_LIBRARY_SOURCES\s*(.*?)\)", text, re.DOTALL)
    if match is None:
        raise RuntimeError("cannot find set(SEMB_LIBRARY_SOURCES ...) in root CMakeLists.txt")
    return [Path(token).name for token in re.findall(r"[^\s#)]+", re.sub(r"#.*", "", match.group(1)))
            if Path(token).suffix == ".cpp"]


def load_scan_tus(scan_script: Path, repo_root: Path) -> list[str]:
    spec = importlib.util.spec_from_file_location("c41_part4_object_code_scan", scan_script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load scan script {scan_script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    derive = getattr(module, "library_translation_units", None)
    if derive is not None:
        return list(derive(repo_root))
    # The legacy shape is intentionally supported only so the must-reject can
    # prove this checker kills the prior hand-maintained population.
    legacy = getattr(module, "SCOPED_TUS", None)
    if legacy is None:
        raise RuntimeError("scan script exposes neither library_translation_units nor SCOPED_TUS")
    return list(legacy)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--scan-script", required=True)
    args = ap.parse_args(argv)
    try:
        expected = cmake_library_tus(Path(args.repo_root))
        scanned = load_scan_tus(Path(args.scan_script), Path(args.repo_root))
    except (OSError, RuntimeError) as exc:
        print(f"C41 part 4 scope derivation: FAIL -- {exc}")
        return 1
    missing = [tu for tu in expected if tu not in scanned]
    extra = [tu for tu in scanned if tu not in expected]
    if missing or extra:
        print("C41 part 4 scope derivation: FAIL -- scan population differs from SEMB_LIBRARY_SOURCES")
        print(f"  missing from scan: {', '.join(missing) if missing else '<none>'}")
        print(f"  extra in scan: {', '.join(extra) if extra else '<none>'}")
        return 1
    print(f"C41 part 4 scope derivation: PASS -- {len(expected)} library TUs derived from SEMB_LIBRARY_SOURCES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
