# TE-234 query localization probes

These diagnostics compare SuperEmbedder's exact tokenizer and PS-N endpoint
against the Qwen3-Embedding-0.6B Hugging Face reference. They do not modify the
product library.

## Files

- `tokenize_sslm.cpp` checks the full product token sequence, including the
  explicitly appended `151643`, over length-prefixed UTF-8 inputs.
- `product_endpoint.cpp` exposes one input's product pre-final-norm row and
  post-final-norm float32 endpoint.
- `product_batch.cpp` emits full-corpus product endpoints from one opened
  model.
- `run_product_batch.py` drives one query or document corpus arm.
- `analyze.py` executes the model-card float pipeline, validates composition
  and all token sequences, compares layer specimens, and computes retrieval.
- `result.json` is the executed 2026-09-11 result on the paths and revisions
  recorded inside the corresponding Linnaeus fact sheet.

The layer specimens use SuperSLM's existing self-checking
`tools/sslm_layer_trace.cpp`, compiled into this worktree's ignored
`build/te234` directory. Its final pre-norm row must be bit-identical to
`product_endpoint.cpp`'s chunk-batched product seam or `analyze.py` refuses
the run.

## Build

Configure the repository's `build/msvc` tree as specified by TE-234, then
build `superembedder`, `superembedder_testseam`, and `semb`. Compile the
three C++ probes with MSVC 19.33, `/std:c++20 /O2 /MD /fp:precise`, the
repository and installed SuperSLM include directories, and link
`build/msvc/superembedder.lib` plus the installed `superslm.lib` where the
probe calls product entries.

Compile SuperSLM's `sslm_layer_trace.cpp` from the source tree associated with
the candidate artifact, using its checked-in `tools/build_layer_trace.bat`
source list, but place all objects and the executable under this worktree's
`build/te234`.

## Run

Run `run_product_batch.py` separately for `--kind query` and
`--kind document`; each command stays below TE-234's seven-minute ceiling.
Pass both generated binaries to `analyze.py`, together with the product query
source, corpus, Hugging Face snapshot, candidate artifacts, and the three
probe executables. `analyze.py` writes the complete JSON result only after
all equality and endpoint checks hold.
