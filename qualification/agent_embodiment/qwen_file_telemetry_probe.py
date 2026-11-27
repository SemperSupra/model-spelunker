#!/usr/bin/env python3
"""Public synthetic local-file telemetry smoke for pinned Qwen Code.
No real model, private inputs, remote collector, or application deployment.
Only the allowlisted summary may leave the disposable runner.
"""
import argparse
import hashlib
import http.server
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request

from telemetry_capture import CAP, inspect_telemetry
from telemetry_verdict import fixture_pass
from file_access_witness import FileAccessWitness, witness_pass


def make_handler(fixture, file_marker, answer, seen, call_id='call_fixture', witness=None):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == '/v1/models':
                self.reply({'object': 'list', 'data': [{'id': 'qwen3:1.7b', 'object': 'model', 'owned_by': 'fixture'}]})
            else:
                self.send_error(404)

        def reply(self, value):
            raw = json.dumps(value).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            if self.path != '/v1/chat/completions':
                self.send_error(404)
                return
            n = int(self.headers.get('Content-Length', '0'))
            if not 0 < n <= CAP:
                self.send_error(413)
                return
            body = json.loads(self.rfile.read(n))
            messages = body.get('messages', [])
            matching = [m for m in messages if isinstance(m, dict) and m.get('role') == 'tool'
                        and file_marker in json.dumps(m.get('content'))]
            tool_result = bool(matching)
            seen['tool_result_marker_records'] += len(matching)
            if seen['tool_requested']:
                seen['tool_result_id_matches'] += sum(m.get('tool_call_id') == call_id for m in matching)
            tool_exists = any(isinstance(t, dict) and t.get('function', {}).get('name') == 'read_file'
                              for t in (body.get('tools') or []))
            seen['requests'] += 1
            if tool_result:
                if witness is not None and seen['tool_requested'] and any(m.get('tool_call_id') == call_id for m in matching):
                    witness.at_result()
                seen['tool_result_seen'] = True
                message, reason = {'role': 'assistant', 'content': answer}, 'stop'
            elif tool_exists:
                if witness is not None:
                    witness.before_issue()
                seen['tool_requested'] = True
                message = {'role': 'assistant', 'content': None, 'tool_calls': [{
                    'id': call_id, 'type': 'function', 'function': {
                        'name': 'read_file', 'arguments': json.dumps({'file_path': str(fixture)})}}]}
                reason = 'tool_calls'
            else:
                message, reason = {'role': 'assistant', 'content': 'synthetic auxiliary response'}, 'stop'
            base = {'id': 'chatcmpl-fixture', 'created': 1, 'model': 'qwen3:1.7b'}
            if not body.get('stream'):
                self.reply(dict(base, object='chat.completion', choices=[{'index': 0, 'message': message,
                    'finish_reason': reason}], usage={'prompt_tokens': 20, 'completion_tokens': 5, 'total_tokens': 25}))
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            delta = dict(message)
            if 'tool_calls' in delta:
                delta['tool_calls'][0]['index'] = 0
            for choice in ({'index': 0, 'delta': delta, 'finish_reason': None},
                           {'index': 0, 'delta': {}, 'finish_reason': reason}):
                event = dict(base, object='chat.completion.chunk', choices=[choice])
                self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
    return Handler


