// tests/semb_epoch_store_contract.h -- TE-162 (U1 slice 3 red suite): the
// test author's own concrete pin of the append-only epoch store's on-disk
// shape (`Claude/Plans/SuperEmbedder_Plan.md` sec 8, C32; sec 3.5's "the
// structure is the epoch rather than a re-mint"; the conductor's fixed
// points, D-SLM6377, `Claude/Bach/briefs/te162-slice3-red.md`).
//
// THIS FILE DECLARES A CONTRACT, NOT AN IMPLEMENTATION -- the identical
// convention `tests/semb_seam_abi_contract.h` and
// `tests/semb_ps_n_pool_abi_contract.h` already carry: Curie's own concrete
// pin of a shape the plan and the dispatch already commit to in prose, kept
// in sync BY HAND with `tests/epoch_store_contract.py`'s own Python mirror
// (the sibling module the dispatch names) -- two files, one shape, checked
// by every cell that reads either. The store itself does not exist yet
// (`grep -rniE "epoch_store|EpochStore|lineage"` across `src/`, `include/`,
// `tools/` returns nothing at this branch's own base, confirmed this
// round); the builder's round is what makes a directory on disk match this
// contract.
//
// THE PATH LAYOUT, sec 8 C32 + the dispatch's own fixed points:
//   epoch-store/live/<fingerprint-hex>/{vectors.f32, row-digest.tsv, lineage.tsv}
//   epoch-store/archive/<fingerprint-hex>/{vectors.f32, row-digest.tsv, lineage.tsv}
// <fingerprint-hex> is the fingerprint's bytes (semb_fingerprint::digest,
// 32 bytes) as LOWERCASE hex, 64 characters, no prefix. The repository's
// `.gitattributes` already declares `* -text` at its root (confirmed this
// round: `git check-attr text` on a path under epoch-store/ reports
// "text: unset"), which this contract's own cell (5) asserts rather than
// assumes, per this project's own "a claim is checked, never taken on
// prose" discipline.
//
// THE THREE MEMBERS PER ENTRY, byte-exact:
//   vectors.f32   -- the emitted float32 rows, corpus order, little-endian,
//                     dims*4 bytes per row, no header, no separator. Row i
//                     is document i of the entry's own corpus order.
//   row-digest.tsv -- one line per document, corpus order:
//                     "<id>\t<psn_vector_sha256>\n"
//                     then a final line "all\t<sha256 over vectors.f32>\n".
//                     psn_vector_sha256 is SHA-256 over that document's own
//                     dims*4-byte slice of vectors.f32 -- the same
//                     definition tests/c12b_row_digest_check.py's own
//                     psn_vector_sha256 column carries (its own docstring:
//                     "SHA-256 over the float32 vector bytes PS-N emits
//                     from that position -- what a user receives").
//   lineage.tsv    -- one line per document, corpus order:
//                     "<id>\t<seam_sha256>\n"
//                     then a final line
//                     "all\t<sha256 over u64(document_count) LE, then each
//                     document's own semb_seam_serialize_document bytes in
//                     corpus order>\n".
//                     seam_sha256 is SHA-256 over
//                     `semb_seam_serialize_document`'s own bytes for EVERY
//                     position of the document (position 0 included, the
//                     appended end token included) -- sec 4.4b's own W-B
//                     formula applied per document rather than pooled
//                     across the corpus, and the same column
//                     tests/c12b_row_digest_check.py's own instrument
//                     already emits under this exact name.
//
// THE THREE FAIL STATUSES this slice's check reports by NAME (sec 8 C32's
// own able-to-fail list). These are BUILD-TIME CHECK OUTCOMES, the way
// cmake/SourceProvenance.cmake emits SEMB_SOURCE_SET_DRIFT and
// cmake/EngineGuards.cmake emits SEMB_ENGINE_INSTALL_DIVERGED -- NOT
// members of the `semb_status` C ABI enum (tests/semb_public_abi_contract.h
// carries them as plan names only, kPlanStatusNames, reported
// present-or-absent, never required; this slice does not touch that
// header's own count, per the dispatch's own standing constraint).
//
// THE PARTITION THIS CONTRACT FIXES between the three statuses, so the
// check (tests/epoch_store_check.py) and the constructions population
// (tests/epoch_store_constructions_check.py, twelve as of TE-170/TE-174/TE-180)
// agree on which status a given mutation produces, and so the builder's
// own product code, once it
// exists, is graded against a fixed rather than an improvised meaning:
//   - vectors.f32 and/or row-digest.tsv differ from the parent commit's
//     entry at the SAME fingerprint path, lineage.tsv held fixed
//     -> SEMB_EPOCH_BYTES_DIVERGED ("bytes moving under an unchanged
//     fingerprint" -- vectors.f32 is the bytes; row-digest.tsv is derived
//     from them and moves together with them under any real mutation, so
//     the two members are graded as one group for this status).
//   - lineage.tsv differs from the parent commit's entry at the SAME
//     fingerprint path, vectors.f32 AND row-digest.tsv both held fixed
//     -> SEMB_EPOCH_LINEAGE_DIVERGED ("the lineage digest moving alone").
//   - every member differs at the SAME fingerprint path (a wholesale
//     overwrite, "re-minting an entry in place"), OR a live entry present
//     in the parent commit is absent from HEAD with no byte-identical twin
//     under archive/<same fingerprint>/ in HEAD ("an entry leaves the live
//     store only by ARCHIVE-BY-MOVE... absent a matching archive entry,
//     deletion stays SEMB_EPOCH_ENTRY_MODIFIED", sec 8 C32 verbatim), OR an
//     entry ALREADY present under archive/<fingerprint>/ in the parent
//     commit is absent, or byte-different, at that SAME archive path in
//     HEAD (TE-170, C1: "an entry may never leave archive/" applies with
//     equal force to the destination of the move, not only to the source --
//     the archive path is not merely accepted once and then unwatched)
//     -> SEMB_EPOCH_ENTRY_MODIFIED.
//   - a NEW fingerprint directory present in HEAD's live/ with no entry at
//     that path in the parent commit, whose own three members are
//     internally well-formed (cell 1a) -> GREEN, an ordinary append.
#ifndef SEMB_EPOCH_STORE_CONTRACT_H
#define SEMB_EPOCH_STORE_CONTRACT_H

