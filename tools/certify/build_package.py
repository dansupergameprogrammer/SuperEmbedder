#!/usr/bin/env python3
"""Builds the certification package on the dev box (te267 U2-6), one resumable step per invocation.

The package is run-only, in the pattern of SuperSLM's tools/t2116_crossvendor/: prebuilt binaries, the model and
tokenizer, the corpus, and run_certify.ps1, with no toolchain needed where it runs (README.txt beside this file
gives the procedure). Every step below writes only its own part of the package, so a step that crashed is simply
run again; nothing a step writes is read back by the same step.

    pin    --member M --engine-prefix E --source S [--lock L] [--workdir W]
           Pins the member's own engine with the pin tool, in the calling environment (the member's toolchain:
           vcvars64 -vcvars_ver=14.33 for the MSVC 19.33 and clang-cl members, BuildTools' vcvars64 for MSVC 19.44,
           the Ubuntu-24.04 distro for GCC). A forced member passes --force-tier <its tier>. The GPU binary's
           prefix is the msvc19.33-auto engine pinned again with the pin tool's --with-gpu (D-SLM7735): --member
           msvc19.33-auto-gpu.
    build  --member M --engine-prefix E --build-dir B [--source-dir R]
           Configures (Ninja, Release, CMAKE_PREFIX_PATH=E) and builds `semb`, plus C63's binary for the forced
           AVX-512 member and SEMB_BUILD_GPU=ON for the GPU binary.
    stage  --package P --member M --build-dir B --engine-prefix E [--repo R] [--shaders D]
           Copies the member's semb, its compile-flag record, its engine's flag record and member.json (engine
           pin, engine build record, product commit, derivation-input digest) into bin/<member>/. The forced
           AVX-512 member also gets c63.exe. The GPU binary also gets shaders/ and is refused unless its engine's
           build record equals msvc19.33-auto's.
    tools  --package P --probe-windows X --probe-linux Y --superfaiss-source S [--sf-roundtrip Z]
           Copies the two builds of the CPU probe into bin/tools/, and SuperFAISS's tools/wvbank.py at
           superfaiss.lock's commit into harness/. The round trip's program is Z when given; otherwise it is
           compiled here, in the calling (MSVC 19.33) environment, by the round-trip harness's own export and
           build functions from the tree superfaiss.lock pins.
    finish --package P --model M --tokenizer T [--repo R]
           Copies the artifacts, the corpus, C63's texts, the harness and readiness scripts, run_certify.ps1,
           README.txt and gpu-legs.json, and writes package.json.
    receipts --package P --from <results dir>
           Copies the dev-box provisional receipts of the two forced cells host mode compares against
           (msvc19.33-sse2@sse2, msvc19.33-avx2@avx2) into receipts/.

Refusals, each one line on stderr, exit 1, before anything is run or written:
    SEMB-PACKAGE-BUILD-ENV-FLAGS <variable>   pin or build while CFLAGS, CXXFLAGS, LDFLAGS or
                                              CMAKE_TOOLCHAIN_FILE is set, so no member's flag record carries a
                                              flag a user following the README would not get
    SEMB-PACKAGE-GPU-ENGINE-MISMATCH          the GPU binary's engine build record is not msvc19.33-auto's
    SEMB-PACKAGE-UNKNOWN-MEMBER <name>        a member the plan does not rule
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

# The ruled members (D-SLM4739, D-SLM7253), in the order the package runs them, and the GPU binary (TE-401).
MEMBERS = ("msvc19.33-auto", "msvc19.33-sse2", "msvc19.33-avx2", "msvc19.33-avx512", "clangcl18.1.8-auto",
           "msvc19.44.35214-auto", "gcc13.3.0-wsl-auto")
GPU_BINARY = "msvc19.33-auto-gpu"
GPU_ENGINE_OF = "msvc19.33-auto"
WSL_MEMBER = "gcc13.3.0-wsl-auto"
C63_MEMBER = "msvc19.33-avx512"
FORCED_CELLS = ("msvc19.33-sse2@sse2", "msvc19.33-avx2@avx2")
ENV_FLAGS = ("CFLAGS", "CXXFLAGS", "LDFLAGS", "CMAKE_TOOLCHAIN_FILE")
RUN_FILES = ("row-digests.tsv", "token-id-digest.txt")


class Refused(Exception):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def forced_tier(member: str) -> str | None:
    m = re.search(r"-(sse2|avx2|avx512)$", member)
    return m.group(1) if m else None


def check_member(member: str, allow_gpu: bool = True) -> None:
    if member not in MEMBERS and not (allow_gpu and member == GPU_BINARY):
        raise Refused(f"SEMB-PACKAGE-UNKNOWN-MEMBER {member}")


def refuse_env_flags(environ: dict) -> None:
    for name in ENV_FLAGS:
        if environ.get(name, "").strip():
            raise Refused(f"SEMB-PACKAGE-BUILD-ENV-FLAGS {name}")


def executable(directory: Path, stem: str) -> Path | None:
    return next((p for p in (directory / f"{stem}.exe", directory / stem) if p.is_file()), None)


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+ " + " ".join(cmd), flush=True)
    done = subprocess.run(cmd, cwd=cwd)
    if done.returncode:
        raise SystemExit(f"command failed ({done.returncode}): {cmd[0]}")


def provenance(prefix: Path) -> dict:
    return json.loads((prefix / "share" / "superslm-provenance" / "provenance.json").read_text(encoding="utf-8"))


def engine_flags_record(prov: dict) -> dict:
    """The engine's flag record in the form C42 (b')'s location clause reads (U2-3 item 12; TE-298)."""
    eb = prov["engine_build"]
    return {"schemaVersion": 1, "family": eb["flags"]["family"], "sha256": eb["flagsSha"],
            "residual": eb["flags"].get("residual", []), "record": eb["flags"]["record"]}


