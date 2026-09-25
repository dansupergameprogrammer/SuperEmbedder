"""U2 cloud build: U2-1's C56, the Linux shared library's proof (te267 sec 5
U2-1, C56; F44).

  (1) `cmake --install` of this build places the shared library (`libsemb.so`)
      and the public header `semb.h`;
  (2) the shared library's exported set (`nm -D --defined-only`, T) equals
      `semb.h`'s declaration scan by U2-1's corrected rule, exactly (0 extra,
      0 missing);
  (3) a C application linked against the installed `.so` alone carries
      NEEDED exactly {libsemb.so, libc.so.6} (no static fallback);
  (4) mechanism leg (runs here): that application opens the synthetic pair,
      reads `semb_fingerprint_of`, and encodes corpus-239's texts through
      `semb_encode_batch`, all SEMB_OK, with the fingerprint and every row byte
      equal to the same application statically linked against the certified
      archive (`libsuperembedder.a` plus the engine);
  (5) real leg (dev box / WSL member): the same on the real artifact, with the
      fingerprint `5485a7e8ce4caad2...` and the rows' SHA-256
      `38cdbdc0612b8804...` (the adversary's reading, TE-325), and equal to the
      static route. Without --model/--tokenizer: MISSING PREREQUISITE.

RED TODAY: nothing is installed (no install() rules, no shared target), so
(1) fails and (2)-(5) cannot run. The library name `libsemb.so` and the NEEDED
spelling are the plan's; a versioned soname is accepted as `libsemb.so[.N...]`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS = REPO_ROOT / "tests" / "fixtures" / "c12b" / "corpus-239.jsonl"
SCAN = re.compile(r"^(?:SEMB_API\s+)?(semb_status|const char\*)\s+(semb_[a-z0-9_]+)\(", re.M)
REAL_FP_PREFIX = "5485a7e8ce4caad2"
REAL_ROWS_PREFIX = "38cdbdc0612b8804"

APP = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "superembedder/semb.h"
/* argv: model tokenizer corpus.bin rows.out. corpus.bin: u32 count, then per
 * document u32 len + bytes. Prints status names and the fingerprint hex. */
static unsigned char* slurp(const char* p, long* n) {
  FILE* f = fopen(p, "rb"); if (!f) return NULL;
  fseek(f, 0, SEEK_END); *n = ftell(f); fseek(f, 0, SEEK_SET);
  unsigned char* b = (unsigned char*)malloc((size_t)*n); fread(b, 1, (size_t)*n, f); fclose(f); return b;
}
int main(int argc, char** argv) {
  if (argc != 5) return 2;
  semb_config cfg; memset(&cfg, 0, sizeof cfg);
  cfg.struct_size = sizeof cfg; cfg.model_path = argv[1]; cfg.model_path_len = strlen(argv[1]);
  cfg.tokenizer_path = argv[2]; cfg.tokenizer_path_len = strlen(argv[2]); cfg.max_concurrency = 4;
  semb_encoder enc = NULL;
  semb_status s = semb_encoder_open(&cfg, &enc);
  printf("open %s\n", semb_status_name(s)); if (s != SEMB_OK) return 1;
  semb_fingerprint fp; memset(&fp, 0, sizeof fp); fp.struct_size = sizeof fp;
  s = semb_fingerprint_of(enc, &fp);
  printf("fingerprint_of %s ", semb_status_name(s));
  for (int i = 0; i < 32; ++i) printf("%02x", fp.digest[i]);
  printf("\n");
  long n = 0; unsigned char* c = slurp(argv[3], &n); if (!c) return 3;
  unsigned count; memcpy(&count, c, 4);
  semb_document* docs = (semb_document*)calloc(count, sizeof *docs);
  char (*ids)[16] = calloc(count, 16);
  long off = 4;
  for (unsigned i = 0; i < count; ++i) {
    unsigned len; memcpy(&len, c + off, 4); off += 4;
    snprintf(ids[i], 16, "d%u", i);
    docs[i].struct_size = sizeof(semb_document); docs[i].id = ids[i]; docs[i].id_len = strlen(ids[i]);
    docs[i].utf8 = (const char*)(c + off); docs[i].utf8_len = len; off += len;
  }
  uint32_t dims = 0; semb_encoder_dims(enc, &dims);
  size_t bytes = (size_t)count * dims * 4, req = 0;
  float* rows = (float*)malloc(bytes);
  s = semb_encode_batch(enc, docs, count, rows, bytes, &req);
  printf("encode_batch %s %zu\n", semb_status_name(s), bytes);
  FILE* o = fopen(argv[4], "wb"); fwrite(rows, 1, bytes, o); fclose(o);
  printf("close %s\n", semb_status_name(semb_encoder_close(enc)));
  return s == SEMB_OK ? 0 : 1;
}
'''


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", **kw)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", required=True)
    ap.add_argument("--archive", required=True, help="the certified static archive (static route)")
    ap.add_argument("--engine-lib", required=True, help="the engine's static library (static route)")
    ap.add_argument("--model", default="")
    ap.add_argument("--tokenizer", default="")
    args = ap.parse_args(argv)
    build = Path(args.build_dir)
    work = build / "_scratch" / "c56"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    fails = 0

    def verdict(ok: bool, cell: str, detail: str) -> None:
        nonlocal fails
        fails += 0 if ok else 1
        print(f"[{'PASS' if ok else 'FAIL'}] {cell}: {detail}")

    prefix = work / "install"
    inst = run(["cmake", "--install", str(build), "--prefix", str(prefix)])
    sos = sorted(p for p in prefix.rglob("libsemb.so*") if p.is_file()) if prefix.exists() else []
    header = prefix / "include" / "superembedder" / "semb.h"
    verdict(inst.returncode == 0 and bool(sos) and header.is_file(),
            "C56 (1) cmake --install places libsemb.so and semb.h",
            f"exit {inst.returncode}; libsemb.so: {[str(p.relative_to(prefix)) for p in sos] or 'absent'}; "
            f"semb.h: {'present' if header.is_file() else 'absent'}")
    if not sos or not header.is_file():
        print("[NOT RUN] C56 (2)-(5): nothing to read without the installed shared library and header")
        print(f"TOTAL fail={fails}")
        return 1
    so = sos[0]
    declared = {m.group(2) for m in SCAN.finditer(header.read_text(encoding="utf-8"))}
    nm = run(["nm", "-D", "--defined-only", str(so)]).stdout
    exported = {ln.split()[2] for ln in nm.splitlines() if len(ln.split()) == 3 and ln.split()[1] == "T"}
    verdict(exported == declared and len(declared) >= 12,
            f"C56 (2) exported set equals semb.h's scan ({len(declared)} declared)",
            f"{len(exported & declared)} of {len(declared)}, extra {sorted(exported - declared)[:8]}, "
            f"missing {sorted(declared - exported)}")
    src = work / "c56_app.c"
    src.write_text(APP, encoding="utf-8")
    app = work / "c56_app"
    cc = run(["cc", "-O2", "-o", str(app), str(src), f"-I{prefix / 'include'}", f"-L{so.parent}", "-lsemb",
              f"-Wl,-rpath,{so.parent}"])
    needed = [m.group(1) for m in re.finditer(r"\(NEEDED\).*\[(.*)\]", run(["readelf", "-d", str(app)]).stdout)]
    ok_needed = (cc.returncode == 0 and len(needed) == 2 and "libc.so.6" in needed
                 and any(re.fullmatch(r"libsemb\.so(\.\d+)*", n) for n in needed))
    verdict(ok_needed, "C56 (3) the C application's NEEDED is exactly libsemb.so and libc.so.6",
            f"link exit {cc.returncode}; NEEDED {needed} {cc.stderr.strip()[-300:]}")
    static_app = work / "c56_app_static"
    sc = run(["c++", "-O2", "-x", "c", str(src), "-x", "none", "-o", str(static_app),
              f"-I{REPO_ROOT / 'include'}", args.archive, args.engine_lib, "-lpthread", "-lm"])
    if sc.returncode:
        verdict(False, "C56 static route: the same application linked against the certified archive",
                sc.stderr.strip()[-400:])
    corpus = [json.loads(ln)["text"].encode("utf-8") for ln in CORPUS.read_text(encoding="utf-8").splitlines()]
    blob = struct.pack("<I", len(corpus)) + b"".join(struct.pack("<I", len(t)) + t for t in corpus)
    (work / "corpus.bin").write_bytes(blob)

    def leg(name: str, model: str, tok: str, real: bool) -> None:
        outs = {}
        for route, exe in (("so", app), ("static", static_app)):
            if not exe.exists():
                continue
            rows = work / f"{name}_{route}.rows"
            r = run([str(exe), model, tok, str(work / "corpus.bin"), str(rows)], timeout=3600)
            fp = re.search(r"fingerprint_of (\S+) ([0-9a-f]{64})", r.stdout)
            outs[route] = (r.returncode, r.stdout, fp.group(2) if fp else "",
                           rows.read_bytes() if rows.exists() else b"")
        so_r = outs.get("so")
        st_r = outs.get("static")
        ok = bool(so_r) and so_r[0] == 0 and "open SEMB_OK" in so_r[1] and "fingerprint_of SEMB_OK" in so_r[1] \
            and "encode_batch SEMB_OK" in so_r[1] and "close SEMB_OK" in so_r[1]
        verdict(ok, f"C56 ({name}) open / fingerprint_of / encode_batch / close SEMB_OK through the .so alone",
                (so_r[1].strip().replace("\n", " | ") if so_r else "application absent")[:300])
        if so_r and st_r:
            verdict(so_r[2] == st_r[2] and so_r[3] == st_r[3] and len(so_r[3]) > 0,
                    f"C56 ({name}) fingerprint and all {len(corpus)} rows byte-equal to the static route",
                    f"fp {so_r[2][:16]}/{st_r[2][:16]}; rows sha {hashlib.sha256(so_r[3]).hexdigest()[:16]}/"
                    f"{hashlib.sha256(st_r[3]).hexdigest()[:16]}")
        if real and so_r:
            sha = hashlib.sha256(so_r[3]).hexdigest()
            verdict(so_r[2].startswith(REAL_FP_PREFIX) and sha.startswith(REAL_ROWS_PREFIX),
                    "C56 (5) real: fingerprint 5485a7e8ce4caad2... and rows SHA-256 38cdbdc0612b8804...",
                    f"fp {so_r[2][:16]} rows {sha[:16]}")

    pair = REPO_ROOT / "build" / "_scratch" / "u2_9_min_pair"
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import u2_9_workspace_cells_check as u29  # noqa: E402
    u29.ensure_pair(pair)
    leg("4", str(pair / "u1_pair_model.sslm"), str(pair / "u1_pair_tokenizer.sslm"), False)
    if args.model and args.tokenizer:
        leg("5", args.model, args.tokenizer, True)
    else:
        print("[MISSING PREREQUISITE] C56 (5) real leg: needs the real model and tokenizer "
              "(SEMB_C12B_MODEL, SEMB_U1_TOKENIZER); owed to the certified GCC WSL member on the dev box")
    print(f"TOTAL fail={fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
