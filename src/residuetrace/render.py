"""Script-free offline report. All user strings are rendered as escaped text."""

import base64
import json
from html import escape

from .audit import valid_rect


STYLE = """
:root{font:16px/1.5 system-ui,sans-serif;color:#192d35;background:#f7f7f1}body{max-width:68rem;margin:auto;padding:2rem 1rem}
h1,h2,h3{line-height:1.2}header{border-top:5px solid #254d5c}section,article{background:white;padding:1rem;margin:.8rem 0;border:1px solid #ccd3ce}
svg{display:block;width:100%;max-height:28rem}rect{fill:transparent;stroke:#a34023;stroke-width:2;vector-effect:non-scaling-stroke}rect.ok{stroke:#267357}
a:hover rect,a:focus rect{stroke:#1646ad;stroke-width:4}a{color:#184c77}article:target{outline:3px solid #416e99}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f0f2ed;padding:.7rem}strong{color:#85391e}strong.ok{color:#1e654a}
"""


def text(value):
    return escape(str(value))


def dump(value):
    return '<pre>' + escape(json.dumps(value, ensure_ascii=False, indent=2)) + '</pre>'


def render(report, png):
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; base-uri \'none\'">',
             f'<title>ResidueTrace | Identifier audit</title><style>{STYLE}</style><body>',
             '<header><p>RESIDUETRACE / OFFLINE EVIDENCE</p><h1>Identifier audit</h1>',
             '<strong class="ok">All declared links verified</strong>' if report['ok'] else '<strong>Not verified as a whole</strong>',
             f'<p>{text(report["description"])}</p></header>',
             '<p>Agreement of supplied identifiers only. Pixels do not identify a residue. A matching hash does not authenticate the declarant.</p>']
    if png:
        w, h = report['figure_size']
        encoded = base64.b64encode(png).decode('ascii')
        parts.append(f'<section><h2>Declared selections</h2><p>Select a box to inspect its claim and linked CSV lines.</p><svg viewBox="0 0 {w} {h}" aria-label="Declared figure selections"><image width="{w}" height="{h}" href="data:image/png;base64,{encoded}"/>')
        for i, r in enumerate(report['regions']):
            if valid_rect(r['rect'], (w, h)):
                x, y, rw, rh = r['rect']
                cls = 'ok' if r['status'] == 'verified' else 'check'
                label = text(f'{r["id"]}: {r["status"]}')
                parts.append(f'<a href="#region-{i}" aria-label="{label}"><title>{label}</title><rect class="{cls}" x="{x}" y="{y}" width="{rw}" height="{rh}"/></a>')
        parts.append('</svg></section>')
    else:
        parts.append('<p>Figure withheld: bundle integrity not established.</p>')
    parts.append('<h2>Region evidence</h2>')
    for i, r in enumerate(report['regions']):
        links = ', '.join(f'<a href="#row-{n}">line {n}</a>' for n in r['evidence']['csv_lines']) or 'no linked row'
        parts.append(f'<article id="region-{i}"><h3>{text(r["id"])} &mdash; {text(r["status"])}</h3>'
                     f'<p>Stable key <code>{text(r["row_key"])}</code> &middot; CSV: {links}</p>'
                     + dump({'rect': r['rect'], 'issues': r['issues'], **r['evidence']['figure']}) + '</article>')
    parts.append('<h2>CSV source rows</h2>')
    for row in report['rows']:
        start, end = row['line_start'], row['line_end']
        parts.append(f'<article id="row-{start}"><h3>{text(row["row_key"])} &mdash; lines {start}&ndash;{end}</h3>'
                     + dump({'fields': row['fields'], **row['resolution']}) + '</article>')
    parts.extend(['<h2>File integrity and bundle issues</h2>', dump(report['files']), dump(report['issues']), '</body></html>'])
    return '\n'.join(parts)
