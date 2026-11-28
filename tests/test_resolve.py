"""Real-archive and protocol tests for the headless `residuetrace resolve` verb."""

import argparse
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

import residuetrace
from residuetrace import resolve
from residuetrace.cli import main

REPO = Path(__file__).resolve().parents[1]
STRUCTURE = REPO / 'benchmark' / 'data' / '3b9f.cif'
DIGEST = hashlib.sha256(STRUCTURE.read_bytes()).hexdigest()
TEACHING = Path(residuetrace.__file__).with_name('demo') / 'teaching.cif'
TEACHING_DIGEST = hashlib.sha256(TEACHING.read_bytes()).hexdigest()
AUTH_77A = {"model": 1, "auth_asym_id": "H", "auth_seq_id": "77", "ins_code": "A"}
# Appended to the real 3B9F excerpt: same author address H:77A as row 1035, different label residue.
AMBIGUOUS_ROW = b'ATOM 2000 C CA . GLY B 2 76 A -1 -1 -1 1.00 20.00 ? 77 GLY H CA 1\n'


def line(obj):
    return json.dumps(obj, ensure_ascii=False)


def run(claims, sha=DIGEST, structure=STRUCTURE):
    raw = claims if isinstance(claims, (bytes, bytearray)) else claims.encode('utf-8')
    sink = io.BytesIO()
    code = resolve.run(argparse.Namespace(structure=Path(structure), sha256=sha),
                       instream=io.BytesIO(raw), out=sink)
    return code, [json.loads(l) for l in sink.getvalue().splitlines()]


def test_unique_auth_claim_with_insertion_code_on_real_3b9f():
    code, results = run(line(AUTH_77A))
    assert code == 0 and len(results) == 1
    r = results[0]
    assert r['line'] == 1 and r['status'] == 'unique' and r['structure_sha256'] == DIGEST
    assert r['claim'] == AUTH_77A
    c, = r['candidates']
    assert (c['model'], c['auth_asym_id'], c['auth_seq_id'], c['ins_code']) == (1, 'H', '77', 'A')
    assert (c['label_asym_id'], c['label_seq_id'], c['label_comp_id']) == ('B', 73, 'ARG')
    assert c['observed_atom_rows'] == 2  # alternate locations collapse into one observation


def test_multiple_inputs_keep_input_order_and_line_numbers():
    claims = [line(AUTH_77A),
              line({"model": 1, "auth_asym_id": "H", "auth_seq_id": "78", "ins_code": ""}),
              line({"model": 1, "label_asym_id": "B", "label_seq_id": 75}),
              line(AUTH_77A)]
    code, results = run('\n'.join(claims) + '\n')
    assert code == 0
    assert [r['line'] for r in results] == [1, 2, 3, 4]
    assert all(r['status'] == 'unique' for r in results)
    assert results[1]['candidates'][0]['label_seq_id'] == 74
    c, = results[2]['candidates']
    assert (c['auth_asym_id'], c['auth_seq_id'], c['label_seq_id']) == ('H', '79', 75)
    assert results[0]['candidates'] == results[3]['candidates']
    assert {r['structure_sha256'] for r in results} == {DIGEST}


def test_empty_insertion_is_not_a_wildcard_on_real_3b9f():
    code, results = run(line({"model": 1, "auth_asym_id": "H", "auth_seq_id": "77", "ins_code": ""}))
    assert code == 1
    assert results[0]['status'] == 'unknown' and results[0]['candidates'] == []


def test_teaching_example_distinguishes_insertion_and_model_scope():
    no_ins = {"model": 1, "auth_asym_id": "H", "auth_seq_id": "77", "ins_code": ""}
    code, results = run(line(no_ins), sha=TEACHING_DIGEST, structure=TEACHING)
    assert code == 0
    c, = results[0]['candidates']
    assert (c['label_asym_id'], c['label_seq_id'], c['label_comp_id']) == ('B', 74, 'GLY')
    code, results = run(line({"model": 2, "auth_asym_id": "H", "auth_seq_id": "77", "ins_code": "A"}),
                        sha=TEACHING_DIGEST, structure=TEACHING)
    assert code == 0
    c, = results[0]['candidates']
    assert c['model'] == 2  # the model-2 H:77A never answers a model-1 claim
    code, results = run(line({"model": 3, "auth_asym_id": "H", "auth_seq_id": "77", "ins_code": "A"}),
                        sha=TEACHING_DIGEST, structure=TEACHING)
    assert code == 1 and results[0]['status'] == 'unknown'


