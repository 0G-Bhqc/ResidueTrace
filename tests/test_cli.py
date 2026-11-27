import base64
import json
import subprocess
import sys
from html.parser import HTMLParser

from residuetrace.cli import main


class Markup(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.nodes = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))

    def attrs(self, tag):
        return [attrs for t, attrs in self.nodes if t == tag]


def test_clickable_embedded_figure_and_escaped_multiline_row(bundle, tmp_path):
    attack = '<b title="quoted">not markup & not code</b>'
    bundle.regions[0]['id'] = attack
    bundle.manifest['description'] = attack
    bundle.replace('table', 'row_key,model,label_asym_id,label_seq_id,note\nk1,1,B,73,"first line\n'
                   + attack.replace('"', '""') + '"\nk2,1,B,74,last\n')
    out = tmp_path / 'out'
    assert main(['audit', str(bundle.save()), '--out', str(out)]) == 0
    report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    assert report['rows'][0]['fields']['note'] == 'first line\n' + attack
    assert (report['rows'][0]['line_start'], report['rows'][0]['line_end']) == (2, 3)
    assert report['regions'][1]['evidence']['csv_lines'] == [4]
    html = (out / 'report.html').read_text(encoding='utf-8')
    assert attack not in html and '&lt;b title=&quot;quoted&quot;&gt;' in html
    dom = Markup(html)
    assert not dom.attrs('script') and not dom.attrs('b')
    image, = dom.attrs('image')
    prefix, data = image['href'].split(',')
    assert prefix == 'data:image/png;base64' and base64.b64decode(data) == bundle.file('figure').read_bytes()
    links = [a['href'] for a in dom.attrs('a')]
    assert links == ['#region-0', '#region-1', '#row-2', '#row-4']
    targets = {a['id'] for a in dom.attrs('article')}
    assert all(link[1:] in targets for link in links)
    assert dom.attrs('a')[0]['aria-label'] == attack + ': verified'
    assert dom.attrs('rect')[0]['x'] == '12'


def test_exit_codes_and_fail_closed_html(bundle, tmp_path):
    out = tmp_path / 'reports'
    bundle.manifest['figure']['sha256'] = '0' * 64
    assert main(['audit', str(bundle.save()), '--out', str(out)]) == 1
    html = (out / 'report.html').read_text(encoding='utf-8')
    assert not Markup(html).attrs('image') and 'hash_mismatch' in html
    bundle.path.write_text('{', encoding='utf-8')
    assert main(['audit', str(bundle.path), '--out', str(tmp_path / 'invalid')]) == 2
    assert not (tmp_path / 'invalid').exists()


def test_duplicate_json_keys_and_output_alias_rejected(bundle):
    path = bundle.dir / 'report.json'
    path.write_text(bundle.path.read_text(), encoding='utf-8')
    before = path.read_bytes()
    assert main(['audit', str(path), '--out', str(bundle.dir)]) == 2
    assert path.read_bytes() == before
    bundle.path.write_text('{"schema_version":1,"schema_version":1}', encoding='utf-8')
    assert main(['audit', str(bundle.path), '--out', str(bundle.dir)]) == 2


def test_installed_module_demo(tmp_path):
    p = subprocess.run([sys.executable, '-I', '-m', 'residuetrace', 'demo', '--out', str(tmp_path)],
                       capture_output=True, text=True, check=False)
    assert p.returncode == 0, p.stderr
    report = json.loads((tmp_path / 'report.json').read_text(encoding='utf-8'))
    assert report['ok'] and 'Not a 3B9F record' in report['description']
