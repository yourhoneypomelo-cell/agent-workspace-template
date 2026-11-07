"""Unit tests for parsing, hashing, evidence rules, capture and lint."""
import json
import os
import unittest
from unittest import mock

from support import TEMPLATE, Workspace
from wslib import capture, core, evidence, lint, tables
from wslib.core import WorkspaceError
from wslib.schema import TABLES


class CardAndTables(Workspace):
    def test_card_round_trip_keeps_pipes_colons_and_unicode(self):
        text = self.read('docs/state/HANDOFF.md')
        updated = core.card_text(text, {'stop_point': 'C:\\项目: a | b'})
        self.assertEqual(core.parse_card(updated)['stop_point'], 'C:\\项目: a | b')
        self.assertEqual(core.STATE_RE.findall(updated), core.STATE_RE.findall(text))

    def test_unknown_card_field_names_valid_fields(self):
        text = self.read('docs/state/HANDOFF.md').replace('| phase |', '| stage |')
        with self.assertRaisesRegex(WorkspaceError, 'valid: phase'):
            core.parse_card(text)

    def test_fenced_tables_are_not_live_rows(self):
        t = TABLES['tasks']
        text = self.read(t.file) + '\n```text\n| ID | Status |\n| --- | --- |\n| T9 | todo |\n```\n'
        self.assertEqual(tables.parse(text, t.headers, t.file, 'T'), [])

    def test_broken_row_reports_line(self):
        t = TABLES['tasks']
        text = self.read(t.file).rstrip('\n') + '\n| T1 | todo | R1 |\n'
        with self.assertRaisesRegex(WorkspaceError, r'TASKS.md:\d+: row has 3 cells'):
            tables.parse(text, t.headers, t.file, 'T')

    def test_bad_status_lists_valid_values(self):
        self.init()
        result = self.ws('set', 'R1', '--set', 'status=finished', expect=2)
        self.assertIn('use one of: active, deprecated, removed, replaced', result.stderr)

    def test_set_source_is_an_alias_of_the_source_flag(self):
        self.init(requirement=False)
        self.ws('add', 'requirement', '--set', 'requirement=x', '--set', 'acceptance=y', '--set', 'source=user 2026-10-31')
        from wslib import logs
        self.assertEqual(logs.live_rows(self.root, 'REQUIREMENT_LOG')[-1]['Source'], 'user 2026-10-31')

    def test_stale_init_card_is_flagged(self):
        self.init()
        out = self.ws('checkpoint', '--stop', 'a', '--next', 'b').stdout
        self.assertIn('init text', out)
        self.assertIn('still hold the init text', self.ws('brief').stdout)

    def test_common_status_words_map_to_each_table(self):
        self.init(requirement=False)
        self.ws('add', 'requirement', '--set', 'requirement=x', '--set', 'acceptance=y', '--set', 'status=open')
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=tree:', '--set', 'action=b', '--set', 'acceptance=c')
        self.ws('add', 'feature', '--set', 'behavior=x', '--set', 'requirements=R1', '--set', 'tasks=T1', '--set', 'status=active')
        self.ws('set', 'T1', '--set', 'status=In Progress')
        rows = {r['ID']: r['Status'] for t in ('requirements', 'tasks', 'features') for r in tables.rows(self.root, TABLES[t])}
        self.assertEqual(rows, {'R1': 'active', 'T1': 'doing', 'F1': 'building'})
        self.assertIn('use one of', self.ws('set', 'F1', '--set', 'status=finished', expect=2).stderr)

    LEAKS = {
        'ip：211.101.244.239\n密码：dbMbM9BlENy8\n端口：33890': 'dbMbM9BlENy8',
        '用户名 administrator 密码 dbMbM9BlENy8': 'dbMbM9BlENy8',
        '| **密码** | `dbMbM9BlENy8` | 新密码 |': 'dbMbM9BlENy8',
        '密码是 ABC12345': 'ABC12345',
        '密码：Ａｂｃ１２３４５': 'Ａｂｃ１２３４５',
        'password: hunter2xyz': 'hunter2xyz',
        'password: HUNTER22': 'HUNTER22',
        "password: Ab'c12345xyz": "Ab'c12345xyz",
        'password: "correct horse battery staple"': 'correct horse battery staple',
        'my password is Abc12345': 'Abc12345',
        '{"password": "Abc12345"}': 'Abc12345',
        '{"client_secret": "zz9Qq8Ww7Ee6"}': 'zz9Qq8Ww7Ee6',
        'secret_key = "s3cr3tK3yValue"': 's3cr3tK3yValue',
        'api_key: AB12CD34EF56GH78': 'AB12CD34EF56GH78',
        'api_key=sk-abcdefghijklmnopqrstuvwxyz': 'sk-abcdefghijklmnop',
        'mysql://admin:Abc12345@db/app': 'Abc12345',
        'DATABASE_URL=postgres://user:S3cretPass@host/db': 'S3cretPass',
        'https://api.x.com/v1?key=Qw3rTy7uIoP1': 'Qw3rTy7uIoP1',
        'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9xyz': 'eyJhbGciOiJIUzI1NiJ9xyz',
        'github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz': 'github_pat_11ABCDEFG',
        '-----BEGIN OPENSSH PRIVATE KEY-----': 'BEGIN OPENSSH PRIVATE KEY',
        'root 登录用 Xy7kq9Lm2': 'Xy7kq9Lm2',
        'pw is Xy7kq9Lm2': 'Xy7kq9Lm2',
        'passphrase Xy7kq9Lm2': 'Xy7kq9Lm2',
        'ssh admin@10.0.0.5 Xy7kq9Lm2': 'Xy7kq9Lm2',
    }
    SAFE = ['凭据：VPS 密码只出现在聊天中，不得写入任何文件', '| 密码 | 用户自己保管，不写入文件 |', 'Set password: <your password>',
            'token: ${API_TOKEN}', 'api_key = LITGW_API_KEY', 'The password is rotated monthly.', 'password: changeme',
            '| Host key | ed25519 `SHA256:PkQefg03NnHLdBT5QIgXrlYH64mVqEw5cPYreWagRYs` |', 'Authorization: Bearer abc',
            'token: v2.3.3', 'token: 128000', 'token: OAuth2', 'password: Required', 'Token: Optional',
            'secret: SecretManager', '| token | Required |', 'commit 4b825dc642cb6eb9a060e54bf8d69288fbee4904',
            'the key handshake returns 401', 'key: value', 'Max tokens: 4096', 'https://example.com/path?page=2&sort=asc',
            'ssh admin@10.0.0.5 then run python3 test_v2.py', 'root cause was build 1234 on host2026',
            'ssh -i ~/.ssh/id_ed25519 -p 22 administrator@211.101.244.239', 'pass the T12 test now',
            'admin@example.com reported bug ABC12345', 'login uses OAuth2Flow handler', 'ssh into vps01 and restart']

    def test_credentials_are_redacted_in_english_and_chinese(self):
        from wslib.coverage import find_secrets, redact
        for text, secret in self.LEAKS.items():
            self.assertTrue(find_secrets(text), text)
            self.assertNotIn(secret, redact(text), text)
        for text in self.SAFE:
            self.assertEqual(find_secrets(text), [], text)
            self.assertEqual(redact(text), text)

    def test_redaction_is_fast_on_long_lines(self):
        import time
        from wslib.coverage import redact
        start = time.time()
        redact(('password: Abc12345 ' + 'x' * 1000 + ' ') * 200)
        redact('密码' * 50000)
        redact('password:' * 20000)
        self.assertLess(time.time() - start, 3)

    def test_secrets_never_reach_state_files(self):
        self.init()
        self.ws('add', 'requirement', '--set', 'requirement=Login with password: Abc12345', '--set', 'acceptance=y')
        self.ws('card', '--set', 'risks=root 密码：dbMbM9BlENy8')
        for rel in ('docs/state/REQUIREMENTS.md', 'docs/logs/REQUIREMENT_LOG.md', 'docs/state/HANDOFF.md'):
            self.assertNotIn('Abc12345', self.read(rel))
            self.assertNotIn('dbMbM9BlENy8', self.read(rel))

    def test_raw_transcript_copy_is_redacted(self):
        self.init()
        transcript = self.parent / 'leak.jsonl'
        lines = [json.dumps({'type': 'user', 'message': {'role': 'user', 'content': '密码：dbMbM9BlENy8'}}, ensure_ascii=False),
                 json.dumps({'type': 'user', 'message': {'role': 'user', 'content': 'rotate {"password": "Abc12345"}'}}),
                 json.dumps({'type': 'user', 'message': {'role': 'user', 'content': '密码：Zq9Wx8Ev7Rt6'}}),
                 'not json, password: Pp4Qq5Rr6']
        transcript.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        self.ws('capture', '--host', 'claude', stdin=json.dumps({'session_id': 'k', 'transcript_path': str(transcript)}))
        for rel in ('docs/chats/claude/k.md', 'docs/chats/claude/raw/k.jsonl'):
            text = self.read(rel)
            for secret in ('dbMbM9BlENy8', 'Abc12345', 'Zq9Wx8Ev7Rt6', 'Pp4Qq5Rr6'):
                self.assertNotIn(secret, text, rel)

    def test_verify_output_is_redacted_and_still_valid_evidence(self):
        self.init()
        self.ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=tree:', '--set', 'action=x', '--set', 'acceptance=check: echo')
        proof = self.json('verify', 'T1', '--done', '--kind', 'check', '--because', 'redaction probe', '--', 'python', '-c', "print('password: Abc12345')")
        self.assertNotIn('Abc12345', self.read(proof['evidence']))
        self.save()
        self.ready()

    def test_credential_in_docs_is_reported(self):
        self.init()
        self.write('docs/guides/SERVER.md', '# Server\n\n密码：dbMbM9BlENy8\n')
        out = self.ws('check', expect=None).stdout
        self.assertIn('docs/guides/SERVER.md:3: looks like a credential', out)

    def test_unquoted_value_gets_a_quoting_hint(self):
        self.init()
        result = self.ws('add', 'requirement', '--set', 'requirement=Login', 'works', '--set', 'acceptance=y', expect=2)
        self.assertIn('unexpected arguments: works', result.stderr)
        self.assertIn('needs quotes', result.stderr)
        self.assertNotIn('usage:', result.stderr)

    def test_bad_field_lists_valid_fields(self):
        self.init()
        result = self.ws('add', 'task', '--set', 'title=x', expect=2)
        self.assertIn('valid: status, requirements, scope', result.stderr)