def trial(binary, root, enabled):
    from qwen_embody import load_profile, settings
    root.mkdir(mode=0o700)
    home, task = root / 'home', root / 'task'
    (home / '.qwen').mkdir(parents=True)
    task.mkdir()
    markers = [secrets.token_hex(20) for _ in range(4)]
    prompt_marker, file_marker, dummy_key, answer = markers
    fixture = task / 'fixture.txt'
    fixture.write_text(file_marker + '\n')
    telemetry = root / 'telemetry.json'
    seen = dict(requests=0, tool_requested=False, tool_result_seen=False,
                tool_result_marker_records=0, tool_result_id_matches=0)
    call_id = 'call_' + secrets.token_hex(16)
    with FileAccessWitness(fixture) as witness, http.server.ThreadingHTTPServer(
            ('127.0.0.1', 0), make_handler(fixture, file_marker, answer, seen, call_id, witness)) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            cfg = settings(load_profile())
            cfg['modelProviders']['openai'][0]['baseUrl'] = f'http://127.0.0.1:{server.server_port}/v1'
            cfg['telemetry'] = dict(enabled=enabled, outfile=str(telemetry), logPrompts=False,
                                    includeSensitiveSpanAttributes=False)
            config_file = home / '.qwen' / 'settings.json'
            config_file.write_text(json.dumps(cfg))
            before = hashlib.sha256(config_file.read_bytes()).hexdigest()
            env = dict(HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'), XDG_CACHE_HOME=str(home / '.cache'),
                       XDG_DATA_HOME=str(home / '.local/share'), TMPDIR=str(root), PATH=os.defpath,
                       CI='true', LANG='C.UTF-8', OLLAMA_API_KEY=dummy_key,
                       QWEN_TELEMETRY_ENABLED='true' if enabled else 'false',
                       QWEN_TELEMETRY_OUTFILE=str(telemetry), QWEN_TELEMETRY_LOG_PROMPTS='false',
                       QWEN_TELEMETRY_INCLUDE_SENSITIVE_SPAN_ATTRIBUTES='false')
            command = ['prlimit', f'--fsize={CAP}', '--', 'timeout', '-k', '5s', '90s', str(binary),
                       '--prompt', 'Use read_file to read fixture.txt. Marker: ' + prompt_marker,
                       '--model', 'qwen3:1.7b', '--core-tools', 'read_file', '--approval-mode', 'default',
                       '--max-session-turns', '4', '--max-tool-calls', '4', '--max-wall-time', '75s',
                       '--output-format', 'json']
            start = time.monotonic()
            with (root / 'stdout').open('wb') as out, (root / 'stderr').open('wb') as err:
                result = subprocess.run(command, cwd=task, env=env, stdout=out, stderr=err, timeout=110)
            elapsed = round(time.monotonic() - start, 3)
            stats = inspect_telemetry(telemetry, (prompt_marker, file_marker, dummy_key, answer), call_id)
            # Never print or retain raw stdout/stderr, fixture contents or telemetry.
            output = (root / 'stdout').read_bytes()
            return dict(mode='on' if enabled else 'off', cli_exit=result.returncode, seconds=elapsed,
                        **seen, final_marker_seen=answer.encode() in output,
                        file_access_witness=witness.summary(),
                        config_unchanged=before == hashlib.sha256(config_file.read_bytes()).hexdigest(),
                        **stats)
        finally:
            server.shutdown()
            worker.join(5)


def loopback_only(raw):
    # ip queries rtnetlink in the calling process's network namespace; a sysfs
    # mount inherited from the outer namespace can expose the wrong inventory.
    try:
        links = json.loads(raw)
    except (ValueError, TypeError):
        return False
    if not isinstance(links, list) or len(links) != 1 or not isinstance(links[0], dict):
        return False
    link = links[0]
    flags = link.get('flags')
    return (link.get('ifname') == 'lo' and link.get('link_type') == 'loopback'
            and type(link.get('ifindex')) is int and link['ifindex'] > 0
            and isinstance(flags, list) and all(isinstance(f, str) for f in flags)
            and 'LOOPBACK' in flags and 'UP' in flags)


