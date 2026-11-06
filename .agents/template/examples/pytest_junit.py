"""Bridge pytest's native JUnit output to the unique verify destination."""
import os
import subprocess
import sys

raise SystemExit(subprocess.call([sys.executable,'-m','pytest',*sys.argv[1:],'--junitxml',os.environ['CONTINUITY_REPORT']]))
