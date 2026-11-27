import gzip
import hashlib
import json

import pytest

from residuetrace import AuditError


def rejected(report, expected, region=0):
    assert report['ok'] is False
    assert report['regions'][region]['status'] == expected


def test_synthetic_crosswalk_and_provenance(bundle):
    report = bundle.run()
    assert json.loads(json.dumps(report)) == report
    assert report['schema_version'] == 1 and report['ok'] and not report['issues']
    assert [r['status'] for r in report['regions']] == ['verified'] * 2
    c, = report['regions'][0]['evidence']['figure']['candidates']
    assert c == dict(model=1, auth_asym_id='H', auth_seq_id='77', ins_code='A', label_asym_id='B',
                     label_seq_id=73, label_comp_id='GLY', label_entity_id='1', first_atom_site_row=1, observed_atom_rows=2)
    assert report['regions'][0]['evidence']['csv_lines'] == [2]
    assert report['rows'][0]['fields']['row_key'] == 'k1'
    assert report['rows'][0]['resolution']['candidates'] == [c]
    assert all(f['sha256'] == f['actual_sha256'] for f in report['files'].values())


def archive_structure(bundle, data):
    bundle.manifest['structure']['path'] = 'archive.cif.gz'
    bundle.file('structure').write_bytes(data)
    bundle.manifest['structure']['sha256'] = hashlib.sha256(data).hexdigest()


def test_gzip_archive_preserves_evidence_and_pins_archive_bytes(bundle):
    before = bundle.run()
    plain = bundle.file('structure').read_bytes()
    archive_structure(bundle, gzip.compress(plain, mtime=0))
    after = bundle.run()
    assert after['ok'] and after['regions'] == before['regions'] and after['rows'] == before['rows']
    assert after['files']['structure']['actual_sha256'] != before['files']['structure']['actual_sha256']
    bundle.manifest['structure']['sha256'] = before['files']['structure']['sha256']
    rejected(bundle.run(), 'hash_mismatch')


def test_truncated_gzip_does_not_yield_partial_evidence(bundle):
    archive_structure(bundle, gzip.compress(bundle.file('structure').read_bytes(), mtime=0)[:-4])
    with pytest.raises(AuditError, match='incomplete gzip'):
        bundle.run()


def test_gzip_expanded_size_boundary(bundle, monkeypatch):
    from residuetrace import structure
    plain = bundle.file('structure').read_bytes()
    archive_structure(bundle, gzip.compress(plain, mtime=0))
    monkeypatch.setattr(structure, 'MAX_EXPANDED_CIF_BYTES', len(plain))
    assert bundle.run()['ok']
    monkeypatch.setattr(structure, 'MAX_EXPANDED_CIF_BYTES', len(plain) - 1)
    with pytest.raises(AuditError, match='size limit'):
        bundle.run()


@pytest.mark.parametrize('edit', [{'ins_code': ''}, {'model': 2}])
def test_legitimate_conflict_insertion_or_model(bundle, edit):
    bundle.regions[0]['claim'].update(edit)
    report = bundle.run()
    rejected(report, 'conflict')
    assert report['regions'][0]['evidence']['figure']['status'] == report['rows'][0]['resolution']['status'] == 'unique'


@pytest.mark.parametrize('seq', ['9', '90', '999'])  # water, occupancy zero, absent
def test_unknown_unobserved_or_nonpolymer(bundle, seq):
    bundle.regions[0]['claim'].update(auth_seq_id=seq, ins_code='')
    rejected(bundle.run(), 'unknown')


@pytest.mark.parametrize('field', ['model', 'ins_code', 'auth_seq_id'])
def test_auth_claim_cannot_guess_omissions(bundle, field):
    del bundle.regions[0]['claim'][field]
    rejected(bundle.run(), 'undeclared')


def test_csv_with_no_claim_cannot_verify(bundle):
    bundle.replace('table', 'row_key,note\nk1,known-looking key\nk2,ditto\n')
    rejected(bundle.run(), 'undeclared')


def test_reverse_namespace_csv_and_explicit_empty_insertion(bundle):
    for i, region in enumerate(bundle.regions):
        region['claim'] = {'model': 1, 'label_asym_id': 'B', 'label_seq_id': 73 + i}
    bundle.replace('table', 'row_key,model,auth_asym_id,auth_seq_id,ins_code\nk1,1,H,77,A\nk2,1,H,77,\n')
    assert bundle.run()['ok']