class Summaries(unittest.TestCase):
    def test_recognized_passes(self):
        self.assertTrue(evidence.passed(evidence.summarize('Ran 2 tests in 0.01s\n\nOK\n')))
        self.assertTrue(evidence.passed(evidence.summarize('==== 3 passed in 0.2s ====')))
        self.assertTrue(evidence.passed(evidence.summarize('Tests: 3 passed, 3 total')))

    def test_failures_zero_and_unknown_never_pass(self):
        for output in ('Ran 1 test in 0.01s\nFAILED (failures=1)\n', '=== 1 passed, 1 failed in 0.1s ===',
                       'Ran 0 tests in 0.000s\n\nOK\n', 'Ran 2 tests in 0.1s\n\nOK (skipped=2)\n', 'all good',
                       '# tests 2\n# pass 1\n# fail 1\n'):
            self.assertFalse(evidence.passed(evidence.summarize(output)), output)

    def test_reports(self):
        junit = '<testsuite tests="2"><testcase name="a"/><testcase name="b"><skipped/></testcase></testsuite>'
        self.assertEqual(evidence.parse_report(junit, 'junit')['passed'], 1)
        for bad in ('<testsuite tests="3"><testcase/></testsuite>', '<!DOCTYPE x><testsuite/>'):
            with self.assertRaises(WorkspaceError):
                evidence.parse_report(bad, 'junit')
        with self.assertRaises(WorkspaceError):
            evidence.parse_report(json.dumps({'schema': 'test-summary.v1', 'total': 2, 'passed': 1, 'failed': 0,
                                              'errors': 0, 'skipped': 0}), 'json')


