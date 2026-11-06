"""Run the self-tests by tier. A passing full run records the code it ran on, and ws.py release checks that record.

    python .agents/tools/tests/run.py --tier static
    python .agents/tools/tests/run.py --tier fast
    python .agents/tools/tests/run.py --tier full
    python .agents/tools/tests/run.py --tier fast --list
"""
import argparse
import json
import os
import platform
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parents[2]
sys.path[:0] = [str(HERE), str(HERE.parent)]
sys.dont_write_bytecode = True

from wslib import distribution  # noqa: E402
from wslib.core import atomic_write, now  # noqa: E402
from wslib.schema import SELFTEST  # noqa: E402

STATIC = ('test_static', 'test_core.Lint', 'test_distribution.Install.test_generated_files_match_defaults',
          'test_distribution.Install.test_template_checkout_matches_defaults')
# test_workflow, test_session, test_capture, test_field, test_v36, test_review and test_reconcile run only in full:
# together they take most of its twenty minutes. So do the classes of test_regressions that set up several windows.
FAST = STATIC + ('test_core', 'test_distribution', 'test_tracking', 'test_nudge', 'test_messages', 'test_probes',
                 'test_doctor',
                 *(f'test_regressions.{name}' for name in ('Imports', 'Locking', 'RetireMatching', 'Hooks', 'Evidence',
                                                          'Misc', 'Capture', 'Entry', 'Guarded')))


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def collect(tier: str) -> unittest.TestSuite:
    loader = unittest.defaultTestLoader
    if tier == 'full':
        found = loader.discover(str(HERE), pattern='test_*.py', top_level_dir=str(HERE))
    else:
        found = loader.loadTestsFromNames(FAST if tier == 'fast' else STATIC)
    tests, seen = [], set()
    for test in flatten(found):
        if test.id() not in seen:
            seen.add(test.id())
            tests.append(test)
    return unittest.TestSuite(tests)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='run.py', description='Run the workspace self-tests by tier.')
    parser.add_argument('--tier', choices=('static', 'fast', 'full'), default='fast')
    parser.add_argument('--list', action='store_true', help='print the tests of the tier without running them')
    args = parser.parse_args(argv)
    suite = collect(args.tier)
    if args.list:
        for test in flatten(suite):
            print(test.id())
        return 0
    tree, started = distribution.tree_digest(TEMPLATE), time.monotonic()
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if args.tier == 'full' and not os.environ.get('WS_IN_GATE'):
        record = {'passed': result.wasSuccessful(), 'tree': tree, 'tests': result.testsRun, 'failures': len(result.failures),
                  'errors': len(result.errors), 'skipped': len(result.skipped), 'seconds': round(time.monotonic() - started, 1),
                  'python': platform.python_version(), 'platform': platform.platform(), 'at': now()}
        atomic_write(TEMPLATE / SELFTEST, json.dumps(record, indent=1) + '\n')
        print(f'Recorded the full run in {SELFTEST}')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