def engine_pin_of(build: Path) -> dict:
    header = (build / "generated" / "semb_engine_pin.h").read_text(encoding="utf-8")

    def get(name: str) -> str:
        found = re.search(rf'#define {name} "([^"]*)"', header)
        if not found:
            raise SystemExit(f"{name} not in {build / 'generated' / 'semb_engine_pin.h'}")
        return found.group(1)

    return {"tag": get("SEMB_ENGINE_PIN_TAG"), "commit": get("SEMB_ENGINE_PIN_COMMIT"),
            "engine_tree_sha": get("SEMB_ENGINE_PIN_TREE_SHA")}


def tree_identity(repo: Path) -> tuple[str, str]:
    sys.path.insert(0, str(repo / "tools"))
    import derivation_inputs  # noqa: E402  (the one implementation C42 (c') compares against)
    commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()
    return commit, derivation_inputs.digest(repo)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes((json.dumps(value, indent=2) + "\n").encode("utf-8"))
    os.replace(tmp, path)


# -- steps ---------------------------------------------------------------------------------------------------------
def cmd_pin(args, environ: dict) -> int:
    check_member(args.member)
    refuse_env_flags(environ)
    cmd = [sys.executable, str(args.repo / "tools" / "pin-superslm" / "pin_superslm.py"), "--lock", str(args.lock),
           "--prefix", str(args.engine_prefix), "--source", args.source, "--workdir", str(args.workdir)]
    tier = forced_tier(args.member)
    if tier:
        cmd += ["--force-tier", tier]
    if args.member == GPU_BINARY:
        cmd += ["--with-gpu"]  # the pin tool's GPU install (D-SLM7735, U3); the pin tool refuses it until U3 lands
    run(cmd, cwd=args.repo)
    return 0


def cmd_build(args, environ: dict) -> int:
    check_member(args.member)
    refuse_env_flags(environ)
    configure = ["cmake", "-S", str(args.source_dir), "-B", str(args.build_dir), "-G", "Ninja",
                 "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_PREFIX_PATH={args.engine_prefix}"]
    if args.member == GPU_BINARY:
        configure.append("-DSEMB_BUILD_GPU=ON")  # U3's option (te266 sec 4.2)
    run(configure)
    targets = ["semb"] + (["u2_10_c63_keeper_test"] if args.member == C63_MEMBER else [])
    run(["cmake", "--build", str(args.build_dir), "--target", *targets])
    return 0


