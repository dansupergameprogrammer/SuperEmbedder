# K1 Run 1 — output packet

Produced 2026-08-30 by `launch_run1.py` (TE-39, `Claude/Brunel/te39-k1-run1-launch-2026-08-30.md`
in the records repository). `TE39_RUN1_COMPLETE.json` reports `status: COMPLETE`, `r3_holds: true`,
18,377.3 s.

## What is committed here

- `TE39_RUN1_COMPLETE.json` — the run's completion record.
- `run1-full.json` / `run1-full.txt` — the packet and its human-readable table.
- `r3/r3_replication_report.json` and the three `r3-batch*` summaries — the R3 replication arm.
- `launch_stdout.log` / `launch_stderr.log` — the launcher's own output.

## What is NOT committed, and where it is

`run_files/` and `r3/run_files/` hold the per-query TREC ranking files — 98 MB and 11 MB
respectively. They are excluded by `.gitignore` under D-SLM5831 rather than deleted, and they remain
in this directory on the machine that produced them.

They are the input a rescore needs. `eval/k1/tools/rescore_packet.py` recomputes a persisted
packet's verdict under current code; without the run files a rescore cannot be performed and the
only route to the rankings is re-executing the capture, which cost 18,377.3 s of GPU time.

## The verdict this packet carries

Read it with the instrument, not from the file. The packet predates the TE-49 amendment, so it
carries no `bm25_analyzer` and no `query_convention` field, and `rescore_packet.py` **refuses** it
by construction (D-SLM5812, TE-52 H-1): grading pre-amendment rankings under the amended rules
returns a pass where the amended re-run returns a fail. The refusal is the correct answer, not an
obstacle to work around.
