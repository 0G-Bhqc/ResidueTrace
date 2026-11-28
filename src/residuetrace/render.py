"""Script-free offline report. All user strings are rendered as escaped text."""

import base64
import json
from collections import Counter
from html import escape

from .audit import valid_rect


STYLE = """
:root{font:16px/1.55 system-ui,'Segoe UI',sans-serif;color:#1d2d35;background:#f5f5f0}
*{box-sizing:border-box}
body{max-width:70rem;margin:auto;padding:2rem 1rem 4rem}
h1,h2,h3,h4{line-height:1.25;margin:0 0 .4rem}
h1{font-size:1.6rem;letter-spacing:-.01em;margin:.15rem 0 .5rem}
h2{font-size:1.18rem;margin:2.1rem 0 .7rem;padding-bottom:.35rem;border-bottom:1px solid #ccd3ce}
h4{font-size:.92rem;color:#3d4f57;margin:.75rem 0 .15rem}
p{margin:.45rem 0}
header{border-top:5px solid #254d5c;padding-top:.9rem}
.eyebrow{font-size:.75rem;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:#5c6b70}
section,article{background:#fff;border:1px solid #ccd3ce;padding:1rem 1.15rem;margin:.9rem 0}
article{margin:.7rem 0}
article:target{outline:3px solid #416e99}
a{color:#184c77}
a:hover rect,a:focus rect{stroke:#1646ad;stroke-width:4}
a:focus-visible,summary:focus-visible{outline:3px solid #416e99;outline-offset:2px}
svg{display:block;width:100%;max-height:28rem}
rect{fill:transparent;stroke:#a34023;stroke-width:2;vector-effect:non-scaling-stroke}
rect.ok{stroke:#267357}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f0f2ed;padding:.7rem;margin:.4rem 0;font:13px/1.5 ui-monospace,Consolas,'Cascadia Mono',monospace}
code{font-family:ui-monospace,Consolas,'Cascadia Mono',monospace;font-size:.92em;overflow-wrap:anywhere}
strong{color:#85391e}
strong.ok{color:#1e654a}
table{border-collapse:collapse;width:100%;margin:.5rem 0;font-size:.93rem}
th,td{border:1px solid #d8ddd6;padding:.32rem .6rem;text-align:left;vertical-align:top}
thead th{background:#eef1ec}
tbody th{background:#f7f8f4;font-weight:600;color:#3d4f57;white-space:nowrap}
caption{caption-side:top;text-align:left;font-size:.85rem;color:#5c6b70;padding:0 0 .3rem}
.wrap{overflow-x:auto}
.compare td,.identity td{min-width:8rem}
.badge{display:inline-block;padding:.08rem .5rem;border:1px solid;border-radius:2px;font-size:.8rem;font-weight:600;letter-spacing:.02em;white-space:nowrap}
.badge.ok{color:#1e654a;border-color:#b9d4c6;background:#e9f2ec}
.badge.bad{color:#8f2f1d;border-color:#dcbfb2;background:#f6e9e3}
.badge.warn{color:#7a5510;border-color:#d8c697;background:#f6efdc}
.badge.mut{color:#52616a;border-color:#c4ccc8;background:#eef0eb}
td.diff{outline:2px solid #a34023;outline-offset:-2px;background:#f6e9e3;font-weight:600}
td.diff::before{content:'≠ ';color:#a34023}
.mut{color:#5c6b70}
.duo{display:grid;grid-template-columns:repeat(auto-fit,minmax(17rem,1fr));gap:1rem;align-items:start}
.duo table{margin:0}
.duo p{margin:.2rem 0}
details{margin-top:.6rem;border-top:1px dashed #ccd3ce;padding-top:.5rem}
summary{cursor:pointer;color:#184c77;font-weight:600}
.verdict{font-size:1.04rem;margin:.5rem 0 .8rem}
.hash{font-size:.78rem;color:#52616a}
#verdict{border:0;border-radius:.8rem;background:#122b32;color:#f1f7f4;padding:1.4rem 1.5rem}
#verdict h2{font-size:clamp(1.35rem,3vw,2rem);border:0;margin:.3rem 0}
#verdict .eyebrow,#verdict summary{color:#b9d9cf}#verdict strong{color:#ffc1ab}#verdict strong.ok{color:#8ce5c7}
#verdict .duo{color:#1d2d35;background:white;padding:.75rem;margin-top:.5rem}
.finding{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(13rem,100%),1fr));gap:.6rem;margin:.8rem 0}
.finding div{background:#203e46;padding:.75rem 1rem;border-radius:.4rem;min-width:0;overflow-wrap:anywhere}
.finding span,.finding small{display:block;color:#c6dcd9}.finding b{display:block;font:600 1.6rem/1.4 ui-monospace,Consolas,monospace;color:white}
#verdict summary:focus-visible{outline-color:#8ce5c7}.duo>*{min-width:0}
@media (max-width:40rem){body{padding:1.1rem .8rem 3rem}h1{font-size:1.3rem}.duo{grid-template-columns:minmax(0,1fr)}#verdict{padding:1rem}}

@media print{body{background:#fff;max-width:none}section,article{page-break-inside:avoid}}
"""