def cmd_stage(args, environ: dict) -> int:
    check_member(args.member)
    prov = provenance(args.engine_prefix)
    record = prov["engine_build"]["buildRecord"]
    if args.member == GPU_BINARY:
        auto = args.package / "bin" / GPU_ENGINE_OF / "member.json"
        if not auto.is_file():
            raise SystemExit(f"stage {GPU_ENGINE_OF} before {GPU_BINARY}: {auto} is absent")
        theirs = json.loads(auto.read_text(encoding="utf-8")).get("engineBuildRecord")
        if theirs != record:
            raise Refused(f"SEMB-PACKAGE-GPU-ENGINE-MISMATCH {GPU_BINARY} engine_build.buildRecord {record} != "
                          f"{GPU_ENGINE_OF}'s {theirs}")
        if args.shaders is None or not args.shaders.is_dir():
            raise SystemExit(f"{GPU_BINARY} needs --shaders, the engine's shader set (te266 sec 4.2)")
    semb = executable(args.build_dir, "semb")
    if semb is None:
        raise SystemExit(f"no semb in {args.build_dir}")
    out = args.package / "bin" / args.member
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    shutil.copy2(semb, out / semb.name)
    shutil.copyfile(args.build_dir / "generated" / "compile-flags.json", out / "compile-flags.json")
    (out / "engine-flags.json").write_bytes((json.dumps(engine_flags_record(prov), indent=2) + "\n").encode())
    if args.member == C63_MEMBER:
        c63 = executable(args.build_dir / "tests", "u2_10_c63_keeper_test")
        if c63 is None:
            raise SystemExit(f"no u2_10_c63_keeper_test in {args.build_dir / 'tests'}")
        shutil.copy2(c63, out / "c63.exe")
    if args.member == GPU_BINARY:
        shutil.copytree(args.shaders, out / "shaders")
    commit, digest = tree_identity(args.repo)
    write_json(out / "member.json", {
        "member": args.member, "enginePin": engine_pin_of(args.build_dir), "engineBuildRecord": record,
        "engineDispatch": prov["engine_build"].get("dispatch"), "productCommit": commit,
        "derivationInputsSha256": digest, "semb": semb.name,
    })
    print(f"staged {args.member}: {out}")
    return 0


def cmd_tools(args, environ: dict) -> int:
    tools = args.package / "bin" / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.probe_windows, tools / "host_cpuid.exe")
    shutil.copy2(args.probe_linux, tools / "host_cpuid")
    program = args.sf_roundtrip
    if program is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "roundtrip", args.repo / "tests" / "superfaiss_roundtrip" / "roundtrip.py")
        rt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rt)
        scratch = args.package.parent / (args.package.name + "-sf-build")
        shutil.rmtree(scratch, ignore_errors=True)
        scratch.mkdir(parents=True)
        tree = rt.export_superfaiss(rt.read_lock(args.repo / "superfaiss.lock"), args.superfaiss_source, scratch)
        program = rt.build_program(tree, scratch, "cmake", None)
    shutil.copy2(program, tools / "sf_roundtrip.exe")
    lock = dict(line.split("=", 1) for line in (args.repo / "superfaiss.lock").read_text(encoding="utf-8").split()
                if "=" in line)
    shown = subprocess.run(["git", "-C", args.superfaiss_source, "show", f"{lock['commit']}:tools/wvbank.py"],
                           capture_output=True, check=True).stdout
    (args.package / "harness").mkdir(parents=True, exist_ok=True)
    (args.package / "harness" / "wvbank.py").write_bytes(shown)
    write_json(tools / "tools.json", {"superfaissLock": lock})
    return 0


