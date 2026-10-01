"""U3 red suite: the CLI's device surface (te266 sec 4.5 C10 (i) G11, P:4177-4181;
sec 4.1's CLI paragraph, P:4050; sec 4.6 row 5 (f)'s disk leg, P:4215; row 7's
"no fallback", P:4217; docs/FORMAT.md sec 2.4's top-level `device` label).

The plan places these legs "in te230_semb_cli_check.py" (P:4177). They are kept
in this file so each red attributes to U3 alone and te230's own cells stay as
they are; folding them in is a move, not a change of construction.

Runs on the cap-512 synthetic pair (build/_scratch/te222_c17_pair, te230's own)
and the W-B corpus. Cells:

  G11-a    `bake` without --device writes the manifest's `device` = "cpu".
  G11-a'   pin: a CPU bake writes no gpu_* label (P:4125).
  G11-a''  must-accept of the option: `bake --device cpu` succeeds, writes
           `device` = "cpu" and the same .wvbank.bin as the default bake.
  G11-b    `bake --device tpu` exits nonzero and prints SEMB_DEVICE_UNSUPPORTED,
           before any open (no bank written).
  G11-c    `query --device gpu` returns the CPU query's vector: on a
           SEMB_BUILD_GPU=ON build on Windows (the dev box); elsewhere
           MISSING PREREQUISITE.
  G11-c'   must-accept of query's option, every build: `query --device cpu`
           returns the vector the default query returns.
  G11-d    `verify --device gpu` is refused (exit nonzero; verify takes no
           --device, P:4050).
  NF-off   SEMB_BUILD_GPU=OFF builds only (row 7 "no fallback"; P:4024):
           `bake --device gpu` and `query --device gpu` each exit nonzero and
           print SEMB_DEVICE_UNSUPPORTED; no bank is written.
  R5f-disk row 5 (f): `semb bake --device gpu` over a corpus whose 5th document
           is the guard document leaves the disk as the CPU bake does. GPU
           execution: MISSING PREREQUISITE off the dev box.

RED TODAY: G11-a, G11-a'', G11-b, G11-c', NF-off (bake ignores an unknown
option, and query refuses `--device` as unknown). G11-a' and G11-d are pins.
"""
from __future__ import annotations

import argparse
import filecmp
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import u3_cells_check as cells  # noqa: E402

FAILED = False


def emit(state: str, cell: str, detail: str) -> None:
    global FAILED
    print(f"[{state}] {cell}: {detail}", flush=True)
    FAILED |= state in ("FAIL", "RED-UNIMPLEMENTED")


def verdict(ok: bool, cell: str, detail: str) -> None:
    emit("PASS" if ok else "FAIL", cell, detail)