namespace semb_epoch_contract {

// Path layout, relative to the product repository root.
inline constexpr const char* kLiveDir = "epoch-store/live";
inline constexpr const char* kArchiveDir = "epoch-store/archive";

// The three member file names, identical under live/ and archive/.
inline constexpr const char* kVectorsFileName = "vectors.f32";
inline constexpr const char* kRowDigestFileName = "row-digest.tsv";
inline constexpr const char* kLineageFileName = "lineage.tsv";

// The three named FAIL statuses (sec 8 C32), reported by the check as
// PASS/FAIL row names -- not part of the semb_status C ABI enum this
// round (see this file's own header comment).
inline constexpr const char* kStatusBytesDiverged = "SEMB_EPOCH_BYTES_DIVERGED";
inline constexpr const char* kStatusLineageDiverged = "SEMB_EPOCH_LINEAGE_DIVERGED";
inline constexpr const char* kStatusEntryModified = "SEMB_EPOCH_ENTRY_MODIFIED";

// A fingerprint digest is always exactly 32 bytes (semb_fingerprint::digest,
// include/superembedder/semb.h); its directory name is always exactly 64
// lowercase hex characters, no prefix.
inline constexpr int kFingerprintBytes = 32;
inline constexpr int kFingerprintHexChars = 64;

}  // namespace semb_epoch_contract

#endif  // SEMB_EPOCH_STORE_CONTRACT_H
