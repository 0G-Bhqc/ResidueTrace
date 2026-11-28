"""Offline command-line interface for user manifests and the installed teaching bundle."""

import argparse
import json
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

from .audit import AuditError, evaluate
from .render import render
from .resolve import add_parser, run as resolve_run


def _replace(path, text):
    # Publishing a new inode also avoids clobbering a hard-linked input.
    tmp = None
    try:
        with NamedTemporaryFile('w', encoding='utf-8', newline='\n', dir=path.parent, delete=False) as f:
            tmp = Path(f.name)
            f.write(text)
        tmp.replace(path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='residuetrace', description=__doc__)
    verbs = parser.add_subparsers(dest='verb', required=True)
    check = verbs.add_parser('audit', help='audit a local JSON manifest')
    check.add_argument('manifest', type=Path)
    demo = verbs.add_parser('demo', help='audit the bundled synthetic teaching example')
    for p in (check, demo):
        p.add_argument('--out', type=Path, required=True, help='destination for report.json and report.html')
    add_parser(verbs)
    args = parser.parse_args(argv)
    if args.verb == 'resolve':
        return resolve_run(args)
    path = args.manifest if args.verb == 'audit' else Path(__file__).with_name('demo') / 'manifest.json'
    try:
        report, png, inputs = evaluate(path)
        json_path, html_path = (args.out / ('report.' + ext) for ext in ('json', 'html'))
        if any(p.resolve() in inputs for p in (json_path, html_path)):
            raise AuditError('output would overwrite a manifest or input file')
        args.out.mkdir(parents=True, exist_ok=True)
        _replace(json_path, json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        _replace(html_path, render(report, png))
    except (AuditError, OSError, UnicodeError) as exc:
        print(f'residuetrace: {exc}', file=sys.stderr)
        return 2
    print(f'{"verified" if report["ok"] else "not verified"}: {json_path} | {html_path}')
    return 0 if report['ok'] else 1