def call(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(args, cwd=ROOT, capture_output=True, timeout=timeout)
    dec = lambda b: b.decode("utf-8", errors="replace").replace("\r\n", "\n")
    return subprocess.CompletedProcess(p.args, p.returncode, dec(p.stdout), dec(p.stderr))


def manifest(stem: Path) -> dict:
    try:
        return json.loads(Path(str(stem) + ".semb.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def exists(stem: Path) -> bool:
    return any(Path(str(stem) + s).exists() for s in (".wvbank.json", ".wvbank.bin", ".semb.json"))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", type=Path, required=True)
    ap.add_argument("--cmake-executable", required=True)
    args = ap.parse_args(argv)
    build = args.build_dir.resolve()
    gpu_on = cells.cache_value(build, "SEMB_BUILD_GPU").upper() in ("ON", "TRUE", "1", "YES")
    on_devbox = gpu_on and platform.system() == "Windows"
    scratch = build / "_scratch" / "u3_cli"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)

    pair = ROOT / "build" / "_scratch" / "te222_c17_pair"
    if not (pair / "u1_pair_model.sslm").is_file():
        r = call([sys.executable, str(ROOT / "tests" / "fixtures" / "wq" / "regenerate_c17_highcap_pair_fixture.py"),
                  "--lock", "superslm.lock", "--out-dir", str(pair)], timeout=1800)
        if r.returncode:
            emit("FAIL", "fixture", (r.stdout + r.stderr)[-2000:])
            return 1
    base = ["--model", str(pair / "u1_pair_model.sslm"), "--tokenizer", str(pair / "u1_pair_tokenizer.sslm")]
    built = call([args.cmake_executable, "--build", str(build), "--target", "semb"], timeout=1800)
    semb = cells.find_exe(build, "semb")
    if built.returncode or semb is None:
        emit("FAIL", "CLI apparatus", (built.stdout + built.stderr)[-1500:])
        return 1
    corpus = ROOT / "tests" / "fixtures" / "wb" / "wb-corpus.jsonl"
    S = str(semb)

    # ---- G11-a / a' / a'' -------------------------------------------------
    default = scratch / "default"
    r = call([S, "bake", str(corpus), "--out", str(default), *base])
    m = manifest(default)
    if r.returncode:
        emit("FAIL", "G11 setup: the default bake", f"exit {r.returncode}: {(r.stdout + r.stderr)[-500:]}")
        return 1
    verdict(m.get("device") == "cpu", "G11-a bake without --device writes manifest device = \"cpu\" (P:4178)",
            f"device = {m.get('device', '(absent)')!r}")
    gpu_labels = sorted(k for k in m if k.startswith("gpu_"))
    verdict(not gpu_labels, "G11-a' pin: a CPU bake writes no gpu_* label (P:4125)",
            "none" if not gpu_labels else ", ".join(gpu_labels))
    cpu_opt = scratch / "cpu_opt"
    r = call([S, "bake", str(corpus), "--out", str(cpu_opt), "--device", "cpu", *base])
    same_bin = Path(str(cpu_opt) + ".wvbank.bin").is_file() and filecmp.cmp(
        str(default) + ".wvbank.bin", str(cpu_opt) + ".wvbank.bin", shallow=False)
    verdict(r.returncode == 0 and manifest(cpu_opt).get("device") == "cpu" and same_bin,
            "G11-a'' must-accept: bake --device cpu writes device = \"cpu\" and the default bake's rows (P:4050)",
            f"exit {r.returncode}, device = {manifest(cpu_opt).get('device', '(absent)')!r}, rows "
            f"{'equal' if same_bin else 'DIFFER or absent'}")

    # ---- G11-b -----------------------------------------------------------
    tpu = scratch / "tpu"
    r = call([S, "bake", str(corpus), "--out", str(tpu), "--device", "tpu", *base])
    out = r.stdout + r.stderr
    verdict(r.returncode != 0 and "SEMB_DEVICE_UNSUPPORTED" in out and not exists(tpu),
            "G11-b bake --device tpu exits nonzero, prints SEMB_DEVICE_UNSUPPORTED, writes nothing (P:4179, P:4050)",
            f"exit {r.returncode}, output {out.strip()[-160:]!r}, bank {'WRITTEN' if exists(tpu) else 'absent'}")

    # ---- G11-c / c' --------------------------------------------------------
    text = "a short query about the corpus"
    q_default = call([S, "query", str(default), text, "--hex", *base])
    q_cpu = call([S, "query", str(default), text, "--hex", "--device", "cpu", *base])
    verdict(q_default.returncode == 0 and q_cpu.returncode == 0 and q_cpu.stdout == q_default.stdout,
            "G11-c' must-accept: query --device cpu returns the default query's vector (P:4050)",
            f"exit {q_cpu.returncode}: {(q_cpu.stdout + q_cpu.stderr).strip()[-160:]!r}")
    if on_devbox:
        q_gpu = call([S, "query", str(default), text, "--hex", "--device", "gpu", *base])
        verdict(q_gpu.returncode == 0 and q_gpu.stdout == q_default.stdout,
                "G11-c query --device gpu returns the CPU query's vector (P:4180)",
                f"exit {q_gpu.returncode}")
    else:
        emit("MISSING PREREQUISITE", "G11-c query --device gpu returns the CPU query's vector (P:4180)",
             "GPU execution: Windows with SEMB_BUILD_GPU=ON (the dev box)")

    # ---- G11-d -------------------------------------------------------------
    r = call([S, "verify", str(default), "--corpus", str(corpus), "--device", "gpu", *base])
    verdict(r.returncode != 0, "G11-d verify --device gpu is refused (verify takes no --device; P:4181, P:4050)",
            f"exit {r.returncode}: {(r.stdout + r.stderr).strip()[-160:]!r}")

    # ---- NF-off --------------------------------------------------------------
    if not gpu_on:
        gstem = scratch / "gpu_off"
        r = call([S, "bake", str(corpus), "--out", str(gstem), "--device", "gpu", *base])
        out = r.stdout + r.stderr
        verdict(r.returncode != 0 and "SEMB_DEVICE_UNSUPPORTED" in out and not exists(gstem),
                "NF-off bake --device gpu in a SEMB_BUILD_GPU=OFF build refuses SEMB_DEVICE_UNSUPPORTED "
                "(no fallback; P:4024, P:4217)",
                f"exit {r.returncode}, output {out.strip()[-160:]!r}, bank {'WRITTEN' if exists(gstem) else 'absent'}")
        r = call([S, "query", str(default), text, "--hex", "--device", "gpu", *base])
        out = r.stdout + r.stderr
        verdict(r.returncode != 0 and "SEMB_DEVICE_UNSUPPORTED" in out,
                "NF-off query --device gpu in a SEMB_BUILD_GPU=OFF build refuses SEMB_DEVICE_UNSUPPORTED",
                f"exit {r.returncode}, output {out.strip()[-160:]!r}")
    else:
        emit("NOTE", "NF-off", "this build has SEMB_BUILD_GPU=ON; the OFF legs run in an OFF tree")

    # ---- R5f-disk ------------------------------------------------------------
    if on_devbox:
        guard = cells.ensure_pair("guard")
        gbase = ["--model", str(guard / "u1_pair_model.sslm"), "--tokenizer", str(guard / "u1_pair_tokenizer.sslm")]
        docs = ["one", "two", "three", "four", "abcdefgí", "six", "seven", "eight"]
        gcorpus = scratch / "guard-batch.jsonl"
        gcorpus.write_text("".join(json.dumps({"id": f"d{i}", "text": t}) + "\n" for i, t in enumerate(docs)),
                           encoding="utf-8")
        listing = {}
        for dev in ("cpu", "gpu"):
            d = scratch / f"r5f_{dev}"
            d.mkdir()
            r = call([S, "bake", str(gcorpus), "--out", str(d / "bank"), "--device", dev, *gbase])
            listing[dev] = (r.returncode, sorted(p.name for p in d.iterdir()))
        verdict(listing["cpu"] == listing["gpu"] and listing["cpu"][0] != 0,
                "R5f-disk bake --device gpu over the guard batch leaves the disk as the CPU bake does (P:4215 (f))",
                f"cpu {listing['cpu']}, gpu {listing['gpu']}")
    else:
        emit("MISSING PREREQUISITE", "R5f-disk bake --device gpu over the guard batch leaves the disk as the CPU "
             "bake does (P:4215 (f))", "GPU execution: Windows with SEMB_BUILD_GPU=ON (the dev box)")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