IDENTITY = (
    ('Model', 'model'),
    ('Chain (auth)', 'auth_asym_id'),
    ('Residue no. (auth)', 'auth_seq_id'),
    ('Insertion code', 'ins_code'),
    ('Chain (label)', 'label_asym_id'),
    ('Residue no. (label)', 'label_seq_id'),
    ('Component', 'label_comp_id'),
)
IDENTITY_KEYS = tuple(key for _, key in IDENTITY)
STATUS_ORDER = ('verified', 'conflict', 'hash_mismatch', 'ambiguous', 'unknown',
                'undeclared', 'duplicate', 'invalid_region', 'not_checked')
STATUS_INDEX = {s: i for i, s in enumerate(STATUS_ORDER)}
ISSUE_DETAIL = {'hash_mismatch': 'bytes differ from the declared digest',
                'undeclared': 'no digest was declared for this file'}


def text(value):
    return escape(str(value))


def dump(value):
    return '<pre>' + escape(json.dumps(value, ensure_ascii=False, indent=2)) + '</pre>'


def tone(status):
    if status in ('verified', 'matched', 'unique'):
        return 'ok'
    if status in ('conflict', 'hash_mismatch'):
        return 'bad'
    if status == 'not_checked':
        return 'mut'
    return 'warn'


def badge(status):
    return f'<span class="badge {tone(status)}">{text(status)}</span>'


def cell(value):
    """Identifier value in a cell: an em dash when absent, an explicit marker when empty."""
    if value is None:
        return '<span class="mut">&mdash;</span>'
    if value == '':
        return '<span class="mut">(none)</span>'
    return text(value)


def opt(value):
    return text(value) if value not in (None, '') else '<span class="mut">&mdash;</span>'


def identity_values(resolution):
    """Values per identity row: the resolved residue when unique, otherwise the declared claim."""
    claim = resolution.get('claim')
    claim = claim if isinstance(claim, dict) else {}
    candidates = resolution.get('candidates') or []
    resolved = resolution.get('status') == 'unique' and len(candidates) == 1
    source = candidates[0] if resolved else claim
    return {key: source.get(key) for key in IDENTITY_KEYS}, resolved


def side_note(status, count):
    return {
        'ambiguous': f'matches {count} observed residues, so no single identity is established',
        'unknown': 'declared residue is not an observed polymer residue of the pinned structure',
        'undeclared': 'claim is missing required identifier fields',
        'not_checked': 'not interpreted: bundle integrity failed',
    }.get(status, '')


def path_cell(value):
    return f'<code>{text(value)}</code>' if value else '<span class="mut">&mdash;</span>'


def hash_cell(value):
    return f'<code class="hash">{text(value)}</code>' if value else '<span class="mut">&mdash;</span>'