def cmd_finish(args, environ: dict) -> int:
    sys.path.insert(0, str(args.repo / "tests"))
    import c35_two_installation_harness as c35  # the one corpus conversion, checked against its manifest

    pkg = args.package
    for sub in ("artifacts", "corpus", "c63"):
        (pkg / sub).mkdir(parents=True, exist_ok=True)
    model, tokenizer = Path(args.model), Path(args.tokenizer)
    shutil.copyfile(model, pkg / "artifacts" / model.name)
    shutil.copyfile(tokenizer, pkg / "artifacts" / tokenizer.name)
    c35.corpus_jsonl(pkg / "corpus")  # writes corpus/corpus-239.idtext.jsonl
    for name in ("mid.txt", "short.txt"):
        shutil.copyfile(args.repo / "tests" / "fixtures" / "c63" / name, pkg / "c63" / name)
    harness = pkg / "harness"
    for rel in ("tests/superfaiss_roundtrip/roundtrip.py", "tests/te230_c5_floor.py",
                "tests/fixtures/c12b/corpus-239.jsonl", "tools/readiness/readiness.py"):
        (harness / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.repo / rel, harness / rel)
    for name in ("run_certify.ps1", "README.txt", "gpu-legs.json"):
        shutil.copyfile(HERE / name, pkg / name)
    commit, digest = tree_identity(args.repo)
    write_json(pkg / "package.json", {
        "schemaVersion": 1, "productCommit": commit, "derivationInputsSha256": digest,
        "members": list(MEMBERS), "gpuBinary": GPU_BINARY, "wslMember": WSL_MEMBER, "wslDistro": "Ubuntu-24.04",
        "model": {"file": model.name, "sha256": sha256_file(pkg / "artifacts" / model.name)},
        "tokenizer": {"file": tokenizer.name, "sha256": sha256_file(pkg / "artifacts" / tokenizer.name)},
        "corpus": "corpus/corpus-239.idtext.jsonl", "certificationRelease": "1.0.0",
    })
    print(f"finished {pkg}")
    return 0


def cmd_receipts(args, environ: dict) -> int:
    for cell in FORCED_CELLS:
        src = args.source_results / "docs" / "certification" / "1.0.0" / cell
        dst = args.package / "receipts" / cell
        dst.mkdir(parents=True, exist_ok=True)
        for name in RUN_FILES + ("run.json",):
            shutil.copyfile(src / name, dst / name)
    return 0


def main(argv: list[str], environ: dict | None = None) -> int:
    environ = dict(os.environ) if environ is None else environ
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="step", required=True)
    p = sub.add_parser("pin")
    p.add_argument("--member", required=True)
    p.add_argument("--engine-prefix", type=Path, required=True)
    p.add_argument("--source", required=True, help="a SuperSLM clone holding the pinned tag")
    p.add_argument("--lock", type=Path, default=REPO / "superslm.lock")
    p.add_argument("--workdir", type=Path, default=None)
    p.add_argument("--repo", type=Path, default=REPO)
    p = sub.add_parser("build")
    p.add_argument("--member", required=True)
    p.add_argument("--engine-prefix", type=Path, required=True)
    p.add_argument("--build-dir", type=Path, required=True)
    p.add_argument("--source-dir", type=Path, default=REPO)
    p = sub.add_parser("stage")
    p.add_argument("--package", type=Path, required=True)
    p.add_argument("--member", required=True)
    p.add_argument("--build-dir", type=Path, required=True)
    p.add_argument("--engine-prefix", type=Path, required=True)
    p.add_argument("--shaders", type=Path, default=None)
    p.add_argument("--repo", type=Path, default=REPO)
    p = sub.add_parser("tools")
    p.add_argument("--package", type=Path, required=True)
    p.add_argument("--probe-windows", type=Path, required=True)
    p.add_argument("--probe-linux", type=Path, required=True)
    p.add_argument("--sf-roundtrip", type=Path, default=None)
    p.add_argument("--superfaiss-source", required=True)
    p.add_argument("--repo", type=Path, default=REPO)
    p = sub.add_parser("finish")
    p.add_argument("--package", type=Path, required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--tokenizer", required=True)
    p.add_argument("--repo", type=Path, default=REPO)
    p = sub.add_parser("receipts")
    p.add_argument("--package", type=Path, required=True)
    p.add_argument("--from", dest="source_results", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.step == "pin" and args.workdir is None:
        args.workdir = args.engine_prefix.with_name(args.engine_prefix.name + "-workdir")
    steps = {"pin": cmd_pin, "build": cmd_build, "stage": cmd_stage, "tools": cmd_tools, "finish": cmd_finish,
             "receipts": cmd_receipts}
    try:
        return steps[args.step](args, environ)
    except Refused as refusal:
        print(str(refusal), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