def native(binary, output):
    # A fresh network namespace is established by the workflow before invocation.
    if not binary.is_file() or not output.parent.is_dir() or output.exists():
        raise ValueError('invalid owned run paths')
    inventory = subprocess.run(['ip', '-j', 'link', 'show'], capture_output=True,
                               check=True, timeout=3,
                               env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'})
    if not loopback_only(inventory.stdout):
        raise ValueError('loopback-only namespace required')
    if os.geteuid() == 0:
        raise ValueError('non-root fixture required')
    with tempfile.TemporaryDirectory(prefix='qwen-telemetry-', dir=output.parent) as d:
        root = Path(d)
        rows = []
        for enabled in (False, True):
            try:
                rows.append(trial(binary, root / ('on' if enabled else 'off'), enabled))
            except Exception as exc:
                # Bounded type-only diagnostics, not exception payloads or raw logs.
                rows.append(dict(mode='on' if enabled else 'off', error=type(exc).__name__))
    good = fixture_pass(rows) and all(witness_pass(r.get('file_access_witness')) for r in rows)
    receipt = dict(schema='qwen-public-file-telemetry-smoke/v2', native_harness='0.28.3',
                   model='SYNTHETIC_LOCAL_HTTP_FIXTURE', source=os.environ.get('GITHUB_SHA', 'UNKNOWN'),
                   raw_payload_retained=False, rows=rows, verdict='PASS' if good else 'FAIL')
    output.write_text(json.dumps(receipt, sort_keys=True) + '\n')
    print(json.dumps(receipt, sort_keys=True))
    return 0 if good else 1


class ContractTests(unittest.TestCase):
    def test_namespace_inventory(self):
        lo = dict(ifindex=1, ifname='lo', link_type='loopback', flags=['LOOPBACK', 'UP'])
        self.assertTrue(loopback_only(json.dumps([lo])))
        for rows in ([], [lo, dict(lo, ifname='eth0')], [dict(lo, ifname='eth0')],
                     [dict(lo, flags=['LOOPBACK'])], [dict(lo, link_type='ether')],
                     [dict(lo, ifindex=True)], [dict(lo, flags='UP')], [None], {}):
            self.assertFalse(loopback_only(json.dumps(rows)))
        self.assertFalse(loopback_only('{broken'))

    def test_file_parser_and_markers(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'trace'
            self.assertEqual(inspect_telemetry(p, ['canary'])['records'], 0)
            p.write_text('{"x":1}\n{"y":"canary"}\n')
            self.assertEqual(inspect_telemetry(p, ['canary'])['records'], 2)
            self.assertTrue(inspect_telemetry(p, ['canary'])['payload_marker_seen'])
            p.write_text('{"x":')
            with self.assertRaises(ValueError):
                inspect_telemetry(p, [])
            p.write_bytes(b'x' * (CAP + 1))
            with self.assertRaises(ValueError):
                inspect_telemetry(p, [])

    def test_actual_loopback_fixture(self):
        seen = dict(requests=0, tool_requested=False, tool_result_seen=False,
                tool_result_marker_records=0, tool_result_id_matches=0)
        with http.server.ThreadingHTTPServer(('127.0.0.1', 0), make_handler(Path('/synthetic.txt'), 'file-marker', 'answer-marker', seen)) as srv:
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            try:
                endpoint = f'http://127.0.0.1:{srv.server_port}/v1/chat/completions'
                def call(body):
                    req = urllib.request.Request(endpoint, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
                    with urllib.request.urlopen(req, timeout=3) as resp:
                        return resp.read()
                body = dict(messages=[], tools=[{'function': {'name': 'read_file'}}])
                reply = json.loads(call(body))
                self.assertEqual(reply['choices'][0]['finish_reason'], 'tool_calls')
                body.update(messages=[{'role': 'tool', 'content': 'file-marker', 'tool_call_id': 'wrong'}], stream=True)
                self.assertIn(b'answer-marker', call(body))
                self.assertEqual(seen['tool_result_id_matches'], 0)
                body.update(messages=[{'role': 'tool', 'content': 'file-marker', 'tool_call_id': 'call_fixture'}])
                self.assertIn(b'answer-marker', call(body))
                self.assertEqual(seen, dict(requests=3, tool_requested=True, tool_result_seen=True,
                                           tool_result_marker_records=2, tool_result_id_matches=1))
            finally:
                srv.shutdown()
                t.join(5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    if args.self_test:
        unittest.main(argv=[__file__], verbosity=2)
    if not args.binary or not args.receipt:
        parser.error('binary and receipt required')
    raise SystemExit(native(args.binary.resolve(), args.receipt.resolve()))
