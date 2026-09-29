"""U3 red suite: C10's real-artifact GPU legs (te266 sec 4.5 C10 (a), (b), (g),
(h), (i), P:4151-4181). Dev box only: Windows, SEMB_BUILD_GPU=ON, the real
model and tokenizer (SEMB_C12B_MODEL / SEMB_U1_TOKENIZER). Anywhere else every
leg prints MISSING PREREQUISITE and exits 77.

One leg per invocation (--leg), one ctest per leg, so a dev-box step is short
and a crash loses one leg. Every bank a leg writes lives under
build/_u3_real/<leg>/ and is reused when complete (a manifest beside a bin of
the right size), so re-running a leg after a crash resumes after its bakes.
Every command's output is appended to build/_u3_logs/real_<leg>.log as it runs.

  a         (P:4151-4152) `semb bake --device gpu` and `--device cpu` over the
            239-document corpus (tests/fixtures/c12b/corpus-239.jsonl): the two
            runs' row-digests.tsv (tests/u3_row_digest_pair.py derive) identical
            on 239/239 rows; then u3_gpu_cells_test --cell c10a_anchors, and every
            GPU psn_selected equals the committed anchors'
            (tests/fixtures/c12b/anchors-*.tsv, psn_selected_sha256).
  e2        (P:4162) u3_gpu_cells_test --cell c10e2's tsv pair must be REFUSED by
            the pairwise instrument.
  b         (P:4153) composition, on (a)'s banks: the CPU bank queried with
            --device gpu and the GPU bank with --device cpu are both accepted, and
            the query vectors for W-Q's set and 50 corpus texts are identical
            across devices; with --off-build-dir, that OFF build's semb opens the
            GPU bank and returns the same vectors (pins sec 4.3's engine_path_id
            rule).
  g4096, g8192, gcap   (P:4168-4170) u3_gpu_cells_test --cell c10g at 4,096,
            8,192 and 32,767 content tokens (the cap row: two GPU runs, no CPU
            half, D-SLM7722). ~2 min, ~6 min + 2.1 h CPU, ~2 x 78 min.
  h         (P:4171 as restated by the planner's U3 ruling 3) fiqa-long80
            (D-SLM7873; --c10h-corpus, SEMB_U3_C10H_CORPUS), 80 documents:
            `semb bake --device gpu` and `--device cpu` (the CLI's default of 8
            workers), both from this tree, and the pairwise instrument finds the
            two row-digests.tsv equal on 80/80 rows. K1-Run-2's corpora are
            deleted and unrecoverable (TE-439), so the leg is reduced to this one
            population. The input's sha256 is checked FIRST, on any host, and a
            mismatch is refused before anything runs. Must-reject: C10 (e) 3's
            one-byte edit, applied to one row of the GPU run's row-digests.tsv,
            is REFUSED by the same instrument.
  i_verify  (P:4174) `semb verify` over (a)'s GPU bank exits 0; its must-reject,
            one byte of a copy's row file edited, is refused.
  i_install (P:4175) `cmake --install` to a scratch prefix, then that prefix's
            `semb bake --device gpu` over 16 documents gives the CPU's rows; its
            must-reject, the same prefix with shaders/ removed, refuses
            SEMB_DEVICE_UNAVAILABLE.
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import u3_cells_check as cells  # noqa: E402
import u3_row_digest_pair as pair  # noqa: E402

sys.path.insert(0, str(ROOT / "tests" / "fixtures" / "u3"))
import fiqa_sets  # noqa: E402

CORPUS = ROOT / "tests" / "fixtures" / "c12b" / "corpus-239.jsonl"
WQ = ROOT / "tests" / "fixtures" / "wq" / "wq-queries.jsonl"
FAILED = False
LOG = None


def emit(state: str, leg: str, detail: str) -> None:
    global FAILED
    line = f"[{state}] {leg}: {detail}"
    print(line, flush=True)
    if LOG:
        LOG.write(line + "\n")
        LOG.flush()
    FAILED |= state in ("FAIL", "RED-UNIMPLEMENTED")


def run(cmd: list[str], timeout: int = 6 * 3600) -> subprocess.CompletedProcess[str]:
    if LOG:
        LOG.write("$ " + " ".join(cmd) + "\n")
        LOG.flush()
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=timeout)
    out = p.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    err = p.stderr.decode("utf-8", "replace").replace("\r\n", "\n")
    if LOG:
        LOG.write(out[-4000:] + err[-4000:] + f"(exit {p.returncode})\n")
        LOG.flush()
    return subprocess.CompletedProcess(p.args, p.returncode, out, err)


def complete(stem: Path) -> bool:
    try:
        h = json.loads(Path(str(stem) + ".wvbank.json").read_text(encoding="utf-8"))
        return (Path(str(stem) + ".semb.json").is_file()
                and Path(str(stem) + ".wvbank.bin").stat().st_size == int(h["count"]) * int(h["dims"]) * 4)
    except (OSError, ValueError, KeyError):
        return False


def bake(semb: str, corpus: Path, stem: Path, device: str, base: list[str]) -> bool:
    if complete(stem):
        return True
    stem.parent.mkdir(parents=True, exist_ok=True)
    r = run([semb, "bake", str(corpus), "--out", str(stem), "--device", device, *base])
    return r.returncode == 0 and complete(stem)


def texts(path: Path, n: int | None = None) -> list[tuple[str, str]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line)
            out.append((str(o.get("id", len(out))), o["text"]))
    return out[:n] if n else out


def main(argv: list[str]) -> int:
    global LOG
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--cmake-executable", required=True)
    ap.add_argument("--leg", required=True)
    ap.add_argument("--real-model", default="")
    ap.add_argument("--real-tokenizer", default="")
    ap.add_argument("--off-build-dir", default="")
    ap.add_argument("--c10h-corpus", default="")
    args = ap.parse_args(argv)
    build = Path(args.build_dir).resolve()
    leg = args.leg
    if leg == "h":
        # Ruling 3: the input's sha256 first, before anything runs, on any host.
        st, detail = fiqa_sets.check_long80(args.c10h_corpus)
        if st == "MISSING":
            return cells.missing(f"C10 (h): {detail} (SEMB_U3_C10H_CORPUS)")
        print(f"[{st}] C10 (h) input is fiqa-long80: {detail}", flush=True)
        if st != "PASS":
            return 1
    if platform.system() != "Windows":
        return cells.missing(f"C10 {leg}: GPU execution needs Windows and D3D12 (this host is {platform.system()})")
    if cells.cache_value(build, "SEMB_BUILD_GPU").upper() not in ("ON", "TRUE", "1", "YES"):
        return cells.missing(f"C10 {leg}: the build tree is not configured with SEMB_BUILD_GPU=ON")
    if leg != "e2" and not (args.real_model and Path(args.real_model).is_file() and args.real_tokenizer
                            and Path(args.real_tokenizer).is_file()):
        return cells.missing(f"C10 {leg}: the real artifact (SEMB_C12B_MODEL / SEMB_U1_TOKENIZER) is not configured")
    (build / "_u3_logs").mkdir(parents=True, exist_ok=True)
    LOG = open(build / "_u3_logs" / f"real_{leg}.log", "a", encoding="utf-8")
    base = ["--model", args.real_model, "--tokenizer", args.real_tokenizer]
    work = build / "_u3_real"
    r = run([args.cmake_executable, "--build", str(build), "--target", "semb", "u3_gpu_cells_test"])
    if r.returncode:
        syms = cells.undefined_symbols(r.stdout + r.stderr)
        emit("RED-UNIMPLEMENTED" if syms else "FAIL", f"C10 {leg} apparatus",
             ("undefined: " + ", ".join(syms)) if syms else (r.stdout + r.stderr)[-1500:])
        return 1
    semb = str(cells.find_exe(build, "semb"))
    gcells = str(cells.find_exe(build, "u3_gpu_cells_test"))
    a_gpu, a_cpu = work / "a" / "gpu", work / "a" / "cpu"

    if leg == "a":
        ok_g, ok_c = bake(semb, CORPUS, a_gpu, "gpu", base), bake(semb, CORPUS, a_cpu, "cpu", base)
        if not (ok_g and ok_c):
            emit("FAIL", "C10 (a) the two bakes", f"gpu {'ok' if ok_g else 'FAILED'}, cpu {'ok' if ok_c else 'FAILED'}")
        else:
            try:
                got = pair.compare(pair.derive(str(a_gpu)), pair.derive(str(a_cpu)), "gpu", "cpu")
                emit("PASS", "C10 (a) GPU and CPU row-digests.tsv identical (P:4151)", got)
            except pair.Refused as ex:
                emit("FAIL", "C10 (a) GPU and CPU row-digests.tsv identical (P:4151)", str(ex))
        tfile = work / "a" / "texts.tsv"
        tfile.parent.mkdir(parents=True, exist_ok=True)
        tfile.write_text("".join(f"{i}\t{t.encode('utf-8').hex()}\n" for i, t in texts(CORPUS)), encoding="utf-8")
        scratch = work / "a" / "anchors"
        scratch.mkdir(parents=True, exist_ok=True)
        r = run([gcells, "--cell", "c10a_anchors", *base, "--texts", str(tfile), "--scratch", str(scratch)])
        anchors = sorted((ROOT / "tests" / "fixtures" / "c12b").glob("anchors-*.tsv"))
        want = {}
        for line in anchors[-1].read_text(encoding="utf-8").splitlines() if anchors else []:
            if line and not line.startswith("#"):
                f = line.split("\t")
                want[f[0]] = f[3]
        got_rows = {}
        psn = scratch / "c10a-gpu-psn.tsv"
        for line in psn.read_text(encoding="utf-8").splitlines() if psn.is_file() else []:
            k, v = line.split("\t")
            got_rows[k] = v
        diff = [k for k in want if got_rows.get(k) != want[k]]
        emit("PASS" if want and not diff and r.returncode == 0 else "FAIL",
             "C10 (a) every GPU psn_selected equals the committed anchors (P:4151)",
             f"{len(want) - len(diff)}/{len(want)} equal" + (f"; first differing: {diff[:5]}" if diff else "")
             + ("" if r.returncode == 0 else f"; the cell exited {r.returncode}"))
    elif leg == "e2":
        scratch = work / "e2"
        scratch.mkdir(parents=True, exist_ok=True)
        pairdir = cells.ensure_pair("u1")
        r = run([gcells, "--cell", "c10e2", "--model", str(pairdir / "u1_pair_model.sslm"), "--tokenizer",
                 str(pairdir / "u1_pair_tokenizer.sslm"), "--scratch", str(scratch)])
        try:
            pair.compare((scratch / "c10e2-gpu.tsv").read_bytes(), (scratch / "c10e2-cpu.tsv").read_bytes())
            emit("FAIL", "C10 (e) 2 the perturbation after the check turns (a) red (P:4162)",
                 "the instrument ACCEPTED the perturbed pair")
        except (pair.Refused, OSError) as ex:
            emit("PASS" if r.returncode in (0, 1) and isinstance(ex, pair.Refused) else "FAIL",
                 "C10 (e) 2 the perturbation after the check turns (a) red (P:4162)", f"REFUSED: {ex}")
    elif leg == "b":
        if not (complete(a_gpu) and complete(a_cpu)):
            return cells.missing("C10 (b): run leg a first (its two banks are the inputs)")
        qs = [t for _, t in texts(WQ)] + [t for _, t in texts(CORPUS, 50)]
        bad = []
        for q in qs:
            v = {}
            for stem, dev in ((a_cpu, "gpu"), (a_gpu, "cpu"), (a_cpu, "cpu")):
                rr = run([semb, "query", str(stem), "--hex", "--device", dev, *base, "--", q], timeout=900)
                v[(stem.name, dev)] = (rr.returncode, rr.stdout)
            if len(set(v.values())) != 1 or next(iter(v.values()))[0] != 0:
                bad.append(q[:40])
        emit("PASS" if not bad else "FAIL",
             "C10 (b) CPU bank by a GPU query and GPU bank by a CPU query accepted; vectors identical (P:4153)",
             f"{len(qs) - len(bad)}/{len(qs)} queries identical" + (f"; first: {bad[:3]}" if bad else ""))
        if args.off_build_dir:
            off = cells.find_exe(Path(args.off_build_dir), "semb")
            ref = run([semb, "query", str(a_cpu), "--hex", "--device", "cpu", *base, "--", qs[0]])
            rr = run([str(off), "query", str(a_gpu), "--hex", *base, "--", qs[0]]) if off else None
            emit("PASS" if rr and rr.returncode == 0 and rr.stdout == ref.stdout else "FAIL",
                 "C10 (b) a GPU-baked bank opened by a SEMB_BUILD_GPU=OFF build is accepted (P:4153)",
                 "accepted, same vector" if rr and rr.returncode == 0 and rr.stdout == ref.stdout else
                 (f"exit {rr.returncode}: {(rr.stdout + rr.stderr)[-200:]}" if rr else "no semb in --off-build-dir"))
        else:
            emit("MISSING PREREQUISITE", "C10 (b) the OFF-build reader (P:4153)",
                 "--off-build-dir <a SEMB_BUILD_GPU=OFF tree of this commit>")
    elif leg in ("g4096", "g8192", "gcap"):
        n = {"g4096": "4096", "g8192": "8192", "gcap": "32767"}[leg]
        extra = ["--runs", "2"] if leg == "gcap" else []
        scratch = work / leg
        scratch.mkdir(parents=True, exist_ok=True)
        r = run([gcells, "--cell", "c10g", *base, "--positions", n, *extra, "--scratch", str(scratch)], timeout=8 * 3600)
        print(r.stdout)
        for line in r.stdout.splitlines():
            if LOG:
                LOG.write(line + "\n")
        if r.returncode:
            emit("FAIL", f"C10 (g) {n} tokens", f"the cell exited {r.returncode}")
    elif leg == "h":
        corpus = Path(args.c10h_corpus)
        gpu, cpu = work / "h" / "fiqa-long80-gpu", work / "h" / "fiqa-long80-cpu"
        ok_g, ok_c = bake(semb, corpus, gpu, "gpu", base), bake(semb, corpus, cpu, "cpu", base)
        if not (ok_g and ok_c):
            emit("FAIL", "C10 (h) the two bakes of fiqa-long80",
                 f"gpu {'ok' if ok_g else 'FAILED'}, cpu {'ok' if ok_c else 'FAILED'}")
        else:
            tg, tc = pair.derive(str(gpu)), pair.derive(str(cpu))
            (work / "h" / "gpu-row-digests.tsv").write_bytes(tg)
            (work / "h" / "cpu-row-digests.tsv").write_bytes(tc)
            try:
                got = pair.compare(tg, tc, "gpu", "cpu")
                want = f"{fiqa_sets.FIQA_LONG80_ROWS}/{fiqa_sets.FIQA_LONG80_ROWS} rows identical"
                emit("PASS" if got == want else "FAIL",
                     "C10 (h) fiqa-long80: GPU rows byte-equal to this build's CPU bake on 80/80 (P:4171)", got)
            except pair.Refused as ex:
                emit("FAIL", "C10 (h) fiqa-long80: GPU rows byte-equal to this build's CPU bake on 80/80 (P:4171)",
                     str(ex))
            edited = bytearray(tg)
            pos = edited.index(b"\t") + 1 + 10  # one hex digit of row 0's digest
            edited[pos] = ord("0") if edited[pos] != ord("0") else ord("1")
            try:
                got = pair.compare(bytes(edited), tc, "gpu-edited", "cpu")
                emit("FAIL", "C10 (h) must-reject: C10 (e) 3's one-byte edit of one fiqa-long80 row is refused",
                     f"ACCEPTED ({got})")
            except pair.Refused as ex:
                emit("PASS", "C10 (h) must-reject: C10 (e) 3's one-byte edit of one fiqa-long80 row is refused",
                     f"REFUSED ({ex})")
    elif leg == "i_verify":
        if not complete(a_gpu):
            return cells.missing("C10 (i) verify: run leg a first (its GPU bank is the input)")
        r = run([semb, "verify", str(a_gpu), "--corpus", str(CORPUS), *base])
        emit("PASS" if r.returncode == 0 else "FAIL", "C10 (i) G8 semb verify over (a)'s GPU bank exits 0 (P:4174)",
             f"exit {r.returncode}: {(r.stdout + r.stderr).strip()[-200:]}")
        edited = work / "i_verify" / "edited"
        edited.parent.mkdir(parents=True, exist_ok=True)
        for s in (".wvbank.json", ".wvbank.bin", ".semb.json"):
            shutil.copy2(str(a_gpu) + s, str(edited) + s)
        b = bytearray(Path(str(edited) + ".wvbank.bin").read_bytes())
        b[len(b) // 2] ^= 0x01
        Path(str(edited) + ".wvbank.bin").write_bytes(bytes(b))
        r = run([semb, "verify", str(edited), "--corpus", str(CORPUS), *base])
        emit("PASS" if r.returncode != 0 else "FAIL", "C10 (i) G8 must-reject: one byte of the row file edited is "
             "refused by verify (P:4174)", f"exit {r.returncode}: {(r.stdout + r.stderr).strip()[-200:]}")
    elif leg == "i_install":
        prefix = work / "i_install" / "prefix"
        shutil.rmtree(prefix, ignore_errors=True)
        r = run([args.cmake_executable, "--install", str(build), "--prefix", str(prefix)])
        isemb = cells.find_exe(prefix, "semb")
        if r.returncode or not isemb:
            emit("FAIL", "C10 (i) G9 cmake --install to a scratch prefix", (r.stdout + r.stderr)[-800:])
        else:
            c16 = work / "i_install" / "c16.jsonl"
            c16.write_text("".join(json.dumps({"id": i, "text": t}) + "\n" for i, t in texts(CORPUS, 16)),
                           encoding="utf-8")
            g, c = work / "i_install" / "gpu", work / "i_install" / "cpu"
            for s in (g, c):
                for suf in (".wvbank.json", ".wvbank.bin", ".semb.json"):
                    Path(str(s) + suf).unlink(missing_ok=True)
            rg = run([str(isemb), "bake", str(c16), "--out", str(g), "--device", "gpu", *base])
            rc = run([semb, "bake", str(c16), "--out", str(c), "--device", "cpu", *base])
            same = complete(g) and complete(c) and Path(str(g) + ".wvbank.bin").read_bytes() == Path(
                str(c) + ".wvbank.bin").read_bytes()
            emit("PASS" if rg.returncode == 0 and rc.returncode == 0 and same else "FAIL",
                 "C10 (i) G9 the installed tree's semb bake --device gpu over 16 documents gives the CPU rows (P:4175)",
                 f"gpu exit {rg.returncode}, cpu exit {rc.returncode}, rows {'equal' if same else 'DIFFER'}")
            shaders = [p for p in prefix.rglob("shaders") if p.is_dir()]
            for p in shaders:
                shutil.rmtree(p)
            rr = run([str(isemb), "bake", str(c16), "--out", str(work / "i_install" / "noshaders"), "--device", "gpu",
                      *base])
            emit("PASS" if shaders and rr.returncode != 0 and "SEMB_DEVICE_UNAVAILABLE" in rr.stdout + rr.stderr
                 else "FAIL", "C10 (i) G9 must-reject: the prefix with shaders/ removed refuses SEMB_DEVICE_UNAVAILABLE",
                 f"shaders dirs removed: {len(shaders)}; exit {rr.returncode}: {(rr.stdout + rr.stderr).strip()[-200:]}")
    else:
        emit("FAIL", "u3_gpu_real_check", f"unknown --leg {leg}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
