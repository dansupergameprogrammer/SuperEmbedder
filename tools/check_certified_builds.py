"""C42's release checker for a certification package (plan sec 4.1a, sec 8 C42; te267 U2-3 items 4, 6, 7, 10,
11, 12, 15; D-SLM7206, D-SLM7217, D-SLM7273, D-SLM7279, D-SLM7309).

    python tools/check_certified_builds.py --root <package root> [--extends <prior list> --extends-identity <prior
        identity file>] [--structural]

reads `<root>/docs/certified-builds.json` (the list), `<root>/docs/certification-identity.json` (the identity
file), `<root>/superslm.lock`, the proof corpus the identity file names, and each cell's runs. Run against the
repository root it checks the committed package.

THE PACKAGE
  The list's `builds[]` are cells, each `<member>@<tier>` with the descriptor fields (os, isa, toolchain, stdlib,
  configuration, buildSystem, dispatch, compileFlags, engineFlags), `cpuTier`, `artifact`, `host` and `evidence`.
  A cell's provisional run is `<evidence>/<cell id>/`, its final run `<evidence>/<cell id>/final/`, and a GPU run
  `<evidence>/gpu/<runId>/`. A run directory holds:
    row-digests.tsv          `<corpus label>\\t<sha256>` per row, LF-terminated
    token-id-digest.txt      the manifest's token_id_digest, one line
    bake-manifest.semb.json  the member's own bake manifest, byte for byte
    compile-flags.json       the product's compile-flag record (tools/compile_flags.py --out)
    engine-flags.json        the engine's record (provenance.json's engine_build.flags)
    run.json                 cellId, runId, date, pass ("provisional" or "final"), host (the CPU probe's brand
                             string), manifestSha256, buildDescriptor, machineTier, certificationEpoch,
                             certifiedBuildsSha256, certifiedCell (copies of the manifest's), dispatchedTier (the
                             manifest's machine_tier), hostBestTier (the package script's own CPUID reading),
                             enginePin {tag, commit, engine_tree_sha}, productCommit, derivationInputsSha256,
                             rowDigest, tokenIdDigest; a GPU run also copies device and the four gpu_* labels
  and, for the msvc19.33-auto cells, query-digests.tsv and rt4-digests.txt.
  A pair carries `a`, `b`, `runIds` (its two cells' provisional run ids), `rowDigest` and `tokenIdDigest`.
  A list in the Slice 7 interim form (members carrying no descriptor, `evidence` and one `runId` on the pair,
  `enginePin` in the list) is read for clauses (a)-(c); every binding clause refuses it by name.

THE CLAUSES, each refused on its own output line `REFUSED C42(<clause>) ...`
  (a)   Membership: at least two cells, unique ids, exactly one pairwiseProofs entry per unordered pair, and the
        two cells' recomputed row digests equal.
  (b)   Evidence: every digest the list records is recomputed from the cells' run files, never taken from the
        JSON; evidence paths stay inside the root; an unreadable file is a refusal, not a crash.
  (b')  Binding (item 12): each cell run's manifest is the file run.json names; the cell's descriptor and
        cpuTier equal the manifest's build_descriptor and machine_tier, its artifact hashes the manifest's
        model_sha and tokenizer_sha, its host the run's; every run.json copy equals the manifest; the manifest's
        count and corpus_digest equal the identity's proofCorpus; row-digests.tsv has exactly `rows` lines whose
        ids are the corpus labels in order; token-id-digest.txt equals the manifest's token_id_digest and
        proofCorpus.tokenIdDigest; each pair's runIds are its cells' provisional run ids; no runId repeats; and
        both flag records recompute to the descriptor's digests and carry no residual location.
  (c)   Engine pin: every run's enginePin equals the identity file's, and the identity file's equals the lock's.
  (c')  Freshness (item 4): every run's derivationInputsSha256 equals the digest of the tree being certified.
  (e)   Final equality replay (item 6), on a release list: every cell has a final run equal to its own
        provisional run (row and token digests, and for msvc19.33-auto the query and RT-4 digests), compiled
        with the committed list, resolved to its own cell, at the committed identity's epoch, from this tree,
        with one witness_sha across all cells.
  (f)   Every cell executed at its tier (item 7), on a release list: a provisional and a final run whose
        dispatchedTier is the cell's cpuTier; an auto cell's equals hostBestTier, a forced cell's is the forced
        tier and does not exceed hostBestTier; the run's descriptor is the cell's.
  (g)   Extension (item 10), only with --extends: under an identity byte-identical to the prior release's, every
        prior cell and proof is kept unchanged and every added cell has a pair with every cell whose rowDigest
        is recomputed from the run files.
  (h)   Identity derivation (item 10): the identity file equals, byte for byte, what
        tools/write_certification_identity.py writes from this tree at the file's own `line`.
  (i)   Verified GPUs (item 15), on a release list: every gpuVerifications entry's cell is listed, its runIds
        resolve to committed gpu/ runs, exactly one of them bakes the proof corpus, and that run's manifest is a
        GPU bake of the cell's build and tier whose rows and tokens equal the cell's provisional receipt.

  A list whose `release` names the interim ("...interim...") is graded by (a), (b), (b'), (c), (c') and (h);
  (e), (f) and (i) run over a release list (REL-4 step 4).

--structural (item 11) runs clauses (a) and (b) over the list and the evidence files they read and nothing
else, then prints one `READ <path>` line per file read, for configure's CMAKE_CONFIGURE_DEPENDS.

Output: the REFUSED lines, then `ACCEPTED ...` when nothing is refused. Exit 0 accepted, 1 refused; a package that
cannot be read at all is refused with a `REFUSED C42: ...` line and exit 1. C42 (d), the runtime equality of
certification_epoch, belongs to tests/te264_fingerprint_final_check.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compile_flags  # noqa: E402
import derivation_inputs  # noqa: E402
import write_certification_identity as identity_tool  # noqa: E402

HEX64 = re.compile(r"^[0-9a-f]{64}$")
PIN_FIELDS = ("tag", "commit", "engine_tree_sha")
DESCRIPTOR_FIELDS = ("os", "isa", "toolchain", "stdlib", "configuration", "buildSystem", "dispatch",
                     "compileFlags", "engineFlags")
RUN_COPIES = (("buildDescriptor", "build_descriptor"), ("machineTier", "machine_tier"),
              ("certificationEpoch", "certification_epoch"), ("certifiedBuildsSha256", "certified_builds_sha256"),
              ("certifiedCell", "certified_cell"))
TIER_ORDER = {"scalar": 0, "sse2": 1, "avx2": 2, "avx512": 3}
GPU_LABELS = ("gpu_vendor_id", "gpu_device_id", "gpu_adapter_name", "gpu_driver_version")
GPU_ENTRY_KEYS = {"gpu_vendor_id": "vendorId", "gpu_device_id": "deviceId", "gpu_adapter_name": "adapterName",
                  "gpu_driver_version": "driverVersion"}
CLAUSES = ("a", "b", "b'", "c", "c'", "e", "f", "g", "h", "i")
LIST_PATH = "docs/certified-builds.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_lock(path: Path) -> dict:
    fields = dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line)
    return {"tag": fields.get("tag"), "commit": fields.get("commit"), "engine_tree_sha": fields.get("tree")}


def pin_of(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    return {k: value.get(k) for k in PIN_FIELDS}


def artifact_hashes(artifact) -> tuple[str | None, str | None]:
    """The cell's model and tokenizer SHA-256: {"model": {"sha256"}, "tokenizer": {"sha256"}}, or a string
    carrying `sha256=<hex>` for the model and then the tokenizer."""
    if isinstance(artifact, dict):
        m, t = artifact.get("model"), artifact.get("tokenizer")
        return (m.get("sha256") if isinstance(m, dict) else None, t.get("sha256") if isinstance(t, dict) else None)
    if isinstance(artifact, str):
        found = re.findall(r"sha256=([0-9a-f]{64})", artifact)
        if len(found) == 2:
            return found[0], found[1]
    return None, None


class Run:
    """One run directory, its files recomputed; problems are clause (b)'s."""

    def __init__(self, root: Path, directory: Path, label: str, read: list[Path]) -> None:
        self.label = label
        self.directory = directory
        self.problems: list[str] = []
        self.files: dict[str, bytes] = {}
        self.row_digest = self.token_digest = None
        self.run: dict | None = None
        self.manifest: dict | None = None
        self.lines: list[tuple[str, str]] = []
        if root.resolve() != directory.resolve() and root.resolve() not in directory.resolve().parents:
            self.problems.append(f"{label}: evidence path {directory} leaves the package root")
            return
        try:
            for name in ("row-digests.tsv", "token-id-digest.txt", "run.json"):
                read.append(directory / name)
                self.files[name] = (directory / name).read_bytes()
            self.run = json.loads(self.files["run.json"].decode("utf-8"))
        except (OSError, ValueError) as exc:
            self.problems.append(f"{label}: evidence at {directory} is unreadable: {exc}")
            return
        tsv = self.files["row-digests.tsv"]
        text = tsv.decode("utf-8", errors="replace")
        raw = text.split("\n")
        if not tsv or raw[-1] != "" or any(len(l.split("\t")) != 2 or not HEX64.match(l.split("\t")[1])
                                           for l in raw[:-1]):
            self.problems.append(f"{label}: row-digests.tsv is not LF-terminated '<id>\\t<sha256>' lines")
        else:
            self.lines = [tuple(l.split("\t")) for l in raw[:-1]]
        self.row_digest = sha256(tsv)
        token = self.files["token-id-digest.txt"].decode("utf-8", errors="replace")
        self.token_digest = token.strip()
        if not HEX64.match(self.token_digest) or token != self.token_digest + "\n":
            self.problems.append(f"{label}: token-id-digest.txt is not one SHA-256 line")
        if not isinstance(self.run, dict):
            self.problems.append(f"{label}: run.json is not an object")
            self.run = None
            return
        if self.run.get("rowDigest") != self.row_digest:
            self.problems.append(f"{label}: run.json rowDigest {self.run.get('rowDigest')} != SHA-256 of "
                                 f"row-digests.tsv {self.row_digest}")
        if self.run.get("tokenIdDigest") != self.token_digest:
            self.problems.append(f"{label}: run.json tokenIdDigest {self.run.get('tokenIdDigest')} != "
                                 f"token-id-digest.txt {self.token_digest}")

    def optional(self, name: str) -> bytes | None:
        if name not in self.files:
            try:
                self.files[name] = (self.directory / name).read_bytes()
            except OSError:
                return None
        return self.files[name]

    def load_manifest(self) -> str | None:
        """Reads bake-manifest.semb.json; returns a problem string or None."""
        data = self.optional("bake-manifest.semb.json")
        if data is None:
            return "no bake-manifest.semb.json"
        try:
            self.manifest = json.loads(data.decode("utf-8"))
        except ValueError as exc:
            return f"bake-manifest.semb.json is not JSON: {exc}"
        if not isinstance(self.manifest, dict):
            self.manifest = None
            return "bake-manifest.semb.json is not an object"
        return None

    @property
    def run_id(self):
        return self.run.get("runId") if self.run else None


