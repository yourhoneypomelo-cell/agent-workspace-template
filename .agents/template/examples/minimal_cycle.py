"""Run a full session cycle in a temporary project: init, record, verify, abrupt stop, takeover, handoff."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[3]


def main():
    with tempfile.TemporaryDirectory(prefix='ws-example-', dir=os.environ.get('WS_TEMP') or None) as folder:
        project = Path(folder) / 'project'
        tool = [sys.executable, str(TEMPLATE / '.agents/tools/ws.py')]
        env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
        # The example plays several sessions; the host session running it must not make them one.
        for name in ('WS_SESSION_ID', 'CLAUDE_CODE_SESSION_ID', 'CODEX_SESSION_ID', 'QWEN_CODE_SESSION_ID', 'ZCODE_SESSION_ID',
                     'KIRO_SESSION_ID', 'WS_ROLE'):
            env.pop(name, None)

        def ws(*args, expect=0):
            result = subprocess.run([*tool, '--root', str(project), *args], capture_output=True, text=True,
                                    encoding='utf-8', env=env)
            if result.returncode != expect:
                raise SystemExit(f'ws {" ".join(args)} exited {result.returncode}\n{result.stdout}{result.stderr}')
            return result.stdout

        subprocess.run([*tool, 'install', '--target', str(project), '--allow-modified'], check=True, capture_output=True, env=env)
        ws('init', '--goal', 'Total order quantities and reject negative ones')
        ws('add', 'requirement', '--set', 'requirement=Totals sum the quantities; negative quantities raise ValueError',
           '--set', 'acceptance=python -m unittest test_orders', '--source', 'example user')
        ws('add', 'task', '--set', 'requirements=R1', '--set', 'scope=orders.py, test_orders.py',
           '--set', 'action=Implement total() with validation', '--set', 'acceptance=python -m unittest test_orders')
        ws('add', 'feature', '--set', 'behavior=Order totals with validation', '--set', 'requirements=R1', '--set', 'tasks=T1')
        (project / 'orders.py').write_text(
            'def total(quantities):\n    if any(q < 0 for q in quantities):\n        raise ValueError("negative quantity")\n'
            '    return sum(quantities)\n', encoding='utf-8')
        (project / 'test_orders.py').write_text(
            'import unittest\nfrom orders import total\n\n\nclass Orders(unittest.TestCase):\n'
            '    def test_sum(self):\n        self.assertEqual(total([2, 3]), 5)\n\n'
            '    def test_negative(self):\n        with self.assertRaises(ValueError):\n            total([1, -1])\n',
            encoding='utf-8')
        proof = json.loads(ws('verify', 'T1', '--done', '--', 'python', '-m', 'unittest', 'test_orders').splitlines()[0])
        ws('set', 'F1', '--set', 'status=shipped')
        ws('checkpoint', '--stop', 'T1 verified, F1 shipped', '--next', 'Ask the user for the next requirement')
        ws('check', '--ready')
        # A second session starts work and dies without a checkpoint.
        ws('start')
        (project / 'orders.py').write_text((project / 'orders.py').read_text(encoding='utf-8') + '\n# half-finished edit\n', encoding='utf-8')
        # A third session in another tool takes over and sees the unsaved file.
        brief = ws('brief')
        takeover = json.loads(ws('start', '--force', '--reason', 'the old window crashed').splitlines()[0])
        ws('checkpoint', '--stop', 'Reviewed the leftover edit in orders.py and kept it', '--next', 'Ask the user for the next requirement')
        ws('check', '--ready')
        print(json.dumps({
            'product_tests': proof['summary']['passed'],
            'unsaved_seen_in_brief': 'orders.py' in brief,
            'took_over_from': takeover['took_over_from'],
            'final': json.loads(ws('status'))['writer'] is None,
        }))


if __name__ == '__main__':
    main()
