# Determinism

This page states what SuperEmbedder guarantees about the bytes it emits, what the guarantee rests on, and
what it does not cover. Every measured number on it names the cell it was measured in: the build, the CPU
tier or device, the artifact and the corpus.

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
list. 1.0's list holds two cells, `msvc19.33-auto@avx2` and `clangcl18.1.8-auto@avx2`, certified on an AMD
Ryzen 9 5950X. AVX-512 cells, forced-SSE2 builds, MSVC 19.44 and GCC 13.3 builds, and NVIDIA GPUs at 1.18.1 are
planned for a later update; adding them keeps the epoch, because the epoch digests only the engine pin and the
proof corpus. `semb --version` prints the verdict for the build on the host you run it on:

```text
semb 1.0.0 (engine pin v1.18.1 @ c3c14b16690a0c0c54de781f6f30380d88e62bd1, engine_path_sha=9a1a8a28e9d540a9520669b913497ad687dce36390671dfbf75b2cb23c4c29e6)
build: os=Windows arch=AMD64 compiler=MSVC/19.33.31631.0 frontend=MSVC configuration=Release buildSystem=cmake
descriptor: os=windows isa=x86-64 toolchain="MSVC 193331631.0" stdlib="MSVC STL 202205L" configuration=Release buildSystem=cmake dispatch=auto compileFlags=205f4e0199088defb1cf1580a8916464db86477664998b078136fc366104c29b engineFlags=751427436f68e8ef11d5d2286f6ed1aaa27e6100891ff671013af148e6f09ecf engineToolchain="MSVC 193331631.0" engineStdlib="MSVC STL 202205L"
tier: avx2
cell: msvc19.33-auto@avx2 epoch=77cff77602bd9304b6bd316a2ff84ea1fe5be1b34184e0f51bebe1c6f0c8d7ef
certification: line=1 identity_sha256=77cff77602bd9304b6bd316a2ff84ea1fe5be1b34184e0f51bebe1c6f0c8d7ef certified_builds_sha256=2b2c499757ad155b6ca63cc4bfc0cea872fd8181551aa61aff7aa5814b60434b
engine: build_record=sslm-build-record-v1:41759ef0d67a0fca2dba24384900219bcf688b9a28d0da48103c13c96b58aa51 expected=sslm-build-record-v1:41759ef0d67a0fca2dba24384900219bcf688b9a28d0da48103c13c96b58aa51 forced_tier=auto required_isa=none check=SEMB_OK
```

A line prints `uncertified` when the build is not a certified cell on this host. That build still runs; it
computes the uncertified epoch, so its fingerprint differs from every certified build's, and a bank baked
by one is refused by the other by name (`SEMB_FINGERPRINT_MISMATCH`).

To check a build end to end, run `semb verify` against the reference bank in `docs/certification/reference-bank/`
(see the README's *Checking your build*).

## What changes the fingerprint, and what does not

**A change to the model, tokenizer, composition literals, executed witness results or certification epoch
changes the fingerprint.** A code change outside what the witnesses execute can change output without
moving the fingerprint. The certified set's proofs and `semb verify` against the reference bank check for
such changes on the certification corpus; the fingerprint alone does not catch them.
An uncommitted edit is never itself a new certification line; adopting one is the transition described
under *Epochs and re-baking*.

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

**int8 banks.** The guarantee is stated over emitted vectors. 1.0 has not compared the int8 bank bytes
SuperFAISS bakes from one bank file on two machines, so it makes no claim that re-baking an int8 bank on
another machine gives the same bytes. Bake the int8 bank once and ship those bytes; SuperFAISS's identical-hits
guarantee holds given identical bank bytes.

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
certified**, with every exception unmasked, in `msvc19.33-auto@avx2` (the MSVC 19.33.31631 Release auto build at AVX2, on an AMD Ryzen 9 5950X).

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
query prefix; a document pays for its own text. Measured on `msvc19.33-auto@avx2` (the MSVC 19.33.31631
Release auto build at AVX2), on an AMD Ryzen 9 5950X, CPU device, warm file cache:

| Tokens | Encode time | Tokens/s | Per token |
|---:|---:|---:|---:|
| 256 | 2,681 ms | 95.48 | 10.47 ms |
| 1,024 | 12,925 ms | 79.23 | 12.62 ms |
| 4,096 | 95,688 ms | 42.81 | 23.36 ms |

A document at the full 32,768-token context takes far longer than these; submitting one is legal and is not
fast.

**Time to ready runs from process start through the first query result**, including process startup,
encoder open, bank open and the first encoded query. Measured on `msvc19.33-auto@avx2`, on an AMD Ryzen 9
5950X, CPU device: 9,204 ms with a warm file cache (median of 3 runs). A cold-cache reading was not taken on
this build. This reading does not isolate encoder-open cost. Keep an encoder open to reuse it across encodes.

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
   same digest. On the same card, the GPU test suite passed except for one known test issue, since fixed in
   the tests (a timing-record drift in the C64 a/a2 legs, not a vector difference), and a 32,767-token
   long-context correctness capture passed 2 of 2.
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
