"""tests/te331_u2_consumer_check.py -- TE-331 (U2-1, U2-7): drives
tests/consumer/ against an INSTALL PREFIX (`Claude/Plans/te267-u2-release-plan.md`
sec 5 U2-1 "Builds", "Red first" and "Proof"; U2-7 "Red first" (1), (2)).

LEGS.

  INSTALL      `cmake --install <product build> --prefix <scratch>` places the
               shared library (libsemb.so*), the public header semb.h and
               version.h and no other header ("the other headers in
               include/superembedder/ are internal test ABIs and are not
               installed"), superembedderConfig.cmake and
               superembedderConfigVersion.cmake, and the semb CLI; the static
               library is not installed. Must-reject, run in the cell: an
               empty prefix (today's red before U2-1), and the real prefix
               plus one internal header, each refused by the same predicate.

  NO-ENGINE-DEPENDENCY  the installed package files name no superslm target
               ("with no dependency on superslm::superslm"). Must-reject, run
               in the cell: the same text with a superslm::superslm link added
               is refused. The consumer legs below configure with the install
               prefix alone on CMAKE_PREFIX_PATH, so a dependency the text
               read missed fails there too.

  CONSUMER 1.0 (the plan's proof)  the consumer calls
               find_package(superembedder 1.0 CONFIG REQUIRED), links
               superembedder::superembedder, and on the synthetic pair opens
               by path, checks the dimension, encodes one string, encodes one
               query through semb_encode_query, and opens from memory through
               semb_encoder_open_memory with the path open's fingerprint.
               Configures, builds and runs green, or FAIL. The package is
               SameMajorVersion and the product reads 0.1.0 until REL-1 sets
               1.0.0 (plan sec 5 REL-1), so this leg is red until REL-1 by the
               plan's own order; the FAIL line says so when that is the cause.
               Vitality, run in the cell: the same configure against an EMPTY
               prefix fails naming superembedder (the original red-first
               construction), so a consumer configure that cannot fail is read
               red.

  CONSUMER MECHANISM  the same consumer, requesting the installed package's
               own version (read from the installed ConfigVersion file). Not
               the plan's proof: it keeps the install, link and run graded
               before REL-1, and it is not counted as the 1.0 leg.

  REAL (only with --model/--tokenizer)  the mechanism consumer on the real
               artifact. Otherwise MISSING PREREQUISITE (owed to the dev box).

EXIT: 0 only if every leg is PASS or MISSING PREREQUISITE.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSUMER = REPO_ROOT / "tests" / "consumer"
PUBLIC_HEADERS = {"semb.h", "version.h"}


def run(cmd, cwd=None, env=None, timeout=3600):
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, errors="replace",
                          timeout=timeout)
    return proc.returncode, proc.stdout + proc.stderr


def clean_env() -> dict:
    """The consumer sees the install prefix and nothing else."""
    env = dict(os.environ)
    for k in list(env):
        if k in ("CMAKE_PREFIX_PATH", "CMAKE_MODULE_PATH") or k.lower().endswith("_dir") and "superslm" in k.lower():
            env.pop(k)
    return env


def install_manifest(prefix: Path) -> dict:
    files = [p for p in prefix.rglob("*") if p.is_file() or p.is_symlink()] if prefix.exists() else []
    rel = [p.relative_to(prefix).as_posix() for p in files]
    return {
        "shared": [r for r in rel if re.search(r"(^|/)libsemb\.so(\.\d+)*$", r)
                   or re.search(r"(^|/)libsemb(\.\d+)*\.dylib$", r) or r.endswith("/semb.dll")],
        "headers": sorted(r.split("/")[-1] for r in rel if r.startswith("include/")),
        "header_dirs": sorted({r.rsplit("/", 1)[0] for r in rel if r.startswith("include/")}),
        "config": [r for r in rel if r.endswith("cmake/superembedder/superembedderConfig.cmake")],
        "config_version": [r for r in rel if r.endswith("cmake/superembedder/superembedderConfigVersion.cmake")],
        "cli": [r for r in rel if re.fullmatch(r"bin/semb(\.exe)?", r)],
        "static": [r for r in rel if re.search(r"libsuperembedder\.a$|superembedder\.lib$", r)],
    }


def install_ok(m: dict) -> tuple[bool, str]:
    why = []
    if not m["shared"]:
        why.append("no libsemb.so (or libsemb*.dylib)")
    if set(m["headers"]) != PUBLIC_HEADERS or m["header_dirs"] != ["include/superembedder"]:
        why.append(f"headers {m['headers']} under {m['header_dirs']} (want exactly semb.h, version.h "
                   f"under include/superembedder)")
    if not m["config"] or not m["config_version"]:
        why.append("no superembedderConfig.cmake / superembedderConfigVersion.cmake")
    if not m["cli"]:
        why.append("no bin/semb")
    if m["static"]:
        why.append(f"the static library is installed: {m['static']}")
    return (not why), "; ".join(why) or "all present, nothing extra"


def package_text(prefix: Path) -> str:
    d = [p for p in prefix.rglob("*.cmake") if "cmake/superembedder" in p.as_posix()]
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sorted(d))


def no_engine_dependency(text: str) -> bool:
    return bool(text) and re.search(r"superslm", text, re.IGNORECASE) is None


def consumer(cmake: str, prefix: Path, build: Path, version: str | None, model: str, tok: str):
    """Returns (stage, output): stage is 'configure', 'build', 'run' (the failing stage) or 'ok'."""
    shutil.rmtree(build, ignore_errors=True)
    cfg = [cmake, "-S", str(CONSUMER), "-B", str(build), "-DCMAKE_PREFIX_PATH=" + str(prefix),
           "-DCMAKE_BUILD_TYPE=Release"]
    if version is not None:
        cfg.append("-DSEMB_CONSUMER_REQUESTED_VERSION=" + version)
    rc, out = run(cfg, env=clean_env())
    if rc != 0:
        return "configure", out
    rc, out = run([cmake, "--build", str(build)], env=clean_env())
    if rc != 0:
        return "build", out
    exe = next((p for p in build.rglob("te331_consumer*") if p.is_file() and os.access(p, os.X_OK)
                and p.suffix in ("", ".exe")), None)
    if exe is None:
        return "build", "te331_consumer not found after build"
    # A Windows consumer of the shared library finds semb.dll through PATH (no rpath), so the install's bin
    # directory goes first, as any application's launcher would put it.
    env = None
    if os.name == "nt":
        env = dict(os.environ, PATH=str(prefix / "bin") + os.pathsep + os.environ.get("PATH", ""))
    rc, out = run([str(exe), model, tok], env=env)
    if rc != 0 or not out.startswith("OK "):
        return "run", out
    return "ok", out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmake-executable", "--cmake", dest="cmake", default="cmake")
    ap.add_argument("--product-build", type=Path, required=True)
    ap.add_argument("--scratch", type=Path, default=None)
    ap.add_argument("--model", default="")
    ap.add_argument("--tokenizer", default="")
    args = ap.parse_args()
    scratch = args.scratch or (args.product_build / "_scratch" / "te331_consumer")
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    results = []

    def leg(status: str, name: str, detail: str) -> None:
        results.append(status)
        print(f"[{status}] {name}: {detail}")

    # INSTALL
    prefix = scratch / "install_prefix"
    rc, out = run([args.cmake, "--install", str(args.product_build), "--prefix", str(prefix)])
    m = install_manifest(prefix)
    ok, why = install_ok(m)
    empty = scratch / "empty_prefix"
    empty.mkdir()
    rej_empty = not install_ok(install_manifest(empty))[0]
    extra = scratch / "install_prefix_extra_header"
    if prefix.exists():
        shutil.copytree(prefix, extra, symlinks=True)
    (extra / "include" / "superembedder").mkdir(parents=True, exist_ok=True)
    (extra / "include" / "superembedder" / "bake_abi.h").write_text("/* internal */\n", encoding="utf-8")
    rej_extra = not install_ok(install_manifest(extra))[0]
    leg("PASS" if rc == 0 and ok and rej_empty and rej_extra else "FAIL", "INSTALL",
        f"install exit {rc}; {why}; shared {m['shared']}; must-rejects refused: empty prefix {rej_empty}, "
        f"an internal header installed {rej_extra}" + ("" if rc == 0 else f"\n{out[-1500:]}"))

    # NO-ENGINE-DEPENDENCY
    text = package_text(prefix)
    mutant = text + "\nset_target_properties(superembedder::superembedder PROPERTIES " \
                    "INTERFACE_LINK_LIBRARIES \"superslm::superslm\")\n"
    ok_dep = no_engine_dependency(text)
    rej_dep = not no_engine_dependency(mutant)
    leg("PASS" if ok_dep and rej_dep else "FAIL", "NO-ENGINE-DEPENDENCY",
        f"installed package files name superslm: {not ok_dep}; must-reject (a superslm::superslm link added) "
        f"refused: {rej_dep}")

    # The synthetic pair (C60 (c)'s minimal fixture, as C56 and C64 use).
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import u2_9_workspace_cells_check as u29  # noqa: E402
    pair = REPO_ROOT / "build" / "_scratch" / "u2_9_min_pair"
    u29.ensure_pair(pair)
    s_model, s_tok = str(pair / "u1_pair_model.sslm"), str(pair / "u1_pair_tokenizer.sslm")

    # CONSUMER 1.0 (the plan's proof) and its vitality.
    stage, out = consumer(args.cmake, prefix, scratch / "consumer_1p0", None, s_model, s_tok)
    vstage, vout = consumer(args.cmake, empty, scratch / "consumer_empty", None, s_model, s_tok)
    vital = vstage == "configure" and "superembedder" in vout.lower()
    pv = re.search(r'set\(PACKAGE_VERSION "([^"]+)"\)', text)
    pkg_version = pv.group(1) if pv else ""
    if stage == "ok" and vital:
        leg("PASS", "CONSUMER 1.0", f"configured, built and ran against the install prefix: {out.strip()}")
    else:
        cause = ""
        if stage == "configure" and pkg_version and not pkg_version.startswith("1."):
            cause = (f" -- the installed package is version {pkg_version} (SameMajorVersion), so a 1.0 request "
                     f"is refused until REL-1 sets project VERSION 1.0.0 (plan sec 5 REL-1)")
        leg("FAIL", "CONSUMER 1.0", f"failed at {stage}{cause}; vitality (empty prefix refused at configure "
            f"naming superembedder): {vital}" + ("" if stage == "ok" else f"\n{out[-1500:]}"))

    # CONSUMER MECHANISM (the package's own version; not the proof).
    if not pkg_version:
        leg("FAIL", "CONSUMER MECHANISM", "no PACKAGE_VERSION in the installed superembedderConfigVersion.cmake")
    else:
        mstage, mout = consumer(args.cmake, prefix, scratch / "consumer_mech", pkg_version, s_model, s_tok)
        leg("PASS" if mstage == "ok" else "FAIL", f"CONSUMER MECHANISM (requests {pkg_version})",
            (f"configured, built and ran: {mout.strip()}" if mstage == "ok" else
             f"failed at {mstage}\n{mout[-1500:]}"))
        if args.model and args.tokenizer:
            rstage, rout = consumer(args.cmake, prefix, scratch / "consumer_real", pkg_version, args.model,
                                    args.tokenizer)
            leg("PASS" if rstage == "ok" else "FAIL", "REAL",
                rout.strip() if rstage == "ok" else f"failed at {rstage}\n{rout[-1500:]}")
        else:
            leg("MISSING PREREQUISITE", "REAL", "needs --model/--tokenizer (the real artifact); owed to the dev box")

    red = [r for r in results if r == "FAIL"]
    print(f"TOTAL legs={len(results)} failed={len(red)}: {results}")
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
