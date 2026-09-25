# Security Policy

## Reporting a vulnerability

Please report security issues privately through GitHub's security advisory
process rather than a public issue:

<https://github.com/dansupergameprogrammer/SuperEmbedder/security/advisories/new>

This opens a private draft advisory visible only to the maintainer until a
fix is ready. Please do not open a public issue for a suspected
vulnerability.

## What to include

Enough to reproduce: the affected version or commit, the platform and
toolchain, and the smallest input or call sequence that demonstrates the
problem. For a memory-safety or validation issue in a file SuperEmbedder
reads — a bank's `.wvbank.json`, `.wvbank.bin` or `.semb.json`, a corpus, or
the model and tokenizer artifacts, which pass through the SuperSLM loader —
a minimal file that triggers it is the most useful attachment.

## Scope

This covers the SuperEmbedder library, its C header, and the `semb` command
line tool in this repository. Issues in the SuperSLM engine's loader or
forward belong to [SuperSLM](https://github.com/dansupergameprogrammer/SuperSLM/security/advisories/new),
and issues in bank search belong to [SuperFAISS](https://github.com/dansupergameprogrammer/superfaiss);
if you are unsure which project owns a problem, report it here.

A bank bundle whose manifest, rows and digests were edited together so that
they agree with each other is **not** a vulnerability: SuperEmbedder detects
accidental and stale mismatch, not forgery, and says so in
[docs/DETERMINISM.md](docs/DETERMINISM.md#the-threat-model). A crash,
out-of-bounds read, or wrong vector returned with `SEMB_OK` while reading such
a bundle is.

## Response

This is a single-maintainer project. There is no fixed SLA, but reports are
read and acknowledged as soon as practical, and a fix or mitigation is
prioritized once a report is confirmed.