def status_count_table(counts):
    if not counts:
        return '<p class="mut">No figure regions are declared, so there is no per-region verdict to count.</p>'
    ordered = sorted(counts, key=lambda s: (STATUS_INDEX.get(s, len(STATUS_ORDER)), s))
    rows = ''.join(f'<tr><td>{badge(s)}</td><td>{counts[s]}</td></tr>' for s in ordered)
    return ('<table><caption>Declared figure regions by verdict</caption>'
            '<thead><tr><th scope="col">Status</th><th scope="col">Regions</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def side_count_table(report):
    pairs = Counter()
    for region in report['regions']:
        pairs[('figure side', region['evidence']['figure']['status'])] += 1
    for row in report['rows']:
        pairs[('table side', row['resolution']['status'])] += 1
    if not pairs:
        return '<p class="mut">No identifier claims were resolved on either side.</p>'
    ordered = sorted(pairs, key=lambda p: (p[0], STATUS_INDEX.get(p[1], len(STATUS_ORDER))))
    rows = ''.join(f'<tr><td>{text(side)}</td><td>{badge(status)}</td><td>{pairs[(side, status)]}</td></tr>'
                   for side, status in ordered)
    return ('<table><caption>Identifier resolutions by side</caption>'
            '<thead><tr><th scope="col">Side</th><th scope="col">Status</th><th scope="col">Claims</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


def conflict_preview(regions, rows_by_line):
    for r in regions:
        if r['status'] != 'conflict':
            continue
        figure, = r['evidence']['figure']['candidates']
        line, = r['evidence']['csv_lines']
        table, = rows_by_line[line]['resolution']['candidates']
        cards = []
        for side, candidate in (('Figure', figure), ('Table', table)):
            label = f'{candidate["label_asym_id"]}:{candidate["label_seq_id"]}'
            author = f'{candidate["auth_asym_id"]}:{candidate["auth_seq_id"]}{candidate["ins_code"]}'
            cards.append(f'<div><span>{side} resolves to</span><b>{text(label)} · {text(candidate["label_comp_id"])}</b>'
                         f'<small>Author {text(author)} · Model {text(candidate["model"])}</small></div>')
        return '<div class="finding">' + ''.join(cards) + '</div>'
    return ''


def verdict_section(report, rows_by_line):
    regions, issues = report['regions'], report['issues']
    counts = Counter(r['status'] for r in regions)
    file_issues = [i for i in issues if 'file' in i]
    n = len(regions)
    if report['ok']:
        lead = ('<strong class="ok">Verified as a whole:</strong> all '
                f'{n} declared figure&ndash;table links agree and every pinned file matched its digest.')
    else:
        frags = []
        if file_issues:
            frags.append('a pinned file failed its integrity binding, so no claims were interpreted')
        conflicts = counts['conflict']
        if conflicts:
            frags.append(f'{conflicts} confirmed residue mismatch' + ('es' if conflicts != 1 else ''))
        pending = n - counts['verified'] - conflicts
        if pending:
            frags.append(f'{pending} region link' + ('s' if pending != 1 else '') + ' could not be verified')
        rest = len(issues) - len(file_issues)
        if rest:
            frags.append(f'{rest} further bundle issue' + ('s' if rest != 1 else ''))
        lead = '<strong>Not verified as a whole:</strong> ' + '; '.join(frags) + '.'
    duo = f'<div class="duo">{status_count_table(counts)}{side_count_table(report)}</div>'
    headline = ('The figure and table point to different residues' if counts['conflict'] else
                'All figure–table links match' if report['ok'] else 'This bundle needs review')
    return (f'<section id="verdict"><p class="eyebrow">Audit result</p><h2>{headline}</h2>'
            f'<p class="verdict">{lead}</p>{conflict_preview(regions, rows_by_line)}'
            f'<details class="breakdown"><summary>Counts by status and source</summary>{duo}</details></section>')


def integrity_section(report):
    rows = []
    for role, f in report['files'].items():
        rows.append(f'<tr><th scope="row">{text(role)}</th>'
                    f'<td>{path_cell(f.get("path"))}</td>'
                    f'<td>{hash_cell(f.get("sha256"))}</td>'
                    f'<td>{hash_cell(f.get("actual_sha256"))}</td>'
                    f'<td>{badge(f["status"])}</td></tr>')
    blocked = any(f['status'] != 'matched' for f in report['files'].values())
    halt = ('<p class="mut">Claims are not interpreted while a pinned file fails its digest: the figure is '
            'withheld and each region reports the integrity failure instead.</p>') if blocked else ''
    table = ('<div class="wrap"><table><caption>Pinned archive files and their integrity binding</caption>'
             '<thead><tr><th scope="col">Role</th><th scope="col">Path</th><th scope="col">Declared sha256</th>'
             '<th scope="col">Actual sha256</th><th scope="col">Status</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div>')
    return (f'<section id="integrity"><h2>File integrity</h2>{halt}'
            f'<details class="digests"{" open" if blocked else ""}><summary>Inspect file hashes</summary>{table}</details></section>')


def figure_section(report, png):
    if not png:
        return '<section><h2>Declared selections</h2><p>Figure withheld: bundle integrity not established.</p></section>'
    w, h = report['figure_size']
    encoded = base64.b64encode(png).decode('ascii')
    parts = [f'<section><h2>Declared selections</h2><p>Select a box to inspect its claim and linked CSV lines.</p>'
             f'<svg viewBox="0 0 {w} {h}" aria-label="Declared figure selections">'
             f'<image width="{w}" height="{h}" href="data:image/png;base64,{encoded}"/>']
    for i, r in enumerate(report['regions']):
        if valid_rect(r['rect'], (w, h)):
            x, y, rw, rh = r['rect']
            cls = 'ok' if r['status'] == 'verified' else 'check'
            label = text(f'{r["id"]}: {r["status"]}')
            parts.append(f'<a href="#region-{i}" aria-label="{label}"><title>{label}</title>'
                         f'<rect class="{cls}" x="{x}" y="{y}" width="{rw}" height="{rh}"/></a>')
    parts.append(f'</svg><p class="mut">Pinned figure embedded at {w}&times;{h} pixels; '
                 'each box links to that region&rsquo;s evidence below.</p></section>')
    return ''.join(parts)


def compare_table(fig_side, tab_side, placeholder):
    fig_vals, fig_ok = identity_values(fig_side)
    if tab_side is None:
        tab_vals = dict.fromkeys(IDENTITY_KEYS)
        tab_ok = False
        tab_status_cell = f'<td><span class="mut">{text(placeholder or "no linked row")}</span></td>'
    else:
        tab_vals, tab_ok = identity_values(tab_side)
        tab_status_cell = f'<td>{badge(tab_side["status"])}</td>'
    contrast = fig_ok and tab_ok
    rows = [f'<tr><th scope="row">Resolution</th><td>{badge(fig_side["status"])}</td>{tab_status_cell}</tr>']
    for label, key in IDENTITY:
        a, b = fig_vals[key], tab_vals[key]
        mark = ' class="diff"' if contrast and a != b else ''
        rows.append(f'<tr><th scope="row">{text(label)}</th><td{mark}>{cell(a)}</td><td{mark}>{cell(b)}</td></tr>')
    notes = []
    fig_note = side_note(fig_side['status'], len(fig_side.get('candidates') or []))
    if fig_note:
        notes.append('Figure side: ' + fig_note)
    if tab_side is not None:
        tab_note = side_note(tab_side['status'], len(tab_side.get('candidates') or []))
        if tab_note:
            notes.append('CSV side: ' + tab_note)
    extra = f'<p class="mut">{"; ".join(notes)}.</p>' if notes else ''
    legend = ''
    if contrast and any(fig_vals[k] != tab_vals[k] for k in IDENTITY_KEYS):
        legend = '<p class="mut">Cells marked &ne; resolve to different residues on the two sides.</p>'
    table = ('<div class="wrap"><table class="compare">'
             '<thead><tr><th scope="col">Identity</th><th scope="col">Figure declaration</th>'
             '<th scope="col">CSV table row</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div>')
    return table + extra + legend


def region_article(report, index, rows_by_line):
    r = report['regions'][index]
    fig = r['evidence']['figure']
    lines = r['evidence']['csv_lines']
    linked = [rows_by_line[n] for n in lines if n in rows_by_line]
    links = ', '.join(f'<a href="#row-{n}">line {n}</a>' for n in lines) or 'no linked row'
    if len(linked) == 1:
        tab, placeholder, dup_note = linked[0]['resolution'], None, None
    elif linked:
        tab, placeholder, dup_note = None, f'{len(linked)} rows share this key', \
            'CSV side: several rows repeat the declared key, so no single identity is contrasted; each row appears in the evidence detail.'
    else:
        tab, placeholder, dup_note = None, 'no linked row', None
    parts = [f'<article id="region-{index}"><h3>{opt(r["id"])} {badge(r["status"])}</h3>',
             f'<p>Stable key <code>{opt(r["row_key"])}</code> &middot; CSV: {links}'
             f' &middot; Declared box <code>{cell(r["rect"])}</code></p>',
             compare_table(fig, tab, placeholder)]
    if dup_note:
        parts.append(f'<p class="mut">{dup_note}</p>')
    parts.append('<details><summary>Evidence detail</summary><h4>Figure-side resolution</h4>' + dump(fig))
    for row in linked:
        parts.append(f'<h4>CSV row at lines {row["line_start"]}&ndash;{row["line_end"]}</h4>'
                     + dump({'fields': row['fields'], 'resolution': row['resolution']}))
    parts.append('</details></article>')
    return ''.join(parts)


def row_article(row):
    start, end = row['line_start'], row['line_end']
    span = f'lines {start}&ndash;{end}' if end > start else f'line {start}'
    res = row['resolution']
    vals, resolved = identity_values(res)
    rows = [f'<tr><th scope="row">{text(label)}</th><td>{cell(vals[key])}</td></tr>' for label, key in IDENTITY]
    if resolved:
        cand = res['candidates'][0]
        rows.append(f'<tr><th scope="row">First atom-site row</th><td>{text(cand["first_atom_site_row"])}</td></tr>')
        rows.append(f'<tr><th scope="row">Observed atom rows</th><td>{text(cand["observed_atom_rows"])}</td></tr>')
    note = side_note(res['status'], len(res.get('candidates') or []))
    parts = [f'<article id="row-{start}"><h3>{opt(row["row_key"])} &mdash; {span} {badge(res["status"])}</h3>',
             '<div class="wrap"><table class="identity">'
             '<caption>Identity declared in this CSV row and the residue it resolves to in the pinned structure.</caption>'
             f'<tbody>{"".join(rows)}</tbody></table></div>']
    if note:
        parts.append(f'<p class="mut">{note}</p>')
    parts.append('<details><summary>Evidence detail</summary><h4>Raw CSV fields</h4>' + dump(row['fields'])
                 + '<h4>Resolution</h4>' + dump(res) + '</details></article>')
    return ''.join(parts)


def issues_section(report):
    issues = report['issues']
    if not issues:
        return ('<section id="issues"><h2>Bundle issues</h2><p>No bundle-level issues: file bindings, '
                'region bindings and CSV keys are consistent.</p></section>')
    rows = []
    for issue in issues:
        scope = issue.get('file') or issue.get('row_key')
        detail = issue.get('detail') or ISSUE_DETAIL.get(issue['status'], '')
        lines = ', '.join(str(n) for n in issue.get('csv_lines', []))
        rows.append(f'<tr><td>{badge(issue["status"])}</td><td>{opt(scope)}</td>'
                    f'<td>{opt(detail)}</td><td>{opt(lines)}</td></tr>')
    table = ('<div class="wrap"><table><caption>Findings outside the per-region verdicts</caption>'
             '<thead><tr><th scope="col">Status</th><th scope="col">Scope</th><th scope="col">Detail</th>'
             '<th scope="col">CSV lines</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div>')
    return (f'<section id="issues"><h2>Bundle issues</h2>{table}'
            f'<details><summary>Evidence detail</summary>{dump(issues)}</details></section>')


def render(report, png):
    rows_by_line = {row['line_start']: row for row in report['rows']}
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; base-uri \'none\'">',
             f'<title>ResidueTrace | Identifier audit</title><style>{STYLE}</style><body>',
             '<header><p class="eyebrow">ResidueTrace / offline evidence</p><h1>Identifier audit</h1>',
             f'<p>{text(report["description"])}</p>',
             '<p>Agreement of supplied identifiers only. Pixels do not identify a residue. A matching hash does not authenticate the declarant.</p></header>',
             verdict_section(report, rows_by_line),
             figure_section(report, png),
             '<h2>Region evidence</h2>']
    for i in range(len(report['regions'])):
        parts.append(region_article(report, i, rows_by_line))
    parts.append('<h2>CSV source rows</h2>')
    for row in report['rows']:
        parts.append(row_article(row))
    parts.append(integrity_section(report))
    parts.append(issues_section(report))
    parts.append('</body></html>')
    return '\n'.join(parts)