@pytest.mark.parametrize('role', ['structure', 'figure', 'table'])
def test_changed_bytes_block_entire_bundle_before_parsing(bundle, role):
    bundle.file(role).write_bytes(b'no longer the pinned bytes')
    report = bundle.run()
    rejected(report, 'hash_mismatch')
    assert set(r['status'] for r in report['regions']) == {'hash_mismatch'}
    assert report['regions'][0]['evidence']['figure']['status'] == 'not_checked'
    assert report['figure_size'] is None and report['rows'] == []


def test_missing_hash_is_not_trust_on_first_use(bundle):
    del bundle.manifest['figure']['sha256']
    rejected(bundle.run(), 'undeclared')


def test_reordering_changes_line_evidence_not_verdict(bundle):
    header, first, second = bundle.file('table').read_text().splitlines()
    before = bundle.run()
    bundle.replace('table', '\n'.join([header, second, first]))
    after = bundle.run()
    assert before['ok'] and after['ok']
    for old, new in zip(before['regions'], after['regions']):
        assert (old['row_key'], old['status'], old['evidence']['figure']) == (new['row_key'], new['status'], new['evidence']['figure'])
        assert old['evidence']['csv_lines'] != new['evidence']['csv_lines']
    assert after['regions'][0]['evidence']['csv_lines'] == [3]


def test_duplicate_csv_key_preserves_both_rows(bundle):
    src = bundle.file('table').read_text()
    bundle.replace('table', src + src.splitlines()[1] + '\n')
    report = bundle.run()
    rejected(report, 'duplicate')
    assert report['regions'][0]['evidence']['csv_lines'] == [2, 4]
    assert report['issues'][0]['csv_lines'] == [2, 4]


@pytest.mark.parametrize('field', ['id', 'rect', 'row_key'])
def test_duplicate_region_bindings(bundle, field):
    bundle.regions[1][field] = bundle.regions[0][field]
    report = bundle.run()
    for i in (0, 1):
        rejected(report, 'duplicate', i)


@pytest.mark.parametrize('rect', [[0, 0, 0, 1], [-1, 5, 10, 10], [210, 20, 7, 1], [True, 0, 1, 1]])
def test_rectangles_fail_closed(bundle, rect):
    bundle.regions[0]['rect'] = rect
    rejected(bundle.run(), 'invalid_region')


def test_empty_manifest_or_orphan_does_not_greenlight(bundle):
    bundle.regions.pop()
    report = bundle.run()
    assert not report['ok'] and report['regions'][0]['status'] == 'verified'
    assert report['issues'][0]['row_key'] == 'k2'
    bundle.regions.clear()
    assert not bundle.run()['ok']


def test_missing_key_does_not_fall_back_to_position(bundle):
    bundle.regions[0]['row_key'] = 'unknown-key'
    rejected(bundle.run(), 'unknown')


@pytest.mark.parametrize('site', [
    'ATOM 7 C CA . GLY B 1 76 A 2 2 2 1 77 GLY H CA 1',  # same auth, different label
    'ATOM 7 C CA . GLY B 1 73 A 2 2 2 1 78 GLY H CA 1',  # same label, different auth
    'ATOM 7 C CA B ALA B 1 73 A 2 2 2 1 77 ALA H CA 1',  # same IDs, different component
])
def test_ambiguity_in_either_direction(bundle, site):
    bundle.replace('structure', bundle.file('structure').read_text() + site + '\n')
    report = bundle.run()
    rejected(report, 'ambiguous')
    assert len(report['regions'][0]['evidence']['figure']['candidates']) == 2


def test_duplicate_csv_columns_are_not_silently_overwritten(bundle):
    bundle.replace('table', 'row_key,row_key,model,label_asym_id,label_seq_id\na,k1,1,B,73\n')
    with pytest.raises(AuditError, match='header'):
        bundle.run()


def test_missing_model_column_is_not_implicitly_model_one(bundle):
    bundle.replace('structure', bundle.file('structure').read_text().replace('_atom_site.pdbx_PDB_model_num', '_atom_site.other'))
    with pytest.raises(AuditError, match='structure'):
        bundle.run()


@pytest.mark.parametrize('contents', ['', '# a comment only', 'data_one\n_entry.id one\ndata_two\n_entry.id two'])
def test_structure_must_have_exactly_one_block(bundle, contents):
    bundle.replace('structure', contents)
    with pytest.raises(AuditError, match='one data block'):
        bundle.run()


def test_relative_artifact_cannot_escape_manifest_directory(bundle):
    bundle.manifest['table']['path'] = '../elsewhere.csv'
    with pytest.raises(AuditError, match='inside the manifest directory'):
        bundle.run()