def flag_record_problems(label: str, data: bytes | None, name: str, expected: str | None) -> list[str]:
    """A flag record's digest recomputed from its record, and its residual locations (item 13 step 6)."""
    if data is None:
        return [f"{label}: no {name}"]
    try:
        doc = json.loads(data.decode("utf-8"))
        record, family = doc["record"], doc.get("family", "other")
    except (ValueError, KeyError, TypeError) as exc:
        return [f"{label}: {name} is not a flag record: {exc}"]
    out = []
    got = compile_flags.digest(record)
    if got != expected:
        out.append(f"{label}: {name} recomputes to {got}, the descriptor carries {expected}")
    windows = family in ("msvc", "clangcl")
    residual = set(doc.get("residual") or [])
    for unit in record.values() if isinstance(record, dict) else []:
        for arg in list(unit.get("includes", [])) + list(unit.get("flags", [])):
            if compile_flags.is_residual(arg, windows):
                residual.add(arg)
    for arg in sorted(residual):
        out.append(f"{label} location {arg}")
    return out


class Checker:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.refused: dict[str, list[str]] = {c: [] for c in CLAUSES}
        self.read: list[Path] = []
        self.notes: list[str] = []

    def refuse(self, clause: str, text: str) -> None:
        self.refused[clause].append(text)

    # -- the list and its runs ----------------------------------------------------------------------------------
    def load_list(self) -> None:
        path = self.root / LIST_PATH
        self.read.append(path)
        self.list_bytes = path.read_bytes()
        doc = json.loads(self.list_bytes.decode("utf-8"))
        builds = doc.get("builds") if isinstance(doc, dict) else None
        proofs = doc.get("pairwiseProofs") if isinstance(doc, dict) else None
        if not isinstance(builds, list) or not isinstance(proofs, list):
            raise ValueError("the document carries no builds/pairwiseProofs arrays")
        self.doc, self.builds, self.proofs = doc, builds, proofs
        self.cells = {b["id"]: b for b in builds if isinstance(b, dict) and isinstance(b.get("id"), str)}
        self.release = str(doc.get("release", ""))
        self.interim = "interim" in self.release

    def evidence_of(self, cell_id: str, proof: dict | None = None) -> str | None:
        cell = self.cells.get(cell_id, {})
        if isinstance(cell.get("evidence"), str):
            return cell["evidence"]
        if isinstance(proof, dict) and isinstance(proof.get("evidence"), str):
            return proof["evidence"]  # the Slice 7 interim form carries evidence on the pair
        for p in self.proofs:
            if isinstance(p, dict) and cell_id in (p.get("a"), p.get("b")) and isinstance(p.get("evidence"), str):
                return p["evidence"]
        return None

    def run_at(self, cell_id: str, final: bool = False) -> Run | None:
        key = (cell_id, final)
        if key not in self.runs:
            evidence = self.evidence_of(cell_id)
            if evidence is None:
                self.runs[key] = None
                return None
            directory = self.root / evidence / cell_id / ("final" if final else "")
            if final and not directory.is_dir():
                self.runs[key] = None
                return None
            run = Run(self.root, directory, cell_id + (" final" if final else ""), self.read)
            self.runs[key] = run
            self.refused["b"].extend(run.problems)
            if run.run is not None:
                named = run.run.get("cellId", run.run.get("buildId"))
                if named != cell_id:
                    self.refuse("b", f"{run.label}: run.json names cell {named!r}")
        return self.runs[key]

    # -- (a) and (b) --------------------------------------------------------------------------------------------
    def clause_a_b(self) -> None:
        self.runs: dict[tuple[str, bool], Run | None] = {}
        ids = [b.get("id") if isinstance(b, dict) else None for b in self.builds]
        if any(not isinstance(m, str) or not m for m in ids) or len(set(ids)) != len(ids):
            self.refuse("a", f"cell ids are not unique non-empty strings: {ids}")
        members = {m for m in ids if isinstance(m, str)}
        if len(members) < 2:
            self.refuse("a", f"{len(members)} cell(s); a certified set has at least two")
        seen: dict[frozenset, int] = {}
        for i, proof in enumerate(self.proofs):
            a, b = (proof.get("a"), proof.get("b")) if isinstance(proof, dict) else (None, None)
            if a not in members or b not in members or a == b:
                self.refuse("a", f"pairwiseProofs[{i}] names {a!r} and {b!r}, not two distinct cells")
                continue
            seen[frozenset((a, b))] = seen.get(frozenset((a, b)), 0) + 1
        for a, b in combinations(sorted(members), 2):
            count = seen.get(frozenset((a, b)), 0)
            if count != 1:
                self.refuse("a", f"pair ({a}, {b}) has {count} pairwiseProofs entries (exactly one required)")
        for cell_id in sorted(members):
            if self.evidence_of(cell_id) is None:
                self.refuse("b", f"{cell_id}: no evidence path")
        for i, proof in enumerate(self.proofs):
            if not isinstance(proof, dict):
                continue
            a, b = proof.get("a"), proof.get("b")
            if a not in members or b not in members:
                continue
            ra, rb = self.run_at(a), self.run_at(b)
            for member, run in ((a, ra), (b, rb)):
                if run is None:
                    continue
                if run.row_digest is not None and proof.get("rowDigest") != run.row_digest:
                    self.refuse("b", f"pairwiseProofs[{i}] ({a}, {b}) rowDigest {proof.get('rowDigest')} != "
                                     f"{member}'s recomputed {run.row_digest}")
                if run.token_digest is not None and proof.get("tokenIdDigest") != run.token_digest:
                    self.refuse("b", f"pairwiseProofs[{i}] ({a}, {b}) tokenIdDigest {proof.get('tokenIdDigest')} "
                                     f"!= {member}'s recomputed {run.token_digest}")
            if ra and rb and ra.row_digest and rb.row_digest and ra.row_digest != rb.row_digest:
                self.refuse("a", f"pair ({a}, {b}): the cells' row-digests.tsv differ "
                                 f"({ra.row_digest} vs {rb.row_digest})")

    # -- the identity -------------------------------------------------------------------------------------------
    def load_identity(self) -> None:
        self.identity = self.identity_bytes = None
        path = self.root / identity_tool.IDENTITY_PATH
        try:
            self.identity_bytes = path.read_bytes()
            self.identity = json.loads(self.identity_bytes.decode("ascii"))
        except (OSError, ValueError) as exc:
            self.refuse("h", f"{identity_tool.IDENTITY_PATH} is unreadable: {exc}")
            return
        line = self.identity.get("line") if isinstance(self.identity, dict) else None
        try:
            expected = identity_tool.identity_bytes(self.root, int(line))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.refuse("h", f"the identity cannot be regenerated from this tree: {exc}")
            return
        if expected != self.identity_bytes:
            self.refuse("h", f"{identity_tool.IDENTITY_PATH} (sha256 {sha256(self.identity_bytes)}) differs from "
                             f"what tools/write_certification_identity.py writes from this tree at line {line} "
                             f"(sha256 {sha256(expected)})")

    @property
    def proof_corpus(self) -> dict:
        pc = self.identity.get("proofCorpus") if isinstance(self.identity, dict) else None
        return pc if isinstance(pc, dict) else {}

    def corpus_labels(self) -> list[str] | None:
        if not hasattr(self, "_labels"):
            try:
                rows = identity_tool.corpus_rows((self.root / self.proof_corpus["path"]).read_bytes())
                self._labels = [r["label"] for r in rows]
            except (OSError, ValueError, KeyError, TypeError):
                self._labels = None
        return self._labels

    # -- (b') ---------------------------------------------------------------------------------------------------
    def bind_run(self, cell_id: str, run: Run, clause: str = "b'") -> None:
        cell = self.cells[cell_id]
        label = run.label
        problem = run.load_manifest()
        if problem:
            self.refuse(clause, f"{label}: {problem}")
            return
        m, r = run.manifest, run.run
        if r.get("manifestSha256") != sha256(run.files["bake-manifest.semb.json"]):
            self.refuse(clause, f"{label}: run.json manifestSha256 {r.get('manifestSha256')} is not the manifest's "
                                f"{sha256(run.files['bake-manifest.semb.json'])}")
        descriptor = m.get("build_descriptor") if isinstance(m.get("build_descriptor"), dict) else {}
        for field in DESCRIPTOR_FIELDS:
            if cell.get(field) is None or cell.get(field) != descriptor.get(field):
                self.refuse(clause, f"{label}: cell {field} {cell.get(field)!r} != manifest build_descriptor "
                                    f"{descriptor.get(field)!r}")
        if cell.get("cpuTier") != m.get("machine_tier"):
            self.refuse(clause, f"{label}: cell cpuTier {cell.get('cpuTier')!r} != manifest machine_tier "
                                f"{m.get('machine_tier')!r}")
        model, tokenizer = artifact_hashes(cell.get("artifact"))
        if model is None or model != m.get("model_sha") or tokenizer != m.get("tokenizer_sha"):
            self.refuse(clause, f"{label}: cell artifact hashes ({model}, {tokenizer}) != manifest model_sha/"
                                f"tokenizer_sha ({m.get('model_sha')}, {m.get('tokenizer_sha')})")
        if cell.get("host") != r.get("host"):
            self.refuse(clause, f"{label}: cell host {cell.get('host')!r} != run host {r.get('host')!r}")
        for run_key, manifest_key in RUN_COPIES:
            if r.get(run_key) != m.get(manifest_key):
                self.refuse(clause, f"{label}: run.json {run_key} {r.get(run_key)!r} != manifest {manifest_key} "
                                    f"{m.get(manifest_key)!r}")
        pc = self.proof_corpus
        if m.get("count") != pc.get("rows") or m.get("corpus_digest") != pc.get("corpusDigest"):
            self.refuse(clause, f"{label}: manifest count/corpus_digest ({m.get('count')}, {m.get('corpus_digest')}) "
                                f"!= proofCorpus ({pc.get('rows')}, {pc.get('corpusDigest')})")
        labels = self.corpus_labels()
        if labels is None:
            self.refuse(clause, f"{label}: the proof corpus's labels cannot be read")
        elif [i for i, _ in run.lines] != labels:
            self.refuse(clause, f"{label}: row-digests.tsv has {len(run.lines)} lines whose ids are not the proof "
                                f"corpus's {len(labels)} labels in order")
        if not (run.token_digest == m.get("token_id_digest") == pc.get("tokenIdDigest")):
            self.refuse(clause, f"{label}: token-id-digest.txt {run.token_digest} != manifest token_id_digest "
                                f"{m.get('token_id_digest')} != proofCorpus.tokenIdDigest {pc.get('tokenIdDigest')}")
        for name, key in (("compile-flags.json", "compileFlags"), ("engine-flags.json", "engineFlags")):
            for text in flag_record_problems(label, run.optional(name), name, descriptor.get(key)):
                self.refuse(clause, text)

    def clause_b_prime(self) -> None:
        if self.identity is None:
            self.refuse("b'", "no identity file to bind the proof corpus to")
        run_ids: dict[str, list[str]] = {}
        for cell_id in sorted(self.cells):
            for final in (False, True):
                run = self.run_at(cell_id, final)
                if run is None or run.run is None:
                    if not final:
                        self.refuse("b'", f"{cell_id}: no readable provisional run")
                    continue
                if self.identity is not None:
                    self.bind_run(cell_id, run)
                if run.run_id is None:
                    self.refuse("b'", f"{run.label}: run.json carries no runId")
                else:
                    run_ids.setdefault(run.run_id, []).append(run.label)
        for rid, where in sorted(run_ids.items()):
            if len(where) > 1:
                self.refuse("b'", f"runId {rid} repeats: {', '.join(where)}")
        self.cell_run_ids = set(run_ids)
        for i, proof in enumerate(self.proofs):
            if not isinstance(proof, dict) or proof.get("a") not in self.cells or proof.get("b") not in self.cells:
                continue
            ra, rb = self.run_at(proof["a"]), self.run_at(proof["b"])
            expected = [ra.run_id if ra else None, rb.run_id if rb else None]
            if proof.get("runIds") != expected:
                self.refuse("b'", f"pairwiseProofs[{i}] ({proof['a']}, {proof['b']}) runIds {proof.get('runIds')} "
                                  f"!= the cells' provisional runIds {expected}")

    # -- (c) and (c') -------------------------------------------------------------------------------------------
    def all_cell_runs(self):
        for (cell_id, final), run in sorted(self.runs.items()):
            if run is not None and run.run is not None:
                yield cell_id, final, run

    def clause_c(self) -> None:
        lock = read_lock(self.root / "superslm.lock")
        pin = pin_of(self.identity.get("enginePin")) if isinstance(self.identity, dict) else None
        source = "identity"
        if pin is None:
            # No identity file (clause (h) refuses that): the Slice 7 interim form's list-level pin stands in.
            pin, source = pin_of(self.doc.get("enginePin")), "document"
        if pin != lock:
            self.refuse("c", f"{source} enginePin {pin} != superslm.lock {lock}")
        for _, _, run in self.all_cell_runs():
            run_pin = pin_of(run.run.get("enginePin"))
            if run_pin != pin:
                self.refuse("c", f"{run.label}: run enginePin {run_pin} != {source} enginePin {pin}")

    def clause_c_prime(self) -> None:
        try:
            tree = derivation_inputs.digest(self.root)
        except OSError as exc:
            self.refuse("c'", f"the tree's derivation inputs cannot be read: {exc}")
            return
        self.tree_digest = tree
        for _, _, run in self.all_cell_runs():
            if run.run.get("derivationInputsSha256") != tree:
                self.refuse("c'", f"{run.label}: derivationInputsSha256 {run.run.get('derivationInputsSha256')} != "
                                  f"the tree being certified {tree}")

    # -- (e) ----------------------------------------------------------------------------------------------------
    def clause_e(self) -> None:
        list_sha = sha256(self.list_bytes)
        identity_sha = sha256(self.identity_bytes) if self.identity_bytes else None
        witnesses: dict[str, str] = {}
        finals: dict[str, Run] = {}
        for cell_id in sorted(self.cells):
            prov, final = self.run_at(cell_id), self.run_at(cell_id, True)
            why: list[str] = []
            if final is None or final.run is None:
                self.refuse("e", f"{cell_id}: no final run")
                continue
            finals[cell_id] = final
            r = final.run
            if prov is None or prov.run is None:
                why.append("no provisional run to compare with")
            else:
                diff = [f"{a[0]}" for a, b in zip(prov.lines, final.lines) if a != b]
                if len(prov.lines) != len(final.lines) or diff:
                    why.append(f"row-digests.tsv differs from the provisional run's on {len(diff)} row(s)"
                               f"{' (' + ', '.join(diff[:5]) + ')' if diff else ''}")
                if prov.files["token-id-digest.txt"] != final.files["token-id-digest.txt"]:
                    why.append("token-id-digest.txt differs from the provisional run's")
                if cell_id.startswith("msvc19.33-auto@"):
                    for name in ("query-digests.tsv", "rt4-digests.txt"):
                        a, b = prov.optional(name), final.optional(name)
                        if a is None or b is None or a != b:
                            why.append(f"{name} {'is missing' if a is None or b is None else 'differs'}")
            if r.get("pass") != "final":
                why.append(f"pass is {r.get('pass')!r}")
            if r.get("certifiedBuildsSha256") != list_sha:
                why.append(f"certifiedBuildsSha256 {r.get('certifiedBuildsSha256')} is not the committed list's "
                           f"{list_sha}")
            if r.get("certifiedCell") != cell_id:
                why.append(f"certifiedCell is {r.get('certifiedCell')!r}")
            if r.get("certificationEpoch") != identity_sha:
                why.append(f"certificationEpoch {r.get('certificationEpoch')} is not the identity's {identity_sha}")
            if r.get("derivationInputsSha256") != getattr(self, "tree_digest", None):
                why.append("derivationInputsSha256 is not the tree being tagged")
            if final.load_manifest() is None and isinstance(final.manifest, dict):
                witnesses[cell_id] = final.manifest.get("witness_sha")
            else:
                why.append("no readable bake manifest for witness_sha")
            if why:
                self.refuse("e", f"{cell_id}: " + "; ".join(why))
        if len(set(witnesses.values())) > 1:
            self.refuse("e", f"witness_sha differs across the final runs: {witnesses}")
        disagree = [f"({a}, {b})" for a, b in combinations(sorted(finals), 2)
                    if finals[a].row_digest != finals[b].row_digest]
        if disagree:
            self.refuse("e", f"final pairs that disagree: {', '.join(disagree)}")
        n = len(self.cells)
        provisional_ok = sum(1 for c in self.cells if self.run_at(c) is not None and self.run_at(c).run is not None)
        self.notes.append(f"C42(e): {provisional_ok} provisional receipts and {n * (n - 1) // 2} pairs; "
                          f"{len(finals)} final replays and {len(finals) * (len(finals) - 1) // 2 - len(disagree)} "
                          f"agreeing final pairs, computed from the final runs")

    # -- (f) ----------------------------------------------------------------------------------------------------
    def clause_f(self) -> None:
        for cell_id, cell in sorted(self.cells.items()):
            why = []
            for final in (False, True):
                run = self.run_at(cell_id, final)
                name = "final" if final else "provisional"
                if run is None or run.run is None:
                    why.append(f"no {name} run")
                    continue
                r = run.run
                dispatched, host = r.get("dispatchedTier"), r.get("hostBestTier")
                if dispatched != cell.get("cpuTier"):
                    why.append(f"{name} run dispatchedTier {dispatched!r} != cpuTier {cell.get('cpuTier')!r}")
                if cell.get("dispatch") == "auto":
                    if dispatched != host:
                        why.append(f"{name} run of an auto cell dispatched {dispatched!r} on a {host!r} host")
                elif dispatched != cell.get("dispatch") or TIER_ORDER.get(dispatched, 99) > TIER_ORDER.get(host, -1):
                    why.append(f"{name} run of a {cell.get('dispatch')!r}-forced cell dispatched {dispatched!r} on a "
                               f"{host!r} host")
                descriptor = r.get("buildDescriptor") if isinstance(r.get("buildDescriptor"), dict) else {}
                off = [f for f in DESCRIPTOR_FIELDS if descriptor.get(f) != cell.get(f)]
                if off:
                    why.append(f"{name} run's descriptor differs from the cell's in {off}")
            if why:
                self.refuse("f", f"{cell_id}: " + "; ".join(why))

    # -- (g) ----------------------------------------------------------------------------------------------------
    def clause_g(self, prior_list: Path, prior_identity: Path) -> None:
        try:
            prior = json.loads(prior_list.read_bytes().decode("utf-8"))
            prior_id = prior_identity.read_bytes()
        except (OSError, ValueError) as exc:
            self.refuse("g", f"the prior release cannot be read: {exc}")
            return
        if prior_id != self.identity_bytes:
            self.notes.append("C42(g): the identity differs from the prior release's -- a new line, not graded")
            return
        cells = {b.get("id"): b for b in prior.get("builds", []) if isinstance(b, dict)}
        for cell_id, entry in sorted(cells.items()):
            if cell_id not in self.cells:
                self.refuse("g", f"{cell_id}: a prior cell is removed")
            elif self.cells[cell_id] != entry:
                self.refuse("g", f"{cell_id}: a prior cell is rewritten")
        now = {frozenset((p.get("a"), p.get("b"))): p for p in self.proofs if isinstance(p, dict)}
        for p in prior.get("pairwiseProofs", []):
            key = frozenset((p.get("a"), p.get("b")))
            if now.get(key) != p:
                self.refuse("g", f"({p.get('a')}, {p.get('b')}): a prior proof is changed or removed")
        for added in sorted(set(self.cells) - set(cells)):
            ra = self.run_at(added)
            for other in sorted(set(self.cells) - {added}):
                p = now.get(frozenset((added, other)))
                rb = self.run_at(other)
                if p is None:
                    self.refuse("g", f"({added}, {other}): the added cell has no pair")
                elif not (ra and rb and ra.row_digest and p.get("rowDigest") == ra.row_digest == rb.row_digest):
                    self.refuse("g", f"({added}, {other}): rowDigest {p.get('rowDigest')} is not recomputed from "
                                     f"{ra.row_digest if ra else None} and {rb.row_digest if rb else None}")

    # -- (i) ----------------------------------------------------------------------------------------------------
    def clause_i(self) -> None:
        entries = self.doc.get("gpuVerifications", [])
        if not isinstance(entries, list):
            self.refuse("i", "gpuVerifications is not an array")
            return
        pc = self.proof_corpus
        seen: dict[str, str] = {}
        for n, entry in enumerate(entries):
            name = entry.get("adapterName", f"gpuVerifications[{n}]") if isinstance(entry, dict) else f"[{n}]"
            why = []
            if not isinstance(entry, dict):
                self.refuse("i", f"{name} is not an object")
                continue
            cell_id = entry.get("cell")
            cell = self.cells.get(cell_id)
            if cell is None:
                self.refuse("i", f"{name}: cell {cell_id!r} is not a builds[] entry")
                continue
            proof_runs = []
            for rid in entry.get("runIds") or []:
                if rid in seen:
                    why.append(f"runId {rid} is also cited by {seen[rid]}")
                seen[rid] = name
                if rid in getattr(self, "cell_run_ids", set()):
                    why.append(f"runId {rid} is a cell run's runId")
                directory = self.root / (cell.get("evidence") or "") / "gpu" / str(rid)
                if not directory.is_dir():
                    why.append(f"runId {rid} has no committed gpu/{rid}/")
                    continue
                run = Run(self.root, directory, f"gpu/{rid}", self.read)
                if run.problems or run.run is None:
                    why.extend(run.problems or [f"gpu/{rid}: run.json unreadable"])
                    continue
                if run.load_manifest():
                    why.append(f"gpu/{rid}: no readable bake manifest")
                    continue
                if run.manifest.get("count") == pc.get("rows") and \
                        run.manifest.get("corpus_digest") == pc.get("corpusDigest"):
                    proof_runs.append(run)
            if len(proof_runs) != 1:
                why.append(f"{len(proof_runs)} cited runs bake the proof corpus (exactly one required)")
            else:
                run = proof_runs[0]
                m, r = run.manifest, run.run
                prov = self.run_at(cell_id)
                if r.get("manifestSha256") != sha256(run.files["bake-manifest.semb.json"]):
                    why.append("the recorded manifest SHA-256 is not the file's")
                if m.get("device") != "gpu":
                    why.append(f"manifest device is {m.get('device')!r}")
                descriptor = m.get("build_descriptor") if isinstance(m.get("build_descriptor"), dict) else {}
                if any(descriptor.get(f) != cell.get(f) for f in DESCRIPTOR_FIELDS) or \
                        m.get("machine_tier") != cell.get("cpuTier"):
                    why.append("the GPU bake's descriptor or machine_tier is not the cell's")
                for label, key in GPU_ENTRY_KEYS.items():
                    if m.get(label) != entry.get(key):
                        why.append(f"manifest {label} {m.get(label)!r} != entry {key} {entry.get(key)!r}")
                if prov is None or prov.run is None:
                    why.append("the cell has no provisional run")
                else:
                    if r.get("derivationInputsSha256") != prov.run.get("derivationInputsSha256"):
                        why.append("derivationInputsSha256 differs from the cell's provisional run's")
                    if run.lines != prov.lines:
                        why.append("row-digests.tsv differs from the cell's provisional receipt")
                    if run.files["token-id-digest.txt"] != prov.files["token-id-digest.txt"]:
                        why.append("token-id-digest.txt differs from the cell's provisional receipt")
            if why:
                self.refuse("i", f"{name}: " + "; ".join(why))

    # -- the whole check ----------------------------------------------------------------------------------------
    def check(self, extends: tuple[Path, Path] | None = None, structural: bool = False) -> dict[str, list[str]]:
        self.load_list()
        self.clause_a_b()
        if structural:
            return self.refused
        self.load_identity()
        self.clause_b_prime()
        self.clause_c()
        self.clause_c_prime()
        if self.interim:
            self.notes.append(f"C42(e), (f) and (i) grade a release list; {LIST_PATH} is {self.release!r}")
        else:
            self.clause_e()
            self.clause_f()
            self.clause_i()
        if extends:
            self.clause_g(*extends)
        return self.refused


