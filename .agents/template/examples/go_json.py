"""Translate uncached Go JSON test events into the public summary contract."""
import json
import os
from pathlib import Path
import subprocess
import sys

run=subprocess.run(['go','test',*sys.argv[1:],'-json','-count=1'],capture_output=True,text=True,encoding='utf-8',errors='replace')
sys.stdout.write(run.stdout); sys.stderr.write(run.stderr)
outcomes={}; package_errors=set()
for line in run.stdout.splitlines():
    try: event=json.loads(line)
    except json.JSONDecodeError: continue
    action=event.get('Action'); package=event.get('Package',''); name=event.get('Test')
    if name and action in {'pass','fail','skip'}: outcomes[package,name]=action
    if not name and action=='fail': package_errors.add(package)
failed=sum(value=='fail' for value in outcomes.values())
errors=sum(not any(p==package and v=='fail' for (p,_),v in outcomes.items()) for package in package_errors)
report=dict(schema='test-summary.v1',total=len(outcomes)+errors,passed=sum(v=='pass' for v in outcomes.values()),failed=failed,errors=errors,skipped=sum(v=='skip' for v in outcomes.values()))
Path(os.environ['CONTINUITY_REPORT']).write_text(json.dumps(report),encoding='utf-8')
raise SystemExit(run.returncode)
