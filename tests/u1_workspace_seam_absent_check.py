"""K-18: actual static-library bytes, with a positive detection control."""
from pathlib import Path
import argparse

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--production', required=True)
    ap.add_argument('--testseam', required=True)
    args = ap.parse_args()
    failed = False
    for label, filename, expected in [('K-18a', args.production, False), ('K-18b', args.testseam, True)]:
        path = Path(filename)
        if not path.is_file():
            print(f'[SETUP FAILURE] {label}: missing static library {path}')
            failed = True
            continue
        found = b'semb_test_seam_' in path.read_bytes()
        if expected and not found:
            print(f'[RED-UNIMPLEMENTED] {label}: MISSING PREREQUISITE: builder seam definitions absent from {path}; presence control is unimplemented')
            failed = True
        else:
            ok = found == expected
            print(f'[{"PASS" if ok else "FAIL"}] {label}: seam names {"present" if found else "absent"} in {path}')
            failed |= not ok
    return int(failed)

if __name__ == '__main__':
    raise SystemExit(main())
