"""Independent offline budget/source/data-boundary checks, not a quality score."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess

MODELS = ('gemini-3.8-flash', 'gemini-3.6-flash')
HEADERS = {'retry-after', 'x-request-id', 'x-goog-request-id', 'x-correlation-id', 'date', 'content-type'}
PROMPT = b'Return exactly READY as a synthetic connectivity check without tools.'


def verify(receipt, source_hashes):
    # Assertions are acceptance gates here, not optional debug checks.
    # Python -O strips them; reject that runtime instead of silently passing.
    if not __debug__:
        raise RuntimeError('RECEIPT_VALIDATION_DISABLED_BY_OPTIMIZATION')
    assert receipt['kind'] == 'provider-readiness-diagnostic'
    assert receipt['source_sha256'] == source_hashes
    assert receipt['admission']['prompt_sha256'] == hashlib.sha256(PROMPT).hexdigest()
    assert receipt['admission']['classification'] == 'PUBLIC_RELEASE_APPROVED'
    assert receipt['limits']['paid_fallback'] is False
    attempts = receipt['attempts']
    assert len(attempts) == receipt['total_generation_attempts'] <= 3
    counts = Counter(row['requested_model'] for row in attempts)
    assert set(counts) <= set(MODELS)
    assert counts[MODELS[0]] <= 2 and counts[MODELS[1]] <= 1
    if attempts:
        assert attempts[0]['requested_model'] == MODELS[0]
    for index, row in enumerate(attempts):
        assert row['api_version'] == 'v1beta' and row['operation'] == 'generateContent'
        assert row['endpoint'] == f"https://generativelanguage.googleapis.com/v1beta/models/{row['requested_model']}:generateContent"
        assert row['agy_executed'] is False and row['tools'] == 'none'
        assert set(row['response_headers']) <= HEADERS
        assert set(row['error']) == {'code', 'status', 'message'}
        assert all(value is None or len(str(value)) <= 530 for value in row['error'].values())
        assert row['elapsed_ms'] >= 0
        assert not row['classification'].startswith('transport-') or row['http_received'] is False
        assert row['http_status'] != 503 or row['classification'] == 'http-service-unavailable'
        if index + 1 < len(attempts):
            assert row['http_status'] in (429, 503, 404)
            assert row['billing_signal'] is False
            assert row['next_step']['action'] != 'stop'
            delay = row['next_step']['wait_seconds']
            assert 0 <= delay <= 30
            following = attempts[index + 1]
            expected = MODELS[0] if row['next_step']['action'] == 'retry-first' else MODELS[1]
            assert following['requested_model'] == expected
            gap = (datetime.fromisoformat(following['utc']) - datetime.fromisoformat(row['utc'])).total_seconds() - following['elapsed_ms'] / 1000
            assert gap >= delay - .1
        if row['classification'] == 'direct-synthetic-success':
            assert row['http_status'] == 200 and row['synthetic_check_passed'] is True
            assert index == len(attempts) - 1
    encoded = json.dumps(receipt)
    assert not re.search(r'(?i)(?:AIza[\w-]{25,}|Bearer\s+[A-Za-z0-9_-]+|[A-Z]:\\\\Users\\\\|[?&]key=)', encoded)
    assert receipt['agy']['state'] == 'NOT_EXECUTED'
    return {'verdict': 'PASS', 'generation_attempts': len(attempts), 'source_binding': 'PASS', 'budget_and_order': 'PASS', 'receipt_boundary': 'PASS', 'provider_cause': 'not independently proven', 'model_skill': 'not evaluated'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receipt', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    receipt = json.loads(args.receipt.read_text(encoding='utf-8-sig'))
    commit = receipt['source_commit']
    assert re.fullmatch('[0-9a-f]{40}', commit)
    source_hashes = {}
    for name, filename in (('module', 'GeminiReadiness.psm1'), ('entry', 'Invoke-GeminiReadiness.ps1')):
        raw = subprocess.check_output(['git', 'show', f'{commit}:qualification/diagnostics/{filename}'])
        source_hashes[name] = hashlib.sha256(raw).hexdigest()
    verdict = verify(receipt, source_hashes)
    # Negative controls prove the independent budget/binding guards reject.
    changed = json.loads(json.dumps(receipt))
    changed['total_generation_attempts'] = 4
    try:
        verify(changed, source_hashes)
    except AssertionError:
        verdict['over_budget_negative_control'] = 'REJECTED'
    else:
        raise AssertionError('Budget negative control falsely accepted')
    changed = json.loads(json.dumps(receipt))
    changed['source_sha256']['module'] = '0' * 64
    try:
        verify(changed, source_hashes)
    except AssertionError:
        verdict['source_mismatch_negative_control'] = 'REJECTED'
    else:
        raise AssertionError('Source negative control falsely accepted')
    text = json.dumps(verdict, indent=2) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')


if __name__ == '__main__':
    main()
