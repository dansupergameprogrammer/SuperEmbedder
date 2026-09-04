"""Incident pin for the non-square-candidate q_width port defect.

Qwen3-Embedding-0.6B has hidden_size=1024 but
num_attention_heads*head_dim=2048.  SuperSLM's backward-compatible default
derives q_width from hidden_size, so omitting the explicit argument is silent
and every square synthetic fixture accepts it.  This check is deliberately
structural: hosted CI does not carry the 633 MB candidate, but must still
reject either the old derivation or any missing call-site argument.

This file was authored during the independent integration review, not by the
U1/C12b product builder.  Its two in-memory mutants commission both halves of
the check before the real source is graded.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
ADAPTER = REPO_ROOT / "src" / "superembedder" / "engine_adapter_interim.cpp"
DERIVATION = "m->q_width = static_cast<size_t>(num_heads) * m->view.config.head_dim;"
CALL_ARGUMENT = "/*q_width=*/m->q_width"
EXPECTED_CALLS = 3  # chunk-batched plus the fused and legacy per-token overloads


def evaluate(text: str) -> list[str]:
    errors: list[str] = []
    if text.count(DERIVATION) != 1:
        errors.append("q_width is not derived exactly once from num_attention_heads * head_dim")
    count = text.count(CALL_ARGUMENT)
    if count != EXPECTED_CALLS:
        errors.append(f"explicit q_width call arguments: expected {EXPECTED_CALLS}, found {count}")
    return errors


def main() -> int:
    text = ADAPTER.read_text(encoding="utf-8")

    missing_call = text.replace(CALL_ARGUMENT, "/*q_width=*/0", 1)
    wrong_derivation = text.replace(
        DERIVATION,
        "m->q_width = m->hidden_size;",
        1,
    )
    if not evaluate(missing_call):
        print("FAIL: missing-call mutant was accepted")
        return 1
    if not evaluate(wrong_derivation):
        print("FAIL: hidden_size-derivation mutant was accepted")
        return 1

    errors = evaluate(text)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("q_width_threading_check: PASS (2 must-reject mutants; real source accepted)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
