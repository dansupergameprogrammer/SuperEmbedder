# Archive: SuperSLM branch `claude/t1777-retrieval-agreement`

The encoder-retrieval evaluation instrument and its probes, as they stood on the SuperSLM branch
`claude/t1777-retrieval-agreement` (tip `e6668a3`, base `main`@`c6cfa03`). Archived here 2026-08-22
because the instrument is SuperEmbedder's now and the branch existed only as a local-only branch of a
public repository it was never scrubbed for.

- `files/` — every file the branch added or changed relative to its base, at the tip (paths as in
  SuperSLM: `tools/...`). `diffstat.txt` lists them; `commits.txt` lists the four commits.
- `t1777-retrieval-agreement.bundle` — the exact history (`git bundle`, `c6cfa03..e6668a3`). To
  recover it in a SuperSLM checkout: `git bundle verify <file>` then `git fetch <file> claude/t1777-retrieval-agreement:archive/t1777`.

These tools were built against the SuperSLM forward at or before `d45927f` (Option G overlay). They
are the capture path behind the standing recall figures (T-1777 build log, 2026-08-06) and the oracle
the plan's C2/C21 fixtures are minted from. They are not a SuperEmbedder deliverable; the plan ports
them (plan §3.1) and the port is graded against this archive.
