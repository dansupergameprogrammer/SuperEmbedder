"""U2 cloud build: the tokenizer manifest tool's recorded commands and its two
refusals, held without the real checkpoint.

tools/tokenizer/regenerate_qwen3_tokenizer_artifact.py records the converter
commands it ran in the manifest, path-free, and refuses two inputs by name.
Nothing else exercises that code short of a real --mint on a machine with the
Qwen3-Embedding-0.6B snapshot, so this check drives the tool's own functions
(portable_command, main) in-process, with the engine clone and the converter
replaced by in-memory fakes and every file under a temporary directory. It
never touches the network, the committed manifest or superslm.lock.

  (a) the corpus is recorded under $SUPEREMBEDDER_ROOT: portable_command on
      the verification command main builds, and a whole --mint --verify run
      (manifest redirected to scratch), both yield exactly the committed
      manifest's verification.command (and converter.emit_command);
  (b) an absolute path the tool did not rewrite is refused: portable_command
      raises NotPortable naming it, in either platform's form whatever this
      host is; and main, handed such an argument, exits 1 with
      SEMB_TOKENIZER_COMMAND_NOT_PORTABLE before the converter runs and
      writes no manifest;
  (c) the snapshot must sit at <hub cache>/models--Qwen--Qwen3-Embedding-0.6B/
      snapshots/<rev>: a directory with the right leaf but a wrong parent or
      grandparent exits 1 with SEMB_TOKENIZER_SNAPSHOT_LAYOUT, while the right
      layout gets past it (the --mint run in (a)).

Each cell fails if the code it holds is reverted.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "tools" / "tokenizer" / "regenerate_qwen3_tokenizer_artifact.py"
MANIFEST = REPO_ROOT / "tests" / "fixtures" / "tokenizer" / "qwen3-embedding-0.6b-tokenizer.manifest.json"
CORPUS_RECORDED = "$SUPEREMBEDDER_ROOT/tests/fixtures/tokenizer/tokenizer_golden_corpus.jsonl"
FAKE_HEAD = "0" * 40


def load_tool():
    spec = importlib.util.spec_from_file_location("semb_regen_qwen3_tokenizer_under_test", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_snapshot(parent: Path, rev: str) -> Path:
    snap = parent / rev
    snap.mkdir(parents=True)
    (snap / "tokenizer.json").write_text("{}", encoding="utf-8")
    (snap / "tokenizer_config.json").write_text("{}", encoding="utf-8")
    return snap


class Fakes:
    """Stands in for the engine clone and the converter: records every command
    main runs and answers it the way a passing converter would."""

    def __init__(self, mod):
        self.mod = mod
        self.calls: list[list[str]] = []
        n = sum(1 for line in mod.CORPUS.read_text(encoding="utf-8").splitlines() if line)
        self.verify_text = (f"bpe-parity: {n} lines, 0 mismatches\n"
                            f"post-processor-parity: {n} lines, 0 mismatches "
                            f"trailing_special_id={mod.EXPECTED_TRAILING_SPECIAL_ID}\n")

    def clone_engine(self, tag, source, workdir):
        (Path(workdir) / "tools").mkdir(parents=True, exist_ok=True)
        return Path(workdir)

    def run(self, cmd, **kwargs):
        cmd = [str(c) for c in cmd]
        self.calls.append(cmd)
        if cmd and Path(cmd[0]).stem.lower() == "git":
            return subprocess.CompletedProcess(cmd, 0, stdout=FAKE_HEAD + "\n", stderr="")
        if "--emit" in cmd:
            Path(cmd[cmd.index("--emit") + 1]).write_bytes(b"fake tokenizer artifact")
            return subprocess.CompletedProcess(cmd, 0, stdout="emitted", stderr="")
        if "--verify" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=self.verify_text, stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    def converter_calls(self) -> list[list[str]]:
        return [c for c in self.calls if "convert_tokenizer.py" in c]


def run_main(mod, argv, fakes: Fakes, manifest_path: Path, patches: dict | None = None):
    """main(argv) with the clone and the converter faked and the manifest
    redirected; returns (exit code or exception, stdout, stderr)."""
    saved = {k: getattr(mod, k) for k in ("clone_engine", "subprocess", "MANIFEST", *(patches or {}))}
    mod.clone_engine = fakes.clone_engine
    mod.subprocess = types.SimpleNamespace(run=fakes.run, CalledProcessError=subprocess.CalledProcessError)
    mod.MANIFEST = manifest_path
    for k, v in (patches or {}).items():
        setattr(mod, k, v)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = mod.main([str(a) for a in argv])
            except Exception as ex:  # noqa: BLE001 -- a raise is a verdict, not a crash
                rc = ex
    finally:
        for k, v in saved.items():
            setattr(mod, k, v)
    return rc, out.getvalue(), err.getvalue()


def main() -> int:
    fails = 0

    def verdict(ok: bool, cell: str, detail: str) -> None:
        nonlocal fails
        fails += 0 if ok else 1
        print(f"[{'PASS' if ok else 'FAIL'}] {cell}: {detail}")

    committed = json.loads(MANIFEST.read_text(encoding="utf-8"))
    want_verify = committed["verification"]["command"]
    want_emit = committed["converter"]["emit_command"]
    verdict(want_verify.count(CORPUS_RECORDED) == 2,
            "(a) the committed manifest records the corpus under $SUPEREMBEDDER_ROOT (twice)", want_verify)

    mod = load_tool()
    rev = mod.CANDIDATE_REVISION

    with tempfile.TemporaryDirectory(prefix="semb_tokcmd_") as tmp_s:
        tmp = Path(tmp_s)
        hub = tmp / "hub"
        snapshot = make_snapshot(hub / mod.SNAPSHOT_REPO_DIR / "snapshots", rev)
        out = (tmp / "out" / mod.CANONICAL_ARTIFACT_NAME).resolve()
        lock = tmp / "superslm.lock"
        lock.write_text("tag=v0.0.0-test\ncommit=" + FAKE_HEAD + "\n", encoding="utf-8")
        common = ["--snapshot", snapshot, "--out", out, "--lock", lock, "--source", tmp / "no-remote"]

        # (a) portable_command on the command main builds.
        exe = sys.executable
        ver_cmd = [exe, "convert_tokenizer.py", "--ckpt", str(snapshot),
                   "--verify", str(mod.CORPUS), "--verify-post-processor", str(mod.CORPUS)]
        emit_cmd = [exe, "convert_tokenizer.py", "--ckpt", str(snapshot), "--emit", str(out)]
        try:
            got_verify = mod.portable_command(ver_cmd, snapshot, out)
        except Exception as ex:  # noqa: BLE001
            got_verify = f"raised {type(ex).__name__}: {ex}"
        verdict(got_verify == want_verify,
                "(a) portable_command(verification command) == the committed manifest's", got_verify)
        try:
            got_emit = mod.portable_command(emit_cmd, snapshot, out)
        except Exception as ex:  # noqa: BLE001
            got_emit = f"raised {type(ex).__name__}: {ex}"
        verdict(got_emit == want_emit, "(a) portable_command(emit command) == the committed manifest's", got_emit)

        # (a) + (c) positive: a whole --mint --verify run over the right layout.
        fakes = Fakes(mod)
        minted = tmp / "minted.manifest.json"
        rc, so, se = run_main(mod, common + ["--workdir", tmp / "work-mint", "--verify", "--mint"],
                              fakes, minted)
        verdict(rc == 0 and minted.exists(),
                "(c) the right snapshot layout gets past the layout check; --mint --verify exits 0",
                f"exit {rc!r}; {se.strip()[:300]}")
        rec = json.loads(minted.read_text(encoding="utf-8")) if minted.exists() else {}
        got = (rec.get("verification") or {}).get("command")
        verdict(got == want_verify, "(a) a --mint --verify run records the committed verification.command", str(got))
        got = (rec.get("converter") or {}).get("emit_command")
        verdict(got == want_emit, "(a) a --mint run records the committed converter.emit_command", str(got))
        verify_runs = [c for c in fakes.converter_calls() if "--verify" in c]
        verdict(len(verify_runs) == 1 and verify_runs[0].count(str(mod.CORPUS)) == 2,
                "(a) the converter itself is handed the real corpus path (only the record is rewritten)",
                str(verify_runs))

        # (b) portable_command refuses what it did not rewrite, in both platforms' forms.
        for leak in ("/elsewhere/corpus.jsonl", "\\\\server\\share\\corpus.jsonl",
                     "C:\\elsewhere\\corpus.jsonl", "C:/elsewhere/corpus.jsonl"):
            try:
                got = mod.portable_command(emit_cmd + ["--extra", leak], snapshot, out)
                ok, detail = False, f"recorded {got!r}"
            except Exception as ex:  # noqa: BLE001
                ok = type(ex).__name__ == "NotPortable" and repr(leak) in str(ex)
                detail = f"{type(ex).__name__}: {ex}"
            verdict(ok, f"(b) portable_command refuses the unrewritten absolute {leak!r} by name", detail)
        try:
            got = mod.portable_command(emit_cmd + ["--extra", "relative/corpus.jsonl"], snapshot, out)
            ok, detail = got.endswith("--extra relative/corpus.jsonl"), got
        except Exception as ex:  # noqa: BLE001
            ok, detail = False, f"{type(ex).__name__}: {ex}"
        verdict(ok, "(b) control: a relative argument is recorded, not refused", detail)

        # (b) main: an argument it has no rewrite for is refused before the converter runs.
        leak = str((tmp / "unrewritten" / "corpus.jsonl").resolve())
        real_portable = mod.portable_command

        def leaky_portable(cmd, snap, o):
            return real_portable(list(cmd) + ["--extra", leak], snap, o)

        fakes = Fakes(mod)
        refused = tmp / "refused.manifest.json"
        rc, so, se = run_main(mod, common + ["--workdir", tmp / "work-leak", "--verify", "--mint"],
                              fakes, refused, {"portable_command": leaky_portable})
        verdict(rc == 1 and "SEMB_TOKENIZER_COMMAND_NOT_PORTABLE" in se and repr(leak) in se,
                "(b) main exits 1 with SEMB_TOKENIZER_COMMAND_NOT_PORTABLE naming the path",
                f"exit {rc!r}; {se.strip()[:300]}")
        verdict(not fakes.converter_calls() and not refused.exists(),
                "(b) ... before the converter runs, and writes no manifest",
                f"converter runs {len(fakes.converter_calls())}; manifest written {refused.exists()}")

        # (c) a snapshot with the right leaf but the wrong structure above it.
        bad = {
            "no snapshots/ parent": tmp / "flat",
            "wrong repo directory": tmp / "hub2" / "models--Other--Model" / "snapshots",
            "wrong parent name": tmp / "hub3" / mod.SNAPSHOT_REPO_DIR / "revisions",
        }
        for label, parent in bad.items():
            snap = make_snapshot(parent, rev)
            fakes = Fakes(mod)
            m = tmp / f"layout-{len(label)}.manifest.json"
            argv = ["--snapshot", snap, "--out", out, "--lock", lock, "--source", tmp / "no-remote",
                    "--workdir", tmp / "work-layout", "--mint"]
            rc, so, se = run_main(mod, argv, fakes, m)
            verdict(rc == 1 and "SEMB_TOKENIZER_SNAPSHOT_LAYOUT" in se and not fakes.calls and not m.exists(),
                    f"(c) {label}: exit 1 with SEMB_TOKENIZER_SNAPSHOT_LAYOUT, nothing run",
                    f"exit {rc!r}; commands run {len(fakes.calls)}; {se.strip()[:200]}")

    print(f"TOTAL fail={fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
