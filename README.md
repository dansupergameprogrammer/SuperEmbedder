# SuperEmbedder

A deterministic text encoder: the same text produces bit-identical embedding
vectors on every certified platform. It is the front half of a cross-device
vector-search guarantee — [SuperFAISS](https://github.com/dansupergameprogrammer/superfaiss)
is bit-identical from the bank onward; SuperEmbedder makes the path bit-identical
from the raw text in.

**Status: project opened 2026-08-22. No code yet.** The plan of record is being
authored; this README states the thesis and the relationships so the repository
exists under its own name from the first commit.

## Relationship to the sibling projects

| Project | Role |
|---|---|
| [SuperSLM](https://github.com/dansupergameprogrammer/SuperSLM) | The integer-only transformer forward SuperEmbedder runs on. SuperEmbedder is a client of it, never a fork of it. |
| [SuperFAISS](https://github.com/dansupergameprogrammer/superfaiss) | The consumer of the banks SuperEmbedder produces and the query vectors it emits (`.wvbank` sidecar format). |

The three are developed as separate, linked repositories.
