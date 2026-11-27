"""Strict verdict for the fixed two-request public synthetic Qwen fixture."""
import unittest


def exact_int(row, key, expected):
    value = row.get(key)
    return type(value) is int and value == expected


def fixture_pass(rows):
    if not isinstance(rows, list) or len(rows) != 2:
        return False
    for row, mode in zip(rows, ('off', 'on')):
        if not isinstance(row, dict) or row.get('mode') != mode or 'error' in row:
            return False
        if not all(exact_int(row, k, n) for k, n in (
            ('cli_exit', 0), ('requests', 2), ('tool_result_marker_records', 1),
            ('tool_result_id_matches', 1))):
            return False
        if not all(row.get(k) is True for k in ('tool_requested', 'tool_result_seen',
                                               'final_marker_seen', 'config_unchanged')):
            return False
        if row.get('payload_marker_seen') is not False:
            return False
        ids, counts = row.get('identity_coverage'), row.get('known_event_counts')
        if not isinstance(ids, dict) or not isinstance(counts, dict):
            return False
        active = mode == 'on'
        pairs, tools = (2, 1) if active else (0, 0)
        if not all(exact_int(ids, k, n) for k, n in (
            ('unique_api_id_pairs', pairs), ('unmatched_api_id_keys', 0),
            ('ambiguous_api_id_keys', 0), ('api_requests_missing_identity', 0),
            ('api_responses_missing_identity', 0), ('tool_records', tools),
            ('tool_records_missing_call_id', 0), ('expected_successful_tool_id_records', tools))):
            return False
        if ids.get('unique_expected_tool_record') is not active:
            return False
        if not all(exact_int(counts, k, n) for k, n in (
            ('qwen-code.api_request', pairs), ('qwen-code.api_response', pairs),
            ('qwen-code.tool_call', tools), ('qwen-code.api_error', 0), ('qwen-code.api_cancel', 0))):
            return False
        record_fields = ('records', 'bytes', 'other_event_records', 'unclassified_records')
        if any(type(row.get(k)) is not int or row[k] < 0 for k in record_fields):
            return False
        if any(type(v) is not int or v < 0 for v in counts.values()):
            return False
        if row['records'] != sum(counts.values()) + row['other_event_records'] + row['unclassified_records']:
            return False
        if active:
            if row['records'] <= 0 or row['bytes'] <= 0:
                return False
        elif row['records'] != 0 or row['bytes'] != 0:
            return False
    return True


def fixture_rows():
    rows = []
    for mode in ('off', 'on'):
        active = mode == 'on'
        pairs, tools = (2, 1) if active else (0, 0)
        rows.append(dict(mode=mode, cli_exit=0, requests=2, tool_result_marker_records=1,
            tool_result_id_matches=1, tool_requested=True, tool_result_seen=True,
            final_marker_seen=True, config_unchanged=True, payload_marker_seen=False,
            records=5 if active else 0, bytes=100 if active else 0, other_event_records=0,
            unclassified_records=0, known_event_counts={'qwen-code.api_request': pairs,
            'qwen-code.api_response': pairs, 'qwen-code.tool_call': tools,
            'qwen-code.api_error': 0, 'qwen-code.api_cancel': 0}, identity_coverage=dict(
            unique_api_id_pairs=pairs, unmatched_api_id_keys=0, ambiguous_api_id_keys=0,
            api_requests_missing_identity=0, api_responses_missing_identity=0,
            tool_records=tools, tool_records_missing_call_id=0,
            expected_successful_tool_id_records=tools, unique_expected_tool_record=active)))
    return rows


class VerdictTests(unittest.TestCase):
    def test_positive_and_order(self):
        rows = fixture_rows()
        self.assertTrue(fixture_pass(rows))
        for bad in (rows[::-1], rows[:1], rows + rows[:1], None, [None, rows[1]]):
            self.assertFalse(fixture_pass(bad))

    def test_external_witness_mutations_both_arms(self):
        for i in (0, 1):
            for key, value in (('tool_result_id_matches', 0), ('tool_result_id_matches', True),
                ('tool_result_marker_records', 2), ('requests', 3), ('cli_exit', False),
                ('tool_requested', 1), ('final_marker_seen', False), ('config_unchanged', None),
                ('payload_marker_seen', True), ('records', -1), ('bytes', True)):
                with self.subTest(arm=i, key=key, value=value):
                    rows = fixture_rows()
                    rows[i][key] = value
                    self.assertFalse(fixture_pass(rows))

    def test_native_identity_mutations(self):
        for key, value in (('unique_api_id_pairs', 1), ('unique_api_id_pairs', True),
            ('unmatched_api_id_keys', 1), ('ambiguous_api_id_keys', 1),
            ('api_requests_missing_identity', 1), ('api_responses_missing_identity', 1),
            ('tool_records', 2), ('tool_records_missing_call_id', 1),
            ('expected_successful_tool_id_records', 0), ('unique_expected_tool_record', 1)):
            with self.subTest(key=key, value=value):
                rows = fixture_rows()
                rows[1]['identity_coverage'][key] = value
                self.assertFalse(fixture_pass(rows))
        for section, key in (('identity_coverage', 'unique_api_id_pairs'),
                             ('known_event_counts', 'qwen-code.api_response')):
            rows = fixture_rows()
            del rows[1][section][key]
            self.assertFalse(fixture_pass(rows))

    def test_capture_accounting_and_off_refusal(self):
        for arm, section, key, value in ((0, None, 'bytes', 1), (0, None, 'records', 1),
            (1, None, 'records', 6), (1, 'known_event_counts', 'qwen-code.api_error', 1),
            (1, 'known_event_counts', 'qwen-code.api_request', 3),
            (0, 'identity_coverage', 'tool_records', 1)):
            rows = fixture_rows()
            target = rows[arm][section] if section else rows[arm]
            target[key] = value
            self.assertFalse(fixture_pass(rows))
        rows = fixture_rows()
        rows[1]['other_event_records'] = 1
        rows[1]['records'] += 1
        self.assertTrue(fixture_pass(rows))


if __name__ == '__main__':
    unittest.main(verbosity=2)
