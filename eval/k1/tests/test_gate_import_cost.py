"""Pins that ``eval.k1.gate`` stays free of the embedding stack (TE-40 code review, Finding
F-7 (Significant), `Claude/Poirot/41424b0-te40-k1-instrument-review.md`, Wizard project
records tree).

`gate.py` is the one module whose job is reading a JSON packet and computing pass/fail --
what a consumer imports to re-derive a verdict without the instrument, and what
`rescore_packet.py` imports. Before the fix, `gate.py` read its required-set roster from
`run_spec.py`, which imports `embed_runner.py`, which imports `torch` and `numpy` --
measured (review Section 4.9): at commit `0003151`, `gate.py` had zero first-party imports;
at `41424b0`, `import eval.k1.gate` took 2.74s and left `torch`/`numpy` resident.

Run in a fresh subprocess rather than in-process: other test modules in this suite import
torch/numpy for their own reasons, and a check against the current process's `sys.modules`
would be contaminated by whichever test ran first -- exactly the isolation Poirot's own
verification used (`import eval.k1.gate` cold)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_importing_gate_does_not_pull_in_torch_or_numpy():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import eval.k1.gate; print('torch' in sys.modules); print('numpy' in sys.modules)"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    torch_resident, numpy_resident = result.stdout.strip().splitlines()
    assert torch_resident == "False", "importing eval.k1.gate pulled in torch"
    assert numpy_resident == "False", "importing eval.k1.gate pulled in numpy"
