"""Run real unittest discovery and write the current run's structured report."""
import json
import os
from pathlib import Path
import sys
import unittest

suite=unittest.defaultTestLoader.discover(sys.argv[1] if len(sys.argv)>1 else '.')
result=unittest.TextTestRunner(verbosity=2).run(suite)
failed=len(result.failures)+len(result.unexpectedSuccesses)
errors=len(result.errors)
skipped=len(result.skipped)+len(result.expectedFailures)
report=dict(schema='test-summary.v1',total=result.testsRun,passed=result.testsRun-failed-errors-skipped,failed=failed,errors=errors,skipped=skipped)
Path(os.environ['CONTINUITY_REPORT']).write_text(json.dumps(report),encoding='utf-8')
raise SystemExit(0 if result.wasSuccessful() else 1)
