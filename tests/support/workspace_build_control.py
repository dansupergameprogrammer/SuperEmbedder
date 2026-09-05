"""Shared execution plumbing for real K-15 build controls; never changes source."""
from pathlib import Path
import argparse
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]

def parser(description):
    p = argparse.ArgumentParser(description=description)
    p.add_argument('--build-dir', required=True)
    p.add_argument('--engine-prefix', required=True)
    p.add_argument('--engine-lock', default='')
    p.add_argument('--c38-define-target', choices=('', 'library', 'witness'), default='')
    p.add_argument('--cmake-executable', default='cmake')
    p.add_argument('--ninja-executable', default='ninja')
    p.add_argument('--cxx-compiler', required=True)
    p.add_argument('--rc-compiler', default='')
    p.add_argument('--mt-executable', default='')
    p.add_argument('--pair-dir', default=str(ROOT/'build/_scratch/u1_pair'))
    return p

def command(args, root, argv, name, records):
    root.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, errors='replace', timeout=600)
    (root/(name+'.log')).write_text(p.stdout+p.stderr, encoding='utf-8')
    records.append({'command':argv,'exit':p.returncode,'log':str(root/(name+'.log'))})
    if p.returncode:
        raise RuntimeError(f'{name} failed with exit {p.returncode}; see {root/(name+".log")}')

def build(args, root, extra, records, targets=('superembedder','superembedder_testseam','u1_workspace_seam_test')):
    configure=[args.cmake_executable,'-S',str(ROOT),'-B',str(root),'-G','Ninja',
               '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+args.cxx_compiler.replace('\\','/'),
               '-DCMAKE_MAKE_PROGRAM='+args.ninja_executable.replace('\\','/'),
               '-DCMAKE_PREFIX_PATH='+args.engine_prefix.replace('\\','/'),
               '-DPython3_EXECUTABLE='+sys.executable.replace('\\','/'),*extra]
    if args.engine_lock:configure.append('-DSEMB_ENGINE_LOCK_FILE='+args.engine_lock.replace('\\','/'))
    if args.c38_define_target:configure.append('-DSEMB_C38_DEFINE_TARGET='+args.c38_define_target)
    if args.rc_compiler:configure.append('-DCMAKE_RC_COMPILER='+args.rc_compiler.replace('\\','/'))
    if args.mt_executable:configure.append('-DCMAKE_MT='+args.mt_executable.replace('\\','/'))
    command(args,root,configure,'configure',records)
    command(args,root,[args.cmake_executable,'--build',str(root),'--target',*targets],'build',records)

def save(root, records):
    (root/'commands.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
