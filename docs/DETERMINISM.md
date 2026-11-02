# Determinism

This page states what SuperEmbedder guarantees about the bytes it emits, what the guarantee rests on, and
what it does not cover. Every measured number on it names the cell it was measured in: the build, the CPU
tier or device, the artifact and the corpus.

<!-- Placeholders in {{DOUBLE_BRACES}} are filled before the release; each carries a comment naming the step
     that produces it. Every comment of this form is removed when its placeholder is filled. -->

## The guarantee

**The same text, encoded by two installations whose `encoder_fingerprint` is equal and whose builds are
members of the certified set that fingerprint's `certification_epoch` names, produces byte-identical
vectors.**

### What the fingerprint covers

`encoder_fingerprint` is a SHA-256 over five fields. Each field enters as its 8-byte little-endian length
(always 32) followed by its 32 bytes:

| # | Field | What it is |
|---|---|---|
| 1 | `model_sha` | SHA-256 of the converted model file's bytes |
| 2 | `tokenizer_sha` | SHA-256 of the tokenizer file's bytes |
| 3 | `template_sha256` | SHA-256 over the three literals composition applies — the document frame (empty), the query prefix and the end-token literal — each as its 8-byte little-endian length followed by its bytes |
| 4 | `witness_sha` | SHA-256 over the three witness digests the encoder computes when it opens: W-A runs pooling over fixed synthetic integer arrays, W-B runs the document forward over fixed texts, and W-Q runs the query composition over fixed queries |
| 5 | `certification_epoch` | SHA-256 of `docs/certification-identity.json` as the build compiled it in, on a build that is a certified cell; on any other build, SHA-256 of `"SEMB-UNCERTIFIED\0"` followed by the same file's bytes |

