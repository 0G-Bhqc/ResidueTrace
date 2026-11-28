"""Presentation regressions: verdict, status counts, side-by-side identity evidence, expandable detail."""

from html.parser import HTMLParser

from residuetrace.audit import evaluate
from residuetrace.render import render

VOID = frozenset({'meta', 'link', 'br', 'hr', 'img', 'input'})


class Page(HTMLParser):
    """Start tags plus the visible text accumulated inside each identified element."""

    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.text = {}
        self.stack = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        named = dict(attrs)
        self.tags.append((tag, named))
        if tag not in VOID:
            self.stack.append((tag, named.get('id')))
        if named.get('id') and named['id'] not in self.text:
            self.text[named['id']] = []

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        for _, eid in self.stack:
            if eid in self.text:
                self.text[eid].append(data)

    def text_of(self, eid):
        return ''.join(self.text.get(eid, []))

    def balanced(self):
        return [tag for tag, _ in self.stack if tag not in VOID]


def showcase(bundle):
    report, png, _ = evaluate(bundle.save())
    return report, render(report, png)


def test_verified_bundle_shows_verdict_counts_and_side_by_side(bundle):
    report, html = showcase(bundle)
    page = Page(html)
    assert report['ok']
    verdict = page.text_of('verdict')
    assert 'Verified as a whole' in verdict and 'figure–table links agree' in verdict
    assert '<td>2</td>' in html  # region count and per-side resolution counts
    assert '<td class="diff">' not in html  # no mismatch markers on an agreeing bundle
    region = page.text_of('region-0')
    for label in ('Figure declaration', 'CSV table row', 'Model', 'Chain (auth)', 'Insertion code',
                  'Chain (label)', 'Residue no. (label)', 'Component'):
        assert label in region
    assert all(v in region for v in ('H', '77', 'A', 'B', '73', 'GLY'))  # resolved identity, both sides
    evidence = [attrs for tag, attrs in page.tags if tag == 'details' and not attrs]
    assert len(evidence) == 4  # one collapsed evidence block per region and CSV row
    assert any(tag == 'details' and attrs.get('class') == 'digests' and 'open' not in attrs
               for tag, attrs in page.tags)
    row = page.text_of('row-2')
    assert 'First atom-site row' in row and 'Observed atom rows' in row and 'GLY' in row


def test_report_stays_offline_accessible_and_balanced(bundle):
    _, html = showcase(bundle)
    page = Page(html)
    assert not page.balanced()
    assert not [t for t, _ in page.tags if t in ('script', 'iframe', 'object', 'embed')]
    anchors = [d for t, d in page.tags if t == 'a']
    assert all(d.get('href', '').startswith('#') for d in anchors)
    assert all(d.get('aria-label') for d in anchors if d['href'].startswith('#region-'))  # box links
    assert all(d['href'].startswith('#row-') for d in anchors if not d.get('aria-label'))  # text links to lines
    images = [d for t, d in page.tags if t == 'image']
    assert len(images) == 1 and images[0]['href'].startswith('data:image/png;base64')
    assert not any(key.lower().startswith('on') for _, d in page.tags for key in d)
    assert "default-src 'none'" in html


def test_conflict_marks_differing_identity_cells(bundle):
    bundle.regions[0]['claim']['ins_code'] = ''
    report, html = showcase(bundle)
    assert report['regions'][0]['status'] == 'conflict'
    assert '<span class="badge bad">conflict</span>' in html
    assert html.count('<td class="diff">') == 4  # insertion code and label residue rows, both sides marked
    page = Page(html)
    region = page.text_of('region-0')
    assert '(none)' in region and 'Cells marked' in region  # explicit empty vs declared insertion code
    verdict = page.text_of('verdict')
    assert 'Not verified as a whole' in verdict and 'conflict' in verdict and 'verified' in verdict


def test_insufficient_evidence_explains_itself(bundle):
    bundle.regions[0]['claim'].update(auth_seq_id='999', ins_code='')
    report, html = showcase(bundle)
    assert report['regions'][0]['status'] == 'unknown'
    region = Page(html).text_of('region-0')
    assert 'not an observed polymer residue' in region  # per-side explanation
    assert '999' in region  # declared claim value shown even though unresolved
    assert '<td class="diff">' not in html  # unresolved sides are never contrasted as identities
    assert '<span class="badge warn">unknown</span>' in html


def test_ambiguity_reports_candidate_count(bundle):
    bundle.replace('structure', bundle.file('structure').read_text()
                   + 'ATOM 7 C CA . GLY B 1 76 A 2 2 2 1 77 GLY H CA 1\n')
    report, html = showcase(bundle)
    assert report['regions'][0]['status'] == 'ambiguous'
    region = Page(html).text_of('region-0')
    assert 'matches 2 observed residues' in region
    assert '<td class="diff">' not in html


def test_bad_hash_withholds_figure_and_explains_the_halt(bundle):
    bundle.manifest['figure']['sha256'] = '0' * 64
    report, html = showcase(bundle)
    assert not report['ok'] and report['figure_size'] is None
    assert '<image' not in html and 'Figure withheld' in html
    assert '<span class="badge bad">hash_mismatch</span>' in html
    page = Page(html)
    assert '0' * 64 in page.text_of('integrity')  # declared digest shown in full
    assert 'bundle integrity failed' in page.text_of('region-0')
    verdict = page.text_of('verdict')
    assert 'Not verified as a whole' in verdict and 'no claims were interpreted' in verdict
    assert '<td class="diff">' not in html


def test_bundle_issues_surface_outside_per_region_verdicts(bundle):
    src = bundle.file('table').read_text()
    bundle.replace('table', src + src.splitlines()[1] + '\n')
    report, html = showcase(bundle)
    assert report['issues'] and not report['ok']
    page = Page(html)
    issues = page.text_of('issues')
    assert 'duplicate CSV row_key' in issues and 'k1' in issues
    assert '2 rows share this key' in page.text_of('region-0')
    assert '1 further bundle issue' in page.text_of('verdict')


def test_orphan_row_is_reported_in_bundle_issues(bundle):
    bundle.regions.pop()
    report, html = showcase(bundle)
    assert not report['ok']
    issues = Page(html).text_of('issues')
    assert 'row has no matching region' in issues and 'k2' in issues
    assert 'Verified' not in Page(html).text_of('verdict')  # lowercase 'verified' count still shown
