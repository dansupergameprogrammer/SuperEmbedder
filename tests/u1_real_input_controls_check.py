"""TE-120: actual healthy/rejecting real fixture prerequisite controls.

Runs the same stdlib verifier, engine-only probe and public rejection path as
the registered driver. Never starts an at-cap forward. All processes are serial.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from fixtures import u1_real_inputs as inputs
from u1_raw_text_cells_check import build_targets, find_exe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, required=True)
    parser.add_argument('--cmake-executable', default='cmake')
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--tokenizer', type=Path, required=True)
    parser.add_argument('--real-inputs', type=Path, required=True)
    args = parser.parse_args()
    root = args.build_dir / 'real-input-controls'
    root.mkdir(parents=True, exist_ok=True)
    records = []
    failed = False

    def record(name, ok, detail):
        nonlocal failed
        failed |= not ok
        records.append(dict(name=name, passed=ok, detail=detail))
        print(f'[{"PASS" if ok else "FAIL"}] {name}: {detail}', flush=True)
        (root / 'results.json').write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8')

    def run(name, command, expected, needle):
        result = subprocess.run(command, cwd=inputs.ROOT, capture_output=True, text=True, errors='replace')
        output = result.stdout + result.stderr
        (root / (name + '.log')).write_text(output, encoding='utf-8')
        record(name, result.returncode == expected and needle in output,
               dict(command=command, exit=result.returncode, expected=expected, needle=needle, output=output))

    built, _, output = build_targets(args.cmake_executable, args.build_dir, ['u1_real_input_probe', 'u1_raw_text_contract_test'])
    if not built:
        record('build prerequisite', False, output)
        return 1
    probe, contract = (find_exe(args.build_dir, n) for n in ('u1_real_input_probe', 'u1_raw_text_contract_test'))
    verifier = [sys.executable, str(Path(__file__).parent / 'fixtures/u1_real_inputs.py'), '--model', str(args.model), '--tokenizer', str(args.tokenizer)]
    run('healthy-identity', [*verifier, '--out-dir', str(args.real_inputs)], 0, '[PASS] REAL_INPUT_SETUP')
    base_probe = [str(probe), str(args.model), str(args.tokenizer)]
    run('healthy-engine-loader', [*base_probe, str(args.real_inputs / 'foreign-tokenizer.sslm'), str(args.real_inputs)], 0, 'total_positions=32768 every HF reference ID agrees')
    run('matching-as-foreign', [*base_probe, str(args.tokenizer), str(args.real_inputs)], 2, 'foreign tokenizer does not exceed model vocabulary')

    # Each independent mutation goes through the first-party verifier. The
    # malformed artifact is also sent directly to the actual engine loader.
    changes = {
        'missing-at-cap': ('at-cap.utf8', None),
        'short-at-cap': ('at-cap.utf8', lambda b: b[:-2]),
        'long-at-cap': ('at-cap.utf8', lambda b: b + b' a'),
        'wrong-reference-id': ('at-cap.ids', lambda b: bytes([65]) + b[1:]),
        'wrong-utf8-crossing': ('over-cap-invalid.utf8', lambda b: b[:-1] + b'?'),
        'malformed-foreign': ('foreign-tokenizer.sslm', lambda b: b[:64]),
        'matching-foreign-identity': ('foreign-tokenizer.sslm', lambda b: args.tokenizer.read_bytes()),
    }
    for name, (filename, change) in changes.items():
        folder = root / name
        folder.mkdir(exist_ok=True)
        for file in inputs.FILES:
            shutil.copyfile(args.real_inputs / file, folder / file)
        path = folder / filename
        if change is None:
            path.unlink()
        else:
            path.write_bytes(change(path.read_bytes()))
        run(name, [*verifier, '--out-dir', str(folder)], 2, '[FAIL] REAL_INPUT_SETUP')
        if name == 'malformed-foreign':
            run('malformed-engine-loader', [*base_probe, str(path), str(args.real_inputs)], 2, 'artifact loader')
        if name == 'wrong-reference-id':
            run('wrong-id-engine-probe', [*base_probe, str(args.real_inputs / 'foreign-tokenizer.sslm'), str(folder)], 2, 'reference ID differs at 0')
        if name in ('missing-at-cap', 'short-at-cap', 'long-at-cap'):
            run(name + '-public-setup', [str(contract), '--model', str(args.model), '--tokenizer', str(args.tokenizer),
                '--dims', '1024', '--real-inputs', str(folder), '--real-inputs-only', '--real-input-cell', 'refusals'],
                1, '[FAIL] REAL_INPUT_SETUP exact pinned real boundary bytes')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