The device an encoder runs on is not an input. See [The GPU](#the-gpu).

**No field of the fingerprint is computed from a description of an input** — not a version, an id, a commit,
a source list or a build system's property. Fields 1–4 digest bytes or executed results; field 5 digests a
document that names the engine pin and the proof corpus by their contents.

### Where the certified set is published, and how to check a build

The certified set is `docs/certified-builds.json` in this repository, and the README's certified-platforms
table is generated from it. Its format is in [FORMAT.md](FORMAT.md#3-certified-buildsjson).

An epoch names a **certification line**. A later release can add cells to a line without moving its epoch,
so a list published later contains every earlier one: check membership against the line's latest published
list. `semb --version` prints the verdict for the build on the host you run it on:

```text
{{SEMB_VERSION_SAMPLE_OUTPUT}}
```
<!-- filled by: REL-4 step 7 — `semb --version` from the released auto build on the work machine -->

A line prints `uncertified` when the build is not a certified cell on this host. That build still runs; it
computes the uncertified epoch, so its fingerprint differs from every certified build's, and a bank baked
by one is refused by the other by name (`SEMB_FINGERPRINT_MISMATCH`).

To check a build end to end, run `semb verify` against the reference bank in `docs/certification/reference-bank/`
(see the README's *Checking your build*).
<!-- REL-4: verify against the committed docs/certified-builds.json and docs/certification/reference-bank/ before tagging -->

## What changes the fingerprint, and what does not

**A change to the model, tokenizer, composition literals, executed witness results or certification epoch
changes the fingerprint.** A code change outside what the witnesses execute can change output without
moving the fingerprint. The certified set's proofs and `semb verify` against the reference bank check for
such changes on the certification corpus; the fingerprint alone does not catch them.
An uncommitted edit is never itself a new certification line; adopting one is the transition described
under *Epochs and re-baking*.
<!-- REL-4: verify against the committed docs/certified-builds.json and docs/certification/reference-bank/ before tagging -->

**With the certification identity and the other four fields unchanged, and both builds certified cells, a
different compiler, optimisation level or warning level does *not* change it, which is the point of the
guarantee rather than a caveat on it.** A compiler joins a line by being added to the certified set with its
pairwise proofs; that keeps the epoch. A build that has not been added computes the uncertified epoch.

**The guarantee is stated over an enumerated certified set, and a build outside that set is a different
epoch.** The set is published (above). The encoder's witness is commissioning evidence that the arithmetic
is exercised; it is not the guarantee's scope. Configure refuses a list whose pairwise proofs are incomplete
(`SEMB_CERTIFIED_BUILDS_UNPROVEN`), and each encoder open decides its own build's membership.

Membership is by **exact toolchain build**: a compiler of the same major version but a different build
number is not the certified compiler.

## Epochs and re-baking

A bank's `certification_epoch` names the certification line it was baked under.

- **Adding cells** to a line in a later release keeps the epoch. No existing bank is refused.
- **Moving the engine pin, withdrawing a cell, or changing the proof corpus** starts a new line. The epoch
  moves, the fingerprint moves, and banks baked on the old line are refused by name by builds on the new
  one. **Re-bake them.**

{{INT8_BANK_BYTES_WORDING}}
<!-- filled by: REL-4, the C15 comparison (int8 bank bytes SuperFAISS bakes from one bank, compared across
     two machines). Equal bytes: "The guarantee holds over identical bank bytes plus identical query bytes:
     an int8 bank SuperFAISS bakes from one bank file is byte-identical on every certified cell, so bake it
     once and ship it." Unequal: state that int8 banks must be re-baked per machine from the shipped
     .wvbank, and that the guarantee is stated over emitted vectors only. -->

## The floating-point environment

**The emitted vector's bytes do not depend on the process's floating-point environment** — not its rounding
mode, not its flush-to-zero state, not any other control-register field — **because the emitted `binary32` is
constructed in integer code rather than computed by IEEE operations.** This matters because it is the one
property a host application can break from outside the library and never be told. The construction is
specified in [POOLING.md](POOLING.md).

**SuperEmbedder does not read, set or restore any field of the calling thread's floating-point control
register** — not the rounding mode, not `FTZ`/`DAZ`, not the six exception-mask bits — **and a host's thread
state is returned untouched because the library never touches it.** A source-level check in the build
asserts it.

What is measured, and where: **no floating-point exception was raised on the corpora and operand sets
certified**, with every exception unmasked, in {{FP_EXCEPTION_CERTIFYING_CELL}}.
<!-- filled by: the REL-2 verify of the cleared-mask cell (C41) — name the build, tier and host it executed on -->

Two stronger statements are **not** made on this page, because no execution establishes them yet: that the
reproducible path performs no floating-point operation at all, and that a host running with exceptions
unmasked can never be stopped by the library. An instruction-level scan is what would establish them, and
when it does they will be stated per certified cell.

### The engine pin, as a consumer obligation

**SuperEmbedder 1.0 requires exactly the SuperSLM it pins, `1.18.1`.** Configure refuses any other version, and
every open refuses an engine build other than the one configure verified. The pin must never fall below
`1.3.0`, for the reason below.

Below 1.3.0 the engine's open path builds hash containers whose bucket count MSVC computes from
`max_load_factor()`, a `float`, so `reserve` performs a floating-point division. **With exceptions unmasked,
on an MSVC 19.3x-class toolchain, that division traps and ends the process inside the engine at handle open,
before any vector exists** (`0xC000008F`, observed at two sites). **On MSVC 19.44 the same construction does
not trap** — measured on one machine, same source, same build line. That is a reason to pin, not a reason
not to: the operation is still on the path, and a toolchain that happens not to raise on it is one toolchain
change away from the crash with nothing in the build to say so.

A build configured against a `1.2.x` engine is refused, not guarded.

### Build flags, as a consumer obligation

Every SuperEmbedder target compiles with `-ffp-contract=off` (GCC, Clang, AppleClang) or `/fp:precise`
(MSVC), and never with fast-math; the build fails if they are missing. **If you link SuperEmbedder
statically, compile your own translation units that include its headers with the same flags.** This is the
obligation SuperFAISS's own DETERMINISM page places on its consumers (its §3, obligation 1), and a static
consumer inherits it for the same reason SuperEmbedder does: a contracted or reassociated operation in a
shared inline function changes bytes.

Any flag beyond the certified cell's recorded set makes the build uncertified. The build refuses to configure
while `CL`, `_CL_` or `CCC_OVERRIDE_OPTIONS` is set, because each of those injects options the build cannot
see.

## The threat model

**The threat model is accidental and stale mismatch, not a forged bundle.** A coordinated edit across a
manifest, its bank and their digests produces a self-consistent bundle that SuperEmbedder does not detect,
because nothing outside the bundle anchors it. The same holds for a forged certification record or a
compiler binary that is not the compiler it reports; [FORMAT.md](FORMAT.md#6-what-the-checks-do-not-catch)
lists each residual.

## Errors

The `semb_status` enum is the only error channel. When a fingerprint does not match, the call returns
`SEMB_FINGERPRINT_MISMATCH`; it does not report which of the five fields differed. Compare the two manifests'
five fields to find out.

## Cost

**Encode cost grows faster than linearly in token count.** A query pays for its own text plus the compiled-in
query prefix; a document pays for its own text. Measured on {{SPAN_CURVE_CELL}}:
<!-- filled by: U2-4 (the readiness tool, C20) — build, tier, host -->

| Tokens | Encode time |
|---:|---:|
| 256 | {{SPAN_MS_256}} |
| 1,024 | {{SPAN_MS_1024}} |
| 4,096 | {{SPAN_MS_4096}} |
<!-- filled by: U2-4 (C20 span curve) -->

A document at the full 32,768-token context takes far longer than these; submitting one is legal and is not
fast.

**Time to ready runs from process start through the first query result**, including process startup,
encoder open, bank open and the first encoded query. Measured on a pre-release MSVC 19.33 build at AVX2,
on an AMD Ryzen 9 3950X, CPU device: 31,971 ms from a cold file cache, 31,994 ms warm. These readings do not
isolate encoder-open cost. Keep an encoder open to reuse it across encodes.

## What is not guaranteed

- **Identity across artifacts.** A different model or tokenizer file is a different fingerprint.
- **Agreement with a floating-point reference.** The vectors are the integer engine's. Retrieval quality
  relative to a floating-point run of the same model is measured, not promised — see the README's
  *Retrieval quality*.
- **Coverage beyond the witness corpus.** The witness is short authored text in one register; it shows the
  arithmetic is exercised, not that every input is.
- **Tiers or builds outside the certified set.**
- **Quality beyond what the published retrieval measurement covers.**
- **Byte identity of the query entry point's own composition code across two builds sharing a fingerprint
  is covered by a check that is built and runs at every encoder open, but has not been independently
  commissioned.** The witness's third digest runs the query entry point on fixed queries; the independent
  must-accept and must-reject pair that would commission it is not done in 1.0.

## The GPU

On Windows, a build configured with `SEMB_BUILD_GPU=ON` can encode on a Direct3D 12 GPU. **GPU and CPU
vectors are byte-identical, and the fingerprint does not name the device**, so a bank baked on one is queried
on the other.

The guarantee on a GPU rests on three things:

1. **The embedding path is integer arithmetic**, which leaves a driver's shader compiler no legal freedom to
   change a result.
2. **GPU identity is executed, on one vendor so far at 1.18.1.** At this pin the GPU encode runs the engine's
   multi-row prompt kernels. On an AMD Radeon RX 7900 XT (driver 32.0.21030.2001), a full bake of the
   239-document certification corpus passed the open-time check, and all 239 rows matched the CPU's, with the
   same digest. The full GPU suite and a long correctness run on that card are still in progress.
   **The multi-row GPU path has not yet been run on NVIDIA at 1.18.1.** Earlier NVIDIA evidence was on the
   engine's older one-row GPU path and does not carry over: an NVIDIA RTX 2080 SUPER and an AMD RX 7900 XTX
   produced identical bytes at engine 1.7.1 or earlier, and an NVIDIA RTX 5060 was checked at engine 1.17,
   after the engine fixed an int64 carry bug in NVIDIA's Blackwell driver.
3. **Every GPU open re-proves byte equality with the CPU** on 22 witness sequences, on the hardware and
   driver it is running on, and refuses (`SEMB_DEVICE_DIVERGED`) if any differs.

**What that does not cover:** on hardware no one has verified, the open-time check proves positions only up
to the longest witness sequence, 97 positions. Longer positions on that hardware
rest on parts 1 and 2 alone, not on an execution there. At 1.18.1 that includes every NVIDIA GPU: part 2 has
not yet been executed on NVIDIA at this pin, so on NVIDIA longer positions rest on part 1 and the open-time
check alone.

GPUs that have been verified are listed in the README's certified-platforms table under *Verified GPUs*.
A GPU is never a certified cell: the verdict is decided on the build's CPU cell.