def check(root: Path, extends: tuple[Path, Path] | None = None, structural: bool = False) -> dict[str, list[str]]:
    return Checker(root).check(extends, structural)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, required=True, help="the package root (the repository root for the "
                                                              "committed package)")
    ap.add_argument("--extends", type=Path, help="the prior release's certified-builds.json (clause (g))")
    ap.add_argument("--extends-identity", type=Path, help="the prior release's certification-identity.json")
    ap.add_argument("--structural", action="store_true", help="clauses (a) and (b) only, for configure")
    args = ap.parse_args(argv)
    if bool(args.extends) != bool(args.extends_identity):
        ap.error("--extends and --extends-identity go together")
    checker = Checker(args.root)
    try:
        refused = checker.check((args.extends, args.extends_identity) if args.extends else None, args.structural)
    except (OSError, ValueError, AttributeError) as exc:
        print(f"REFUSED C42: the package at {args.root} cannot be read: {exc}")
        return 1
    failed = False
    for clause in CLAUSES:
        if refused[clause]:
            failed = True
            for item in refused[clause]:
                print(f"REFUSED C42({clause}) {item}")
    for note in checker.notes:
        print(note)
    if args.structural:
        for path in sorted({p.resolve().as_posix() for p in checker.read}):
            print(f"READ {path}")
    if not failed:
        what = "clauses (a) and (b)" if args.structural else "every clause that grades this list"
        print(f"ACCEPTED: {args.root / LIST_PATH} -- {what}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