def test_unresolved_statuses_are_reported_honestly():
    claims = [line({"model": 1, "auth_asym_id": "H", "auth_seq_id": "78", "ins_code": ""}),   # unique
              line({"model": 1, "auth_asym_id": "H", "auth_seq_id": "999", "ins_code": ""}),  # unknown
              line({"auth_asym_id": "H"}),                                                    # undeclared
              line({"model": 1, "label_asym_id": "B"}),                                       # undeclared
              line({"model": 1, "auth_asym_id": "H", "auth_seq_id": "77", "ins_code": "A", "note": "x"})]  # undeclared
    code, results = run('\n'.join(claims) + '\n')
    assert code == 1
    assert [r['status'] for r in results] == ['unique', 'unknown', 'undeclared', 'undeclared', 'undeclared']
    candidate, = results[0]['candidates']
    assert (candidate['label_seq_id'], candidate['label_comp_id']) == (74, 'ASN')
    assert all(not row['candidates'] for row in results[1:])


def ambiguous(tmp_path):
    dest = tmp_path / 'ambiguous.cif'
    dest.write_bytes(STRUCTURE.read_bytes() + AMBIGUOUS_ROW)
    return dest, hashlib.sha256(dest.read_bytes()).hexdigest()


def test_ambiguity_in_both_directions(tmp_path):
    dest, digest = ambiguous(tmp_path)
    code, results = run(line(AUTH_77A), sha=digest, structure=dest)
    assert code == 1
    assert results[0]['status'] == 'ambiguous' and len(results[0]['candidates']) == 2
    assert {(c['label_seq_id'], c['label_comp_id']) for c in results[0]['candidates']} == {(73, 'ARG'), (76, 'GLY')}
    code, results = run(line({"model": 1, "label_asym_id": "B", "label_seq_id": 73}), sha=digest, structure=dest)
    assert code == 1
    assert results[0]['status'] == 'ambiguous' and len(results[0]['candidates']) == 2


def test_wrong_digest_is_refused_before_any_output(capsys):
    code, results = run(line(AUTH_77A), sha='0' * 64)
    assert code == 2 and results == []
    err = capsys.readouterr().err
    assert 'residuetrace:' in err and 'mismatch' in err and DIGEST in err


def test_malformed_digest_is_refused(capsys):
    code, results = run(line(AUTH_77A), sha=DIGEST[:63])
    assert code == 2 and results == []
    assert '64 hexadecimal' in capsys.readouterr().err


def test_uppercase_digest_is_accepted():
    code, results = run(line(AUTH_77A), sha=DIGEST.upper())
    assert code == 0 and results[0]['status'] == 'unique'


def test_empty_input_is_not_silent_success(capsys):
    code, results = run('')
    assert code == 2 and results == []
    assert 'empty input' in capsys.readouterr().err


@pytest.mark.parametrize('bad', [
    '{oops', '   ', '[1, 2]', '"claim"', 'null', '42',
    '{"model":1,"model":2,"auth_asym_id":"H","auth_seq_id":"77","ins_code":""}',
    '{"model":NaN,"auth_asym_id":"H","auth_seq_id":"77","ins_code":""}',
    '{"model":1e999,"auth_asym_id":"H","auth_seq_id":"77","ins_code":""}',
])
def test_bad_line_reports_context_after_streamed_prefix(capsys, bad):
    code, results = run(line(AUTH_77A) + '\n' + bad + '\n')
    assert code == 2
    assert len(results) == 1 and results[0]['line'] == 1  # the prefix already streamed; see docs/resolve.md
    err = capsys.readouterr().err
    assert 'line 2' in err and bad.strip() in err and 'residuetrace:' in err


def test_duplicate_json_field_is_named_in_context(capsys):
    code, results = run('{"model":1,"model":2}')
    assert code == 2 and results == []
    assert 'duplicate JSON field' in capsys.readouterr().err


def test_invalid_utf8_line_reports_context(capsys):
    code, results = run(b'{"model":1,"auth_asym_id":"\xff\xfe"}\n')
    assert code == 2 and results == []
    assert 'line 1' in capsys.readouterr().err


def test_reply_is_flushed_before_next_input_line_is_requested():
    sink = io.BytesIO()

    def requests():
        for number in (1, 2):
            yield (line(AUTH_77A) + '\n').encode('utf-8')
            replies = sink.getvalue().splitlines()
            assert len(replies) == number and json.loads(replies[-1])['line'] == number

    with io.BufferedWriter(sink) as out:
        code = resolve.run(argparse.Namespace(structure=STRUCTURE, sha256=DIGEST), requests(), out)
        assert code == 0