class Watching(Workspace):
    SKIPPED = ('.vscode/settings.json', '.idea/workspace.xml', 'target/x.o', 'out/a.class', 'coverage/lcov.info',
               'node_modules/x/i.js', '.claude/settings.local.json', 'docs/chats/x.md', '.agents/cache/f.json',
               'app.log', '.env')

    def test_build_ide_and_host_folders_are_skipped(self):
        for rel in ('src/app.py', *self.SKIPPED):
            self.write(rel, 'x')
        watched = core.watched_files(self.root)
        self.assertIn('src/app.py', watched)
        for rel in self.SKIPPED:
            self.assertNotIn(rel, watched)

    def test_cached_hash_still_sees_changes(self):
        self.write('src/a.py', 'one')
        first = core.fingerprint(self.root)['src/a.py']
        self.assertEqual(core.fingerprint(self.root)['src/a.py'], first)
        path = self.root / 'src/a.py'
        path.write_text('two', encoding='utf-8')
        info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1000))
        self.assertNotEqual(core.fingerprint(self.root)['src/a.py'], first)

    def test_crlf_checkout_is_not_a_change(self):
        self.write('src/a.py', 'one\ntwo\n')
        before = core.fingerprint(self.root)
        path = self.root / 'src/a.py'
        path.write_bytes(b'one\r\ntwo\r\n')
        handoff = self.root / 'docs/state/HANDOFF.md'
        handoff.write_bytes(handoff.read_bytes().replace(b'\n', b'\r\n'))
        self.assertEqual(core.fingerprint(self.root), before)

    def test_handoff_state_line_is_not_hashed(self):
        before = core.fingerprint(self.root)
        state = core.state_of(self.root)
        state['revision'] += 5
        core.save_state(self.root, state)
        self.assertEqual(core.fingerprint(self.root), before)

    def test_unsafe_paths(self):
        for rel in ('../x', 'C:/x', 'a\\b', 'docs/../../x'):
            with self.assertRaises(WorkspaceError):
                core.safe_path(self.root, rel)


