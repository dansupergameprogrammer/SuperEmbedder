"""Filesystem boundary regressions for the C12b commissioning harness.

Compiler processes are stubbed here; the separately registered commissioning
test exercises the real healthy instrument and PS-N arithmetic mutant.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import c12b_independent_commission_check as commission


class OutputConsumed(RuntimeError):
    pass


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="c12b-boundary-")
        self.root = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)
        self.source = self.root / "source"
        self.product = self.source / "src" / "superembedder" / "ps_n_pool.cpp"
        self.product.parent.mkdir(parents=True)
        self.original = ("// candidate bytes\r\n" + commission.MUTATION_FROM + "\r\n").encode()
        self.product.write_bytes(self.original)
        self.fixture = self.source / "build" / "_scratch" / "synthetic_te62_c39.sslm"
        self.fixture.parent.mkdir(parents=True)
        self.fixture.write_bytes(b"actual fixture\x00\xff")
        (self.source / "CMakeLists.txt").write_bytes(b"candidate cmake\r\n")

    def exercise(self, build_dir, *, failing_stage=None):
        build_dir.mkdir(parents=True, exist_ok=True)
        sentinel = build_dir / "keep.txt"
        sentinel.write_bytes(b"pre-existing user file\x00\xff")
        nested = build_dir / "user" / "nested.txt"
        nested.parent.mkdir()
        nested.write_bytes(b"pre-existing nested file")
        before = {p.relative_to(build_dir): p.read_bytes()
                  for p in build_dir.rglob("*") if p.is_file()}
        calls = []
        snapshots = []
        real_copytree = shutil.copytree
        real_copy2 = shutil.copy2

        def bounded_copytree(src, dst, *args, **kwargs):
            # Only instrument the outer snapshot call; copytree recursively calls
            # itself with positional arguments internally.
            if snapshots and Path(src).resolve().is_relative_to(snapshots[0]):
                raise OutputConsumed("snapshot consumed its own output")
            if Path(src).resolve() == self.source:
                destination = Path(dst).resolve()
                snapshots.append(destination)

                def bounded_copy(source_file, destination_file):
                    if Path(source_file).resolve().is_relative_to(destination):
                        raise OutputConsumed("snapshot consumed its own output")
                    return real_copy2(source_file, destination_file)

                kwargs["copy_function"] = bounded_copy
            return real_copytree(src, dst, *args, **kwargs)

        def fake_run(cmd, *, cwd, env=None):
            stage = len(calls)
            calls.append(cmd)
            if stage == 0:
                scratch = Path(cmd[cmd.index("--build-dir") + 1])
                scratch.mkdir(parents=True, exist_ok=True)
                (scratch / "baseline.txt").write_bytes(b"baseline output")
            if stage == 1:
                snapshot = Path(cmd[cmd.index("-S") + 1])
                self.assertEqual((snapshot / "CMakeLists.txt").read_bytes(), b"candidate cmake\r\n")
                changed = snapshot / self.product.relative_to(self.source)
                self.assertEqual(changed.read_text(), self.original.decode().replace("\r\n", "\n").replace(
                    commission.MUTATION_FROM, commission.MUTATION_TO))
                self.assertEqual((snapshot / self.fixture.relative_to(self.source)).read_bytes(), self.fixture.read_bytes())
                self.assertFalse(any(p.name == "baseline.txt" for p in snapshot.rglob("*")))
            if stage == failing_stage:
                return subprocess.CompletedProcess(cmd, 1, "injected failure", "")
            if stage == 3:
                return subprocess.CompletedProcess(cmd, 1, "[FAIL] S5 C1' oracle", "")
            return subprocess.CompletedProcess(cmd, 0, "PASS", "")

        argv = ["--instrument", str(self.root / "healthy.exe"), "--build-dir", str(build_dir),
                "--engine-prefix", str(self.root / "engine"), "--cmake-executable", "cmake",
                "--ninja-executable", "ninja", "--python-executable", sys.executable]
        try:
            with patch.object(commission, "REPO_ROOT", self.source), \
                    patch.object(commission, "run", side_effect=fake_run), \
                    patch.object(shutil, "copytree", side_effect=bounded_copytree), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = commission.main(argv)
            self.assertEqual(result, 0 if failing_stage is None else 1)
            self.assertEqual(len(calls), 4 if failing_stage is None else failing_stage + 1)
        finally:
            self.assertEqual(self.product.read_bytes(), self.original)
            self.assertEqual({p.relative_to(build_dir): p.read_bytes()
                              for p in build_dir.rglob("*") if p.is_file()}, before)
        for snapshot in snapshots:
            self.assertFalse(snapshot.exists(), "run-owned snapshot was not cleaned")

    def test_nonstandard_in_tree_build(self):
        self.exercise(self.source / "build-clang" / "commission")

    def test_conventional_build(self):
        self.exercise(self.source / "build" / "commission")

    def test_external_build(self):
        self.exercise(self.root / "external")

    def test_failed_baseline_preserves_user_files(self):
        self.exercise(self.root / "failed-baseline", failing_stage=0)

    def test_failed_configure_preserves_user_files(self):
        self.exercise(self.source / "build-clang", failing_stage=1)

    def test_failed_build_preserves_user_files(self):
        self.exercise(self.root / "failed-build", failing_stage=2)

    def test_omitted_destination_exclusion_is_detected(self):
        # Remove only the new path exclusion. The independent copy observer
        # must detect entry into the output, before an unbounded copy can run.
        with patch.object(commission, "snapshot_ignore", return_value=shutil.ignore_patterns(
                ".git", "build", "__pycache__", "*.pyc")):
            with self.assertRaisesRegex(OutputConsumed, "consumed its own output"):
                self.exercise(self.source / "build-clang" / "commission")

    def test_snapshot_preserves_candidate_bytes(self):
        with commission.owned_workspace(self.source / "unusual") as workspace:
            snapshot = workspace / "snapshot"
            commission.snapshot_source(self.source, snapshot, workspace)
            self.assertEqual((snapshot / self.product.relative_to(self.source)).read_bytes(), self.original)
            self.assertEqual((snapshot / "CMakeLists.txt").read_bytes(), b"candidate cmake\r\n")
            self.assertFalse((snapshot / workspace.relative_to(self.source)).exists())

    def test_snapshot_refuses_destination_outside_ownership(self):
        with commission.owned_workspace(self.root / "build") as workspace:
            destination = self.root / "foreign"
            with self.assertRaisesRegex(ValueError, "strict child"):
                commission.snapshot_source(self.source, destination, workspace)
            self.assertFalse(destination.exists())
            with self.assertRaisesRegex(ValueError, "strict child"):
                commission.snapshot_source(self.source, workspace, workspace)

    def test_cleanup_refuses_redirected_target(self):
        workspace = None
        resolve = Path.resolve

        def redirected(path, *args, **kwargs):
            if path == workspace:
                return self.source
            return resolve(path, *args, **kwargs)

        with patch.object(shutil, "rmtree") as delete:
            with patch.object(Path, "resolve", redirected):
                with self.assertRaisesRegex(RuntimeError, "refusing cleanup"):
                    with commission.owned_workspace(self.root / "build") as owned:
                        workspace = owned
                        (workspace / "run-file").write_bytes(b"owned")
            delete.assert_not_called()
        self.assertTrue((workspace / "run-file").exists())
        self.assertEqual(self.product.read_bytes(), self.original)

    def test_original_copy_recurses_on_bounded_fixture(self):
        # Reproduce the original algorithm independently on a tiny tree. A short
        # recursion limit plus a byte-copy budget bounds both path and disk use.
        source = self.root / "r"
        source.mkdir()
        (source / "f").write_bytes(b"x")
        destination = source / "b" / "m"
        destination.parent.mkdir()
        count = 0

        def bounded_copy(src, dst):
            nonlocal count
            count += 1
            if count > 64:
                raise RuntimeError("copy budget exceeded before recursion failure")
            return shutil.copy2(src, dst)

        old_limit = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(100)
            with self.assertRaises(RecursionError):
                shutil.copytree(source, destination, copy_function=bounded_copy,
                                ignore=shutil.ignore_patterns(".git", "build", "__pycache__", "*.pyc"))
        finally:
            sys.setrecursionlimit(old_limit)
        self.assertTrue((destination / "b" / "m" / "b" / "m").is_dir())
        self.assertLessEqual(count, 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