def test_structure_is_parsed_once_for_many_claims(monkeypatch):
    calls = []
    real = resolve.read_crosswalk

    def counting(data):
        calls.append(len(data))
        return real(data)

    monkeypatch.setattr(resolve, 'read_crosswalk', counting)
    code, results = run('\n'.join(line(AUTH_77A) for _ in range(5)) + '\n')
    assert code == 0 and len(results) == 5
    assert calls == [STRUCTURE.stat().st_size]


def test_missing_structure_file(capsys, tmp_path):
    code, results = run(line(AUTH_77A), structure=tmp_path / 'absent.cif')
    assert code == 2 and results == []
    assert capsys.readouterr().err


def test_unparsable_structure(capsys, tmp_path):
    dest = tmp_path / 'broken.cif'
    dest.write_bytes(b'not a cif at all')
    code, results = run(line(AUTH_77A), sha=hashlib.sha256(dest.read_bytes()).hexdigest(), structure=dest)
    assert code == 2 and results == []
    assert 'structure:' in capsys.readouterr().err


def test_cli_main_streams_utf8_ndjson_without_carriage_returns(monkeypatch):
    claims = line(AUTH_77A) + '\n' + line({"model": 1, "auth_asym_id": "H", "auth_seq_id": "999", "ins_code": ""}) + '\n'
    monkeypatch.setattr(sys, 'stdin', io.TextIOWrapper(io.BytesIO(claims.encode('utf-8')), encoding='utf-8'))
    buffer = io.BytesIO()
    monkeypatch.setattr(sys, 'stdout', io.TextIOWrapper(buffer, encoding='utf-8', newline='\n'))
    assert main(['resolve', str(STRUCTURE), '--sha256', DIGEST]) == 1
    raw = buffer.getvalue()
    assert b'\r' not in raw and raw.endswith(b'\n')
    rows = [json.loads(l) for l in raw.decode('utf-8').splitlines()]
    assert [r['status'] for r in rows] == ['unique', 'unknown'] and rows[1]['line'] == 2


def test_missing_sha256_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        main(['resolve', str(STRUCTURE)])
    assert exc.value.code == 2


def test_subprocess_stdin_stdout_all_unique():
    claims = '\n'.join([line(AUTH_77A), line({"model": 1, "auth_asym_id": "H", "auth_seq_id": "78", "ins_code": ""})])
    p = subprocess.run([sys.executable, '-I', '-m', 'residuetrace', 'resolve', str(STRUCTURE), '--sha256', DIGEST],
                       input=claims.encode('utf-8'), capture_output=True, check=False)
    assert p.returncode == 0, p.stderr
    assert p.stderr == b'' and b'\r' not in p.stdout
    rows = [json.loads(l) for l in p.stdout.decode('utf-8').splitlines()]
    assert [r['status'] for r in rows] == ['unique', 'unique'] and rows[1]['line'] == 2


def test_subprocess_wrong_hash_exits_two_without_stdout():
    p = subprocess.run([sys.executable, '-I', '-m', 'residuetrace', 'resolve', str(STRUCTURE), '--sha256', '0' * 64],
                       input=line(AUTH_77A).encode('utf-8'), capture_output=True, check=False)
    assert p.returncode == 2 and p.stdout == b'' and b'mismatch' in p.stderr


def test_subprocess_non_ascii_claim_round_trips_as_utf8():
    claim = {"model": 1, "auth_asym_id": "Ω", "auth_seq_id": "77", "ins_code": ""}
    p = subprocess.run([sys.executable, '-I', '-m', 'residuetrace', 'resolve', str(STRUCTURE), '--sha256', DIGEST],
                       input=line(claim).encode('utf-8'), capture_output=True, check=False)
    assert p.returncode == 1, p.stderr
    row, = [json.loads(l) for l in p.stdout.decode('utf-8').splitlines()]
    assert row['status'] == 'unknown' and row['claim']['auth_asym_id'] == 'Ω'


def test_bom_and_crlf_inputs_are_tolerated():
    code, results = run('\ufeff' + line(AUTH_77A) + '\n')
    assert code == 0 and results[0]['line'] == 1
    code, results = run(line(AUTH_77A) + '\r\n')
    assert code == 0 and results[0]['status'] == 'unique'
