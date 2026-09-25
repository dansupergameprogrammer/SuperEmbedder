#!/usr/bin/env python3
"""tools/compile_flags.py -- the compile-flag record, one rule for the product and the engine (plan U2-3
item 13; FORMAT.md sec 3.5).

A cell names the flags both sides of the link were compiled with: `compileFlags` is the digest of the
product's record, `engineFlags` the digest of the engine's (the pin tool's `engine_build.flagsSha`). Both are
this rule over the build's own `compile_commands.json`, for each translation unit of the recorded targets:

  1. The argument vector the compiler receives, split by the platform's own rules: the Microsoft C runtime's
     on Windows, where a quote may open inside an argument (-I"E:\\a b\\include"), POSIX shell rules elsewhere.
  2. Dropped: the compiler path, the output arguments (/Fo, /Fd, -Fo, -Fd, and -o with its operand) and the
     source argument.
  2b. Dropped as proven inert: an argument on the compiler family's list (INERT below), which holds only
     arguments shown to leave code and data unchanged. Every other argument is kept.
  3. Joined: an include option written as two arguments (-I X, -isystem X, -imsvc X, -external:I X, -iquote X,
     -idirafter X) becomes one, as the compiler reads it.
  4. Location tokens: every occurrence of a location root becomes its token (<src>, <build>, <engine>). The
     roots are the build system's own values. The longest root is replaced first; a match ends at a
     path-component boundary; on Windows the match ignores case and treats / and \\ as one character.
  5. Include options keep their order; every other argument is sorted into a multiset.
  6. Residual locations: every kept argument that still carries an absolute path is listed beside the record.
     The digest covers the record as it stands, so a build with one reaches no cell.

The record is {"<target>:<tokenized source>": {"includes": [...], "flags": [...]}}; the digest is SHA-256 over
its canonical JSON (sorted keys, no whitespace).

    python tools/compile_flags.py --compile-commands <build>/compile_commands.json --family {msvc,clangcl,gcc,other}
        --root <path>=<token> [...] --target <name> [...] [--exclude-source <file name> ...] [--out <json>]

prints `COMPILE_FLAGS_SHA=<digest>` and one `SEMB_COMPILE_FLAGS_LOCATION <argument>` line per residual.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import sys
from pathlib import Path

INCLUDE_OPTS = ("-external:I", "/external:I", "-imsvc", "/imsvc", "-isystem", "-iquote", "-idirafter", "-I", "/I")
OUTPUT_JOINED = re.compile(r"^[/-]F[od]", re.I)  # /Fo<x> /Fd<x> -Fo<x> -Fd<x>

_SW = r"[/-]"
# Step 2b: per compiler family, only arguments executed and shown to leave code and data unchanged, plus the
# members the plan lists on the compilers' documented contract. Default-keep: anything not matched is recorded.
INERT = {
    "msvc": [rf"^{_SW}(nologo|FS|c|WX-?|Zi|Z7|Zo-?|showIncludes)$", rf"^{_SW}W[0-4]$", rf"^{_SW}w[de]\d+$",
             rf"^{_SW}diagnostics:(classic|column|caret)$", rf"^{_SW}external:W[0-4]$"],
    # clang-cl: NOT /Zi or /Z7, which change its code generation.
    "clangcl": [rf"^{_SW}(nologo|c|WX-?|showIncludes)$", r"^--$", rf"^{_SW}W[0-4]$", rf"^{_SW}wd\d+$",
                rf"^{_SW}diagnostics:(classic|column|caret)$"],
    # GCC: NOT -Wa, -Wl, or -Wp, (they hand options to the assembler, linker and preprocessor).
    "gcc": [r"^-(c|pipe|Wall|Wextra|Werror|MD|MMD|MP)$", r"^-Werror=[\w+-]+$", r"^-Wno-[\w+-]+(=\S*)?$",
            r"^-W(?![apl],)[A-Za-z][\w+-]*(=[^,\s]*)?$", r"^-g([0-3]|gdb|dwarf(-[2-5])?)?$",
            r"^-fdiagnostics-\S+$"],
    "other": [],
}
GCC_WITH_OPERAND = {"-MF", "-MT", "-MQ"}

ABS_WINDOWS = re.compile(r"([A-Za-z]:[\\/]|\\\\)")
ABS_POSIX = re.compile(r"^(-{1,2}[A-Za-z][A-Za-z0-9_+-]*=?)?/")


def family_of(compiler_id: str, frontend: str) -> str:
    """The inert-list family of the record's own compiler, from CMake's CMAKE_CXX_COMPILER_ID and
    CMAKE_CXX_COMPILER_FRONTEND_VARIANT."""
    if compiler_id == "MSVC":
        return "msvc"
    if compiler_id == "Clang" and frontend == "MSVC":
        return "clangcl"
    if compiler_id == "GNU":
        return "gcc"
    return "other"


def split_windows(cmd: str) -> list[str]:
    """The Microsoft C runtime's argument rules: a quote may open mid-argument, 2n backslashes before a quote
    give n and toggle quoting, 2n+1 give n and a literal quote, and "" inside quotes is a literal quote."""
    args: list[str] = []
    cur: list[str] = []
    have = inq = False
    i = 0
    while i < len(cmd):
        c = cmd[i]
        if c == "\\":
            n = 0
            while i < len(cmd) and cmd[i] == "\\":
                n += 1
                i += 1
            if i < len(cmd) and cmd[i] == '"':
                cur.append("\\" * (n // 2))
                if n % 2:
                    cur.append('"')
                    i += 1
            else:
                cur.append("\\" * n)
            have = True
            continue
        if c == '"':
            if inq and i + 1 < len(cmd) and cmd[i + 1] == '"':
                cur.append('"')
                i += 2
                continue
            inq = not inq
            have = True
            i += 1
            continue
        if c in " \t" and not inq:
            if have:
                args.append("".join(cur))
                cur, have = [], False
            i += 1
            continue
        cur.append(c)
        have = True
        i += 1
    if have:
        args.append("".join(cur))
    return args


def argv_of(entry: dict, windows: bool) -> list[str]:
    if isinstance(entry.get("arguments"), list):
        return [str(a) for a in entry["arguments"]]
    cmd = entry["command"]
    return split_windows(cmd) if windows else shlex.split(cmd, posix=True)


def _norm(path: str, windows: bool) -> str:
    return path.replace("\\", "/").rstrip("/").lower() if windows else path.rstrip("/")


def tokenize(arg: str, roots: list[tuple[str, str]], windows: bool) -> str:
    """Every occurrence of a root becomes its token, longest root first, at component boundaries."""
    for root, token in roots:
        r = _norm(root, windows)
        if not r:
            continue
        i = 0
        while True:
            hay = arg.replace("\\", "/").lower() if windows else arg
            j = hay.find(r, i)
            if j < 0:
                break
            end = j + len(r)
            if end == len(arg) or arg[end] in ("/\\" if windows else "/"):
                arg = arg[:j] + token + arg[end:]
                i = j + len(token)
            else:
                i = j + 1
    return arg


def is_residual(arg: str, windows: bool) -> bool:
    if windows:
        return bool(ABS_WINDOWS.search(arg))
    return bool(ABS_POSIX.match(arg)) or "=/" in arg


def _absolute(path: str, directory: str, windows: bool) -> str:
    if (windows and re.match(r"^([A-Za-z]:[\\/]|[\\/]{2})", path)) or path.startswith("/"):
        return path
    return directory.rstrip("/\\") + "/" + path


def _target_of(entry: dict) -> str | None:
    text = entry.get("output") or entry.get("command") or " ".join(entry.get("arguments") or [])
    m = re.search(r"CMakeFiles[\\/]([^\\/]+)\.dir[\\/]", text)
    return m.group(1) if m else None


def record(entries: list[dict], family: str, roots: list[tuple[str, str]], targets: list[str],
           exclude_sources: list[str], windows: bool) -> tuple[dict, list[str]]:
    roots = sorted(roots, key=lambda rt: len(_norm(rt[0], windows)), reverse=True)
    inert = [re.compile(p) for p in INERT[family]]
    excluded = {s.lower() if windows else s for s in exclude_sources}
    rec: dict[str, dict] = {}
    residual: list[str] = []
    for entry in entries:
        target = _target_of(entry)
        if target is None or target not in targets:
            continue
        directory = entry.get("directory", "")
        source = _absolute(entry["file"], directory, windows)
        name = source.replace("\\", "/").rsplit("/", 1)[-1]
        if (name.lower() if windows else name) in excluded:
            continue
        argv = argv_of(entry, windows)[1:]
        source_norm = _norm(source, windows)
        kept: list[str] = []
        k = 0
        while k < len(argv):
            a = argv[k]
            if a in INCLUDE_OPTS and k + 1 < len(argv):
                kept.append(a + argv[k + 1])
                k += 2
                continue
            if a == "-o" or (family == "gcc" and a in GCC_WITH_OPERAND):
                k += 2
                continue
            k += 1
            if OUTPUT_JOINED.match(a) or _norm(a, windows) == source_norm:
                continue
            if _norm(_absolute(a, directory, windows), windows) == source_norm:
                continue
            if any(p.match(a) for p in inert):
                continue
            kept.append(a)
        includes, flags = [], []
        for a in kept:
            t = tokenize(a, roots, windows)
            if is_residual(t, windows):
                residual.append(t)
            (includes if t.startswith(INCLUDE_OPTS) else flags).append(t)
        rec[f"{target}:{tokenize(source, roots, windows)}"] = {"includes": includes, "flags": sorted(flags)}
    return rec, sorted(set(residual))


def digest(rec: dict) -> str:
    return hashlib.sha256(json.dumps(rec, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--compile-commands", type=Path, required=True)
    ap.add_argument("--family", choices=sorted(INERT), required=True)
    ap.add_argument("--platform", choices=("windows", "posix"), default="windows" if os.name == "nt" else "posix")
    ap.add_argument("--root", action="append", default=[], help="<path>=<token>, e.g. C:/src=<src>")
    ap.add_argument("--target", action="append", default=[], required=True)
    ap.add_argument("--exclude-source", action="append", default=[])
    ap.add_argument("--out", type=Path, help="write {record, residual, sha256} here")
    args = ap.parse_args(argv)
    roots = []
    for r in args.root:
        path, sep, token = r.rpartition("=")
        if not sep or not path:
            ap.error(f"--root {r!r} is not <path>=<token>")
        roots.append((path, token))
    entries = json.loads(args.compile_commands.read_text(encoding="utf-8"))
    rec, residual = record(entries, args.family, roots, args.target, args.exclude_source,
                           args.platform == "windows")
    if not rec:
        print(f"SEMB_COMPILE_FLAGS_EMPTY: no translation unit of {args.target} in {args.compile_commands}",
              file=sys.stderr)
        return 1
    sha = digest(rec)
    if args.out:
        doc = {"schemaVersion": 1, "family": args.family, "sha256": sha, "residual": residual, "record": rec}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(doc, sort_keys=True, indent=1) + "\n"
        if not args.out.exists() or args.out.read_text(encoding="utf-8") != text:
            args.out.write_text(text, encoding="utf-8", newline="\n")
    for r in residual:
        print(f"SEMB_COMPILE_FLAGS_LOCATION {r}")
    print(f"COMPILE_FLAGS_SHA={sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
