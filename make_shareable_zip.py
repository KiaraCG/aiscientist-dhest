#!/usr/bin/env python3
"""Package only explicitly approved source files and fixed synthetic fixtures.

No recursion over an exam workspace. No .env, tokens, real scans, grades or
venvs are automatically collected. This is a release guard, not a general
confidentiality detector; read docs/SECURITY_AND_SHARING.md before editing it.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent
TEXT_SUFFIXES = {'.py','.md','.txt','.json'}
SUSPECT = [re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
           re.compile(rb'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}\b'),
           re.compile(rb'\bgh[pousr]_[A-Za-z0-9]{30,}\b')]


def digest(data):return hashlib.sha256(data).hexdigest()


def payloads(root: Path = ROOT) -> dict[str, bytes]:
    root=root.resolve()
    names=[s.strip() for s in (root/'PACKAGE_FILES.txt').read_text(encoding='utf-8').splitlines()
           if s.strip() and not s.lstrip().startswith('#')]
    if len(set(names))!=len(names) or '.env.example' not in names:
        raise ValueError('Duplicate allowlist paths or missing .env.example')
    fixed=json.loads((root/'SYNTHETIC_SHA256.json').read_text())
    if not isinstance(fixed,dict) or '.env.example' not in fixed:
        raise ValueError('Missing fixed-fixture/placeholder audit record')
    out={}
    for name in names:
        p=PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or '\\' in name or str(p)!=name:
            raise ValueError(f'Unsafe archive path: {name}')
        if any(s in {'.env','.venv','venv','.git','__pycache__','.DS_Store'} or
               (s.startswith('.env') and name!='.env.example') for s in p.parts):
            raise ValueError(f'Forbidden archive path: {name}')
        path=root/name
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent!=root and parent.is_relative_to(root)):
            raise ValueError(f'Symlink in approved path: {name}')
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError(f'Not an ordinary approved file: {name}')
        if name not in {'.env.example','.gitignore'} and path.suffix not in TEXT_SUFFIXES | {'.pdf'}:
            raise ValueError(f'Unexpected file type: {name}')
        raw=path.read_bytes()
        if name.startswith('examples/') or name=='.env.example':
            if fixed.get(name)!=digest(raw):
                raise ValueError(f'Example/placeholder file changed or not approved: {name}')
        if path.suffix=='.pdf' and not name.startswith('examples/minimal_exam/'):
            raise ValueError('Only fixed synthetic PDF fixtures can be distributed')
        if path.suffix!='.pdf' and any(pattern.search(raw) for pattern in SUSPECT):
            raise ValueError(f'Recognizable credential/private-key pattern in {name}; inspect before sharing')
        out[name]=raw
    if set(fixed)-set(out):raise ValueError('A fixed fixture is absent from the allowlist')
    return out


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT.parent/'exam_scoring_toolkit_share.zip')
    args=parser.parse_args(argv)
    data=payloads()
    report={'package':'exam_scoring_toolkit','format_version':1,'source_file_count':len(data),
            'source_bytes':sum(map(len,data.values())),
            'env_example_included':'.env.example' in data,'working_env_included':False,
            'release_mode':'Explicit allowlist; fixed synthetic fixtures and placeholder template verified',
            'limits':'Pattern checks are not a general confidentiality proof. No digital signature.',
            'files':{name:digest(raw) for name,raw in sorted(data.items())}}
    print(f'Validated {len(data)} allowlisted files; .env.example included; no .env included.')
    print('Fixed example assets match their synthetic release hashes. Real workspaces and outputs are not selected.')
    if args.check:return 0
    destination=args.output.resolve()
    if destination.is_relative_to(ROOT) or destination.exists() or args.output.is_symlink():
        raise ValueError('Choose a new archive path outside the toolkit directory; nothing is overwritten')
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.exam_toolkit_',suffix='.zip',dir=destination.parent)
    os.close(fd)
    try:
        with ZipFile(temporary,'w',ZIP_DEFLATED) as z:
            for name,raw in sorted(data.items()):z.writestr('exam_scoring_toolkit/'+name,raw)
            z.writestr('exam_scoring_toolkit/RELEASE_AUDIT.json',json.dumps(report,indent=2)+'\n')
            z.writestr('exam_scoring_toolkit/SHA256SUMS.txt',''.join(f'{digest(raw)}  {name}\n' for name,raw in sorted(data.items())))
        with ZipFile(temporary) as z:
            if z.testzip() is not None:raise ValueError('Archive integrity check failed')
            expected={'exam_scoring_toolkit/'+name for name in data}|{'exam_scoring_toolkit/RELEASE_AUDIT.json','exam_scoring_toolkit/SHA256SUMS.txt'}
            if set(z.namelist())!=expected:raise ValueError('Archive contents differ from approved payloads')
        os.link(temporary,destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print(f'Wrote {destination} ({destination.stat().st_size:,} bytes). SHA256: {digest(destination.read_bytes())}')
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr);raise SystemExit(1)
