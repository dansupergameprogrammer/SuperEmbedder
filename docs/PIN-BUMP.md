# Pin bump procedure (maintainers)


Whenever `superslm.lock`'s `tag=` is bumped to a new pinned SuperSLM
release, two constructions must be re-run before the bump lands — both
need a fresh engine clone and a fresh engine build, which is exactly what
makes them unsuitable as per-push CI legs:

- **`tools/engine_side_wa_perturbation.py`** (C36(a) and C38) — builds two independent unperturbed baselines, a
  mutant with one non-inline engine arithmetic site perturbed, and a fourth
  scratch engine whose installed `ReadCarriedScale` header carries C38's
  compile-time branch. It asserts the baselines agree, the non-inline mutant
  moves `witness_sha`, the injected branch is inert by default, a library-only
  definition moves `witness_sha`, and a witness-only definition is inert. The
  released SuperSLM tag is never edited; both mutations live only in throwaway
  clones under the requested scratch root. Run:
  `python tools/engine_side_wa_perturbation.py --scratch-root <scratch dir>`.
  `tests/witness_structural_matrix.py` checks the durable C36(a)/C38 script
  contract and commissions C38's verdict logic via `--selftest-only`; it does
  not repeat the clone/build recipe under every `ctest` run.
- **C35's two-installation construction** (`tests/c35_two_installation_harness.py`) — two independent
  SuperEmbedder installations, each built against its own `tools/pin-superslm`
  engine prefix; the 239-document corpus is baked on one and queried from the
  other. Its 1.0 legs: an identical rebuild and an MSVC-against-clang-cl pair
  must accept; an edited epilogue, an edited non-inline engine `.cpp`, a
  one-byte certification-identity edit and a bank baked by the provisional
  build must each be refused with `SEMB_FINGERPRINT_MISMATCH`. It runs in
  phases from a Visual Studio developer shell, never in CI; the phase order is
  in the script's docstring.