class Locking(Workspace):
    def test_lock_from_dead_process_is_removed(self):
        self.write('.agents/cache/ws.lock', json.dumps({'pid': 999999, 'created_at': 'x'}))
        with core.lock(self.root):
            pass
        self.assertFalse((self.root / '.agents/cache/ws.lock').exists())

    def test_live_lock_blocks_with_advice(self):
        with core.lock(self.root), mock.patch.dict(os.environ, {'WS_LOCK_WAIT': '1'}):
            with self.assertRaisesRegex(WorkspaceError, 'another ws.py command is running'):
                with core.lock(self.root):
                    pass
        self.assertFalse((self.root / '.agents/cache/ws.lock').exists())


class Capture(Workspace):
    def test_claude_style_jsonl(self):
        lines = [
            {'type': 'user', 'message': {'role': 'user', 'content': '以后都用中文回复我'}},
            {'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Done.'},
                                                                                {'type': 'tool_use', 'name': 'x'}]}},
            {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'tool_result', 'content': 'secret tool output'}]}},
            {'type': 'user', 'message': {'role': 'user', 'content': 'key api_key=sk-abcdefghijklmnopqrstuvwxyz'}},
        ]
        path = self.parent / 't.jsonl'
        path.write_text('\n'.join(json.dumps(item, ensure_ascii=False) for item in lines), encoding='utf-8')
        messages = capture.extract(path)
        self.assertEqual([m[0] for m in messages], ['user', 'assistant', 'user'])
        rendered = capture.render('claude', 's1', messages, 't.jsonl')
        self.assertIn('以后都用中文回复我', rendered)
        self.assertNotIn('secret tool output', rendered)
        self.assertNotIn('sk-abcdefghijklmnop', rendered)

    def test_codex_rollout_drops_injected_instructions(self):
        def item(role, text, kind='input_text'):
            return {'type': 'response_item', 'payload': {'type': 'message', 'role': role, 'content': [{'type': kind, 'text': text}]}}
        lines = [
            {'type': 'session_meta', 'payload': {'id': 'x', 'cwd': 'D:/p'}},
            item('developer', 'You are Codex'),
            item('user', '# AGENTS.md instructions for D:/p\n\n<INSTRUCTIONS>...'),
            item('user', '<environment_context>cwd</environment_context>'),
            item('user', '实现 add 命令'),
            {'type': 'event_msg', 'payload': {'type': 'user_message', 'message': '实现 add 命令'}},
            {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'shell'}},
            item('assistant', 'Done.', 'output_text'),
        ]
        path = self.parent / 'rollout.jsonl'
        path.write_text('\n'.join(json.dumps(l, ensure_ascii=False) for l in lines), encoding='utf-8')
        self.assertEqual(capture.extract(path), [('user', '实现 add 命令'), ('assistant', 'Done.')])

    def test_kimi_wire_log(self):
        lines = [
            {'type': 'profile.bind', 'systemPrompt': 'You are Kimi'},
            {'type': 'agent.message.appended', 'message': {'message': {'role': 'user', 'content': [{'type': 'text', 'text': '继续'}]},
                                                            'meta': {'origin': {'kind': 'user'}}}},
            {'type': 'context.append_message', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': '继续'}]}},
            {'type': 'agent.message.appended', 'message': {'message': {'role': 'assistant', 'content': [
                {'type': 'think', 'think': 'hidden'}, {'type': 'text', 'text': '已完成。'}]}}},
            {'type': 'agent.message.appended', 'message': {'message': {'role': 'tool', 'content': [{'type': 'text', 'text': 'tool out'}]}}},
        ]
        path = self.parent / 'wire.jsonl'
        path.write_text('\n'.join(json.dumps(l, ensure_ascii=False) for l in lines), encoding='utf-8')
        self.assertEqual(capture.extract(path), [('user', '继续'), ('assistant', '已完成。')])

    def test_antigravity_transcript(self):
        lines = [
            {'type': 'USER_INPUT', 'source': 'USER_EXPLICIT', 'content': '<USER_REQUEST>\n继续上次的任务。\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\ntime\n</ADDITIONAL_METADATA>'},
            {'type': 'SYSTEM_MESSAGE', 'source': 'SYSTEM_SDK', 'content': 'The workspace brief ...'},
            {'type': 'PLANNER_RESPONSE', 'source': 'MODEL', 'thinking': 'hidden', 'tool_calls': [{'name': 'run_command'}]},
            {'type': 'GENERIC', 'source': 'MODEL', 'content': 'Command output: ...'},
            {'type': 'PLANNER_RESPONSE', 'source': 'MODEL', 'content': '已完成 list 命令。'},
        ]
        path = self.parent / 'transcript.jsonl'
        path.write_text('\n'.join(json.dumps(l, ensure_ascii=False) for l in lines), encoding='utf-8')
        self.assertEqual(capture.extract(path), [('user', '继续上次的任务。'), ('assistant', '已完成 list 命令。')])

    def test_gemini_style_json(self):
        path = self.parent / 'chat.json'
        path.write_text(json.dumps({'messages': [{'type': 'user', 'content': 'hi'}, {'type': 'gemini', 'content': 'hello'}]}),
                        encoding='utf-8')
        self.assertEqual(capture.extract(path), [('user', 'hi'), ('assistant', 'hello')])


class Lint(unittest.TestCase):
    def test_flags_dashes_filler_and_long_lines(self):
        text = '# Title\n\nA seamless flow \u2014 really.\n\n' + 'x ' * 70 + '\n'
        issues = '\n'.join(lint.check(text, 'x.md'))
        for word in ('dash', 'seamless', 'characters'):
            self.assertIn(word, issues)

    def test_clean_document_passes(self):
        self.assertEqual(lint.check('# Title\n\nRun `ws check`.\n\n## Steps\n\n1. Read the file.\n', 'x.md'), [])

    def test_template_documents_are_clean(self):
        self.assertEqual(lint.run(TEMPLATE), [])

    def test_contract_size(self):
        self.assertLess((TEMPLATE / 'AGENTS.md').stat().st_size, 14000)

    def test_chinese_rules(self):
        def issues(body):
            return '\n'.join(lint.check('# 标题\n\n' + body + '\n', 'x.md'))
        self.assertIn('semicolons', issues('第一步读取文件；第二步写入；第三步校验；第四步提交。'))
        # Two full-width semicolons, or a chain inside a list item, are left alone.
        self.assertNotIn('semicolons', issues('第一步读取文件；第二步写入；第三步校验。'))
        self.assertNotIn('semicolons', issues('- 读取；写入；校验；提交'))
        self.assertNotIn('jargon', issues('验收口径不变。'))
        self.assertIn('bold spans', issues('**一** 和 **二** 以及 **三**。'))
        self.assertIn('chat phrasing', issues('你说得对，这里需要改。'))
        self.assertIn('jargon', issues('这一步由维护者统一收口。'))
        self.assertIn('Chinese characters', issues('长' * 301))
        # A long Chinese line under 300 characters is not a long line; ordinary Chinese prose stays clean.
        for body in ('中' * 200, '运行 `ws check`，然后读取输出。', '值得注意的是，Docker 不是虚拟机，而是进程隔离。',
                     '这里用 **兜底** 方案处理未知路由。', '落盘之后再校验。'):
            self.assertEqual(issues(body), '', body)

    def test_chinese_duplicate_sentences(self):
        sentence = '这个工具把每一条需求都记录在状态文件里面，下一个会话从这些文件恢复工作。'
        self.assertIn(sentence, lint.sentences('前文。' + sentence + '后文。'))


if __name__ == '__main__':
    unittest.main()
