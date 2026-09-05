"""TE-114: real first-party K-15 failure-path controls at unchanged deadlines.

Generated adapter copies are diagnostics, never installed or put on production.
The actual workspace child and its parent classify every injected fault.
"""
from pathlib import Path
import hashlib
import json
import time
from support.workspace_build_control import ROOT, parser, build, save
from u1_raw_text_cells_check import Table, workspace_child, ensure_pair, find_exe

CASES = ('healthy', 'startup', 'release_budget', 'reset_budget', 'rendezvous',
         'late_encode', 'late_close', 'cleanup', 'parent')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('fault anchor must occur exactly once: '+old)
    return text.replace(old, new)

def mutant(source, case):
    if case == 'startup':
        return replace_once(source, 'static std::atomic<uint64_t> acquisitions{0};',
                            'static std::atomic<uint64_t> acquisitions{1};')
    if case == 'release_budget':
        return replace_once(source, '++semb::test_seam::release_generation;\n  semb::test_seam::park_budget = 0;',
                            '++semb::test_seam::release_generation; // CONTROL: residual budget retained')
    if case == 'reset_budget':
        return replace_once(source, '  semb::test_seam::park_budget = 0;\n  semb::test_seam::acquisitions.store(0);',
                            '  // CONTROL: unused budget retained\n  semb::test_seam::acquisitions.store(0);')
    if case == 'rendezvous':
        return replace_once(source, 'semb::test_seam::park_budget = count;',
                            'semb::test_seam::park_budget = count ? count - 1 : 0;')
    if case in ('cleanup', 'parent'):
        entry = ('extern "C" void semb_test_seam_release(void) {' if case == 'cleanup' else
                 'extern "C" uint64_t semb_test_seam_acquisitions(void) {')
        stuck = '''
  { // CONTROL: a real seam call never completes.
    std::unique_lock<std::mutex> stuck_lock(semb::test_seam::state_mutex);
    semb::test_seam::state_changed.wait(stuck_lock, [] { return false; });
  }
'''
        return replace_once(source, entry, entry+stuck)
    return source

def main():
    p = parser(__doc__)
    p.add_argument('--only', choices=CASES, action='append', help='Run named controls; default is the complete population')
    args = p.parse_args()
    root = Path(args.build_dir).resolve(); root.mkdir(parents=True, exist_ok=True)
    pair = Path(args.pair_dir).resolve(); fixture = ensure_pair(pair)
    original_path = ROOT/'src/superembedder/engine_adapter_interim.cpp'
    original = original_path.read_bytes()
    original_copy = root/'original_engine_adapter_interim.cpp'; original_copy.write_bytes(original)
    source = original.decode().replace('\r\n','\n')
    report = {'tracked_adapter': str(original_path), 'original_sha256': digest(original),
              'original_copy': str(original_copy), 'fixture': fixture, 'cases': [],
              'policy_seconds': {'rendezvous_refusal':10,'cleanup':30,'parent':600}}
    failed = False
    for case in args.only or CASES:
        print('[CONTROL] starting '+case, flush=True)
        work = root/case; work.mkdir(parents=True, exist_ok=True)
        records = []; row = {'case':case}; report['cases'].append(row)
        try:
            copied = work/'engine_adapter_interim.cpp'
            copy_bytes = original if case in ('healthy','late_encode','late_close') else mutant(source,case).encode()
            copied.write_bytes(copy_bytes)
            row.update(adapter=str(copied), adapter_sha256=digest(copy_bytes))
            extra = ['-DSEMB_WORKSPACE_DIAGNOSTIC_ADAPTER='+copied.as_posix()]
            if case.startswith('late_'): extra.append('-DSEMB_WORKSPACE_DELAY_REFUSAL_HELPERS=ON')
            build(args,work/'build',extra,records)
            exe = find_exe(work/'build','u1_workspace_seam_test')
            if exe is None: raise RuntimeError('built workspace child is absent')
            cells = ('K-15h','K-15d','K-15e','K-15f','K-15g') if case == 'healthy' else (
                'K-15h' if case in ('startup','release_budget','reset_budget','parent') else
                'K-15e' if case == 'late_close' else 'K-15d',)
            row['children'] = []
            for cell in cells:
                child_args = ['--model',str(pair/'u1_pair_model.sslm'),'--tokenizer',str(pair/'u1_pair_tokenizer.sslm'),
                              '--dims','32','--cell',cell]
                receipt = {'command':[str(exe),*child_args]}; table = Table()
                started = time.monotonic()
                result = workspace_child(exe,child_args,case+' '+cell,table,receipt)
                receipt['elapsed_seconds'] = time.monotonic()-started
                receipt['first_party_rows'] = table.rows
                row['children'].append(receipt)
                output = receipt['stdout']
                phase = {'startup':'[FAIL] K-15h startup epoch is empty',
                         'release_budget':'[FAIL] K-15h released residual budget completes without rearm/release',
                         'reset_budget':'[FAIL] K-15h reset residual budget completes without rearm/release',
                         'rendezvous':'[FAIL] K-15d exactly N acquired and parked',
                         'late_encode':'[FAIL] K-15d refusal deadline',
                         'late_close':'[FAIL] K-15e close refusal deadline',
                         'cleanup':'[FAIL] cleanup release exceeded 30 seconds',
                         'parent':'[PHASE] startup before any encode/reset'}.get(case)
                ok = receipt['reaped'] and (result is not None and not table.failed if case == 'healthy' else
                     result is None and table.failed and receipt['returncode'] != 0 and phase in output)
                ok = ok and receipt['timed_out'] == (case == 'parent')
                if case.startswith('late_'):
                    verb = 'encode' if case == 'late_encode' else 'close'
                    ok = ok and f'[CONTROL] late {verb} actual result: SEMB_OK' in output
                if case in ('release_budget','reset_budget','rendezvous','late_encode','late_close'):
                    ok = ok and '[PHASE] drain/join' in output and '[PASS] reset establishes empty epoch' in output
                if case == 'parent':
                    ok = ok and any('600-second child deadline; child killed and waited' in r[2] for r in table.rows)
                receipt['control_accepted'] = bool(ok)
                if not ok: raise RuntimeError('first-party expected outcome missing for '+case+' '+cell)
            row['state'] = 'PASS'
            print('[PASS] expected first-party outcome: '+case,flush=True)
        except Exception as exc:
            row.update(state='FAIL',error=str(exc)); failed=True
            print('[FAIL] control '+case+': '+str(exc),flush=True)
        finally:
            save(work,records)
            row['commands_manifest'] = str(work/'commands.json')
            (root/'results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    report['tracked_adapter_unchanged'] = original_path.read_bytes() == original
    failed = failed or not report['tracked_adapter_unchanged']
    (root/'results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return int(failed)

if __name__ == '__main__':
    raise SystemExit(main())
