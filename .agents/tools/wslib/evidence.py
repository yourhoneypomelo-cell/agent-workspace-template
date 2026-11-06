"""Run acceptance commands and validate the evidence they leave behind."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from .core import WorkspaceError, atomic_write, difference, digest, fingerprint, now, read, safe_path, sha
from .schema import OUTPUT_LIMIT

MAX_REPORT_BYTES = 10 * 1024 * 1024
COUNTERS = ('total', 'passed', 'failed', 'errors', 'skipped')
EVIDENCE_RE = re.compile(r'docs/archive/checks/[A-Za-z0-9_-]+\.json')
DEFINITION_FIELDS = ('Requirements', 'Scope', 'Action', 'Acceptance', 'Depends')


def task_definition(row: dict) -> str:
    return digest({k: row.get(k, '') for k in DEFINITION_FIELDS})


def acceptance_kind(row: dict) -> str:
    return 'check' if row.get('Acceptance', '').strip().lower().startswith('check:') else 'test'


# A check proves behavior only when it names the output it must produce: check: <command> expect "<text>".
# Every expect clause must appear in the output; /text/ is matched as a regular expression. Without one, a check
# proves only that the command exited 0, which is enough for builds and linters, and verify says so.
EXPECT_RE = re.compile(r'\s+expect\s+("(?:[^"\\]|\\.)+"|/(?:[^/\\]|\\.)+/)', re.I)


def split_expect(acceptance: str) -> tuple:
    """(acceptance without its expect clauses, [expected strings or compiled patterns])."""
    expected = []
    for raw in EXPECT_RE.findall(acceptance):
        body = raw[1:-1].replace('\\"', '"').replace('\\/', '/')
        expected.append(re.compile(body, re.M) if raw.startswith('/') else body)
    return EXPECT_RE.sub('', acceptance), expected


def _matches(pattern: str, output: str) -> bool:
    try:
        return bool(re.search(pattern, output, re.M))
    except re.error:
        return False


def missing_expected(output: str, expected: list) -> list:
    return [e.pattern if hasattr(e, 'pattern') else e for e in expected
            if not (e.search(output) if hasattr(e, 'search') else e in output)]


# Terminal summaries. Unknown formats are never guessed as passing.
def summarize(output: str) -> dict:
    text = re.sub(r'\x1b\[[0-9;]*m', '', output)
    failure = bool(re.search(r'^FAILED(?:\s|$)', text, re.M))
    failure |= any(int(n) > 0 for n in re.findall(r'^# (?:fail|cancelled) (\d+)\s*$', text, re.M))
    for line in text.splitlines():
        if re.match(r'^\s*(?:=+\s*|Tests?(?:\s|:)|Test (?:Suites|Files)(?:\s|:)|\d+ (?:passed|failed|errors?))', line):
            failure |= any(int(n) > 0 for n in re.findall(r'(\d+) (?:failed|errors?|xpassed)', line))
    result = dict(parser='unknown', known=False, total=0, passed=0, failed=0, errors=0, skipped=0, explicit_failure=failure)
    runs = list(re.finditer(r'^Ran (\d+) tests? in .+$', text, re.M))
    if runs:
        statuses = re.findall(r'^(OK|FAILED)(?: \(([^\n]+)\))?\s*$', text, re.M)
        if len(statuses) != len(runs):
            return result
        result.update(parser='unittest', known=True, total=sum(int(m[1]) for m in runs))
        for status, details in statuses:
            counts = {k.strip(): int(n) for k, n in re.findall(r'([a-z ]+)=(\d+)', details)}
            result['failed'] += counts.get('failures', 0) + counts.get('unexpected successes', 0)
            result['errors'] += counts.get('errors', 0)
            result['skipped'] += counts.get('skipped', 0) + counts.get('expected failures', 0)
            if status == 'FAILED' and not counts:
                result['errors'] += 1
        result['passed'] = result['total'] - result['failed'] - result['errors'] - result['skipped']
    else:
        lines = [l for l in text.splitlines() if ' in ' in l and re.match(r'^\s*(?:=+\s*)?\d+ (?:passed|failed|skipped|errors?|xfailed|xpassed)', l)]
        if lines:
            values = {}
            for line in lines:
                for n, k in re.findall(r'(\d+) (passed|failed|skipped|errors?|xfailed|xpassed)', line):
                    values[k] = values.get(k, 0) + int(n)
            result.update(parser='pytest', known=True, total=sum(values.values()), passed=values.get('passed', 0),
                          failed=values.get('failed', 0) + values.get('xpassed', 0),
                          errors=values.get('error', 0) + values.get('errors', 0),
                          skipped=values.get('skipped', 0) + values.get('xfailed', 0))
        else:
            tap = {k: int(n) for k, n in re.findall(r'^# (tests|pass|fail|cancelled|skipped|todo) (\d+)\s*$', text, re.M)}
            if all(k in tap for k in ('tests', 'pass', 'fail')):
                result.update(parser='node-tap', known=True, total=tap['tests'], passed=tap['pass'], failed=tap['fail'],
                              errors=tap.get('cancelled', 0), skipped=tap.get('skipped', 0) + tap.get('todo', 0))
            else:
                for line in reversed(text.splitlines()):
                    if re.match(r'^\s*Tests\s*:?', line):
                        total = re.search(r'(\d+) total|\((\d+)\)', line)
                        values = {k: int(n) for n, k in re.findall(r'(\d+) (passed|failed|skipped|todo)', line)}
                        if total:
                            result.update(parser='jest-vitest', known=True, total=int(total[1] or total[2]),
                                          passed=values.get('passed', 0), failed=values.get('failed', 0),
                                          skipped=values.get('skipped', 0) + values.get('todo', 0))
                        break
    if any(result[k] < 0 for k in COUNTERS):
        result['known'] = False
    if result['known'] and result['total'] != sum(result[k] for k in COUNTERS[1:]):
        result['known'] = False
    return result


TEST_CONFIG = re.compile(r'(?:^|/)(?:conftest\.py|pytest\.ini|tox\.ini|setup\.cfg|(?:jest|vitest)\.config\.[cm]?[jt]s)$')
TEST_FILE = re.compile(r'(?:^|/)(?:tests?/|test_[^/]*\.py$|[^/]*_test\.(?:py|go)$|[^/]*\.(?:test|spec)\.[cm]?[jt]sx?$)')


def surface(output: str, files: dict) -> dict:
    """What a run did not test: deselected tests, and the test files and runner config it saw. Kept apart from
    the summary, so evidence recorded before 3.6 still matches its own output."""
    text = re.sub(r'\x1b\[[0-9;]*m', '', output)
    finals = [l for l in text.splitlines() if re.match(r'^\s*=*\s*\d+ (?:passed|failed|skipped|deselected|errors?)\b', l) and ' in ' in l]
    deselected = sum(int(n) for n in re.findall(r'(\d+) deselected', finals[-1])) if finals else 0
    return {'deselected': deselected,
            'test_files': sorted(f for f in files if TEST_FILE.search(f)),
            'config': {f: files[f] for f in files if TEST_CONFIG.search(f)}}


def shrank(previous: dict | None, data: dict) -> list:
    """Ways this accepted run tests less than the task's previous accepted run (U27): fewer tests, more skipped or
    deselected, a test file removed or the runner config changed. Ordinary test edits are not reported: in real
    projects 17 to 96 percent of commits change a test."""
    if not previous or previous.get('command') != data.get('command'):
        return []
    old, new = previous.get('summary') or {}, data['summary']
    before, after = previous.get('surface') or {}, data.get('surface') or {}
    found = []
    if new.get('total', 0) < old.get('total', 0):
        found.append(f'{old["total"]} tests before, {new["total"]} now')
    if 'surface' in previous and new.get('skipped', 0) + after.get('deselected', 0) > old.get('skipped', 0) + before.get('deselected', 0):
        found.append(f'skipped or deselected rose from {old.get("skipped", 0) + before.get("deselected", 0)} '
                     f'to {new.get("skipped", 0) + after.get("deselected", 0)}')
    gone = sorted(set(before.get('test_files', [])) - set(after.get('test_files', [])))
    if gone:
        found.append('test files removed: ' + ', '.join(gone[:4]))
    if before.get('config') is not None and before.get('config') != after.get('config'):
        found.append('test runner config changed: ' + ', '.join(sorted(set(before['config']) ^ set(after['config']) |
                     {f for f in after['config'] if before['config'].get(f) != after['config'][f]})[:4]))
    return found


# Only a runner's own summary line counts, so prose such as "no tests ran for module x" is not matched.
EMPTY_RUN = re.compile(r'^(?:Ran 0 tests in |collected 0 items\s*$|=+ no tests ran in |ok\s+\S+\s+.*\[no test files\]$)', re.M)


def scope_paths(row: dict, files) -> list | None:
    """Project paths a task's Scope and Acceptance name, as found in the watched files; None when it names none, so the whole tree
    counts. Scope is free text such as "src/gateway.py and tests/", so only tokens that match a file or folder count."""
    names = set(files)
    found = []
    for token in re.findall(r'[A-Za-z0-9_.\-/\\]+', row.get('Scope', '') + ' ' + row.get('Acceptance', '')):
        token = token.replace('\\', '/')
        token = (token[2:] if token.startswith('./') else token).rstrip('/')
        # "python -m unittest tests.test_x" names a module; its file is tests/test_x.py.
        for candidate in (token, token.replace('.', '/') + '.py'):
            if candidate and (candidate in names or any(n.startswith(candidate + '/') for n in names)):
                found.append(candidate)
                break
    return found or None


def in_scope(rel: str, scope: list | None) -> bool:
    return scope is None or any(rel == p or rel.startswith(p + '/') for p in scope)


def passed(summary: dict) -> bool:
    return summary['known'] and summary['passed'] > 0 and summary['failed'] == 0 and summary['errors'] == 0 and not summary['explicit_failure']


def parse_report(text: str, kind: str) -> dict:
    if len(text.encode('utf-8')) > MAX_REPORT_BYTES:
        raise WorkspaceError('report exceeds 10 MiB')
    if kind == 'json':
        data = json.loads(text)
        if not isinstance(data, dict) or data.get('schema') != 'test-summary.v1':
            raise WorkspaceError('JSON report requires "schema": "test-summary.v1"')
        values = {k: data.get(k) for k in COUNTERS}
        if any(type(v) is not int or v < 0 for v in values.values()):
            raise WorkspaceError('report counters must be non-negative integers')
    elif kind == 'junit':
        if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
            raise WorkspaceError('DTD and entities are not allowed in reports')
        try:
            root = ET.fromstring(text)
        except ET.ParseError as error:
            raise WorkspaceError(f'invalid JUnit XML: {error}') from error

        def tag(element):
            return element.tag.rsplit('}', 1)[-1]
        if tag(root) not in {'testsuites', 'testsuite'}:
            raise WorkspaceError('JUnit root must be testsuite or testsuites')
        values = dict.fromkeys(COUNTERS, 0)
        for case in (n for n in root.iter() if tag(n) == 'testcase'):
            states = {tag(c) for c in case} & {'failure', 'error', 'skipped'}
            if len(states) > 1:
                raise WorkspaceError('a JUnit testcase has contradictory outcomes')
            outcome = next(iter(states), 'passed')
            values[{'failure': 'failed', 'error': 'errors'}.get(outcome, outcome)] += 1
            values['total'] += 1
        for suite in (n for n in root.iter() if tag(n) in {'testsuite', 'testsuites'}):
            cases = [n for n in suite.iter() if tag(n) == 'testcase']
            counts = {'tests': len(cases), 'failures': 0, 'errors': 0, 'skipped': 0}
            for case in cases:
                states = {tag(c) for c in case}
                for key, name in (('failures', 'failure'), ('errors', 'error'), ('skipped', 'skipped')):
                    counts[key] += int(name in states)
            for key, expected in counts.items():
                if key in suite.attrib and (not suite.attrib[key].isdigit() or int(suite.attrib[key]) != expected):
                    raise WorkspaceError(f'JUnit attribute {key} disagrees with the testcase records')
    else:
        raise WorkspaceError('unknown report format')
    if values['total'] != sum(values[k] for k in COUNTERS[1:]):
        raise WorkspaceError('report counters do not add up')
    return dict(parser='report-' + kind, known=True, **values, explicit_failure=values['failed'] > 0 or values['errors'] > 0)


def _resolve(command: list) -> tuple:
    """Return (argv to execute, argv to record). Records never hold local interpreter paths."""
    recorded = list(command)
    run = list(command)
    if run[0] in ('python', 'python3', 'py'):
        run[0] = sys.executable
    else:
        found = shutil.which(run[0])
        if found:
            run[0] = found
    return run, recorded


def _clip(text: str) -> str:
    if len(text) <= OUTPUT_LIMIT:
        return text
    half = OUTPUT_LIMIT // 2
    return text[:half] + f'\n[... {len(text) - OUTPUT_LIMIT} characters omitted ...]\n' + text[-half:]


def run(root: Path, command: list, label: str, writer: str, revision: int, kind: str, timeout: int,
        report_format: str | None, definitions: dict, for_tasks: list | None = None, expected: list | None = None) -> tuple:
    before_files = fingerprint(root, source_only=True)
    started = now()
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    env.pop('CONTINUITY_REPORT', None)
    report_rel = None
    if report_format:
        if kind != 'test':
            raise WorkspaceError('structured reports need --kind test')
        report_rel = f'docs/archive/checks/{os.urandom(8).hex()}.report.{"xml" if report_format == "junit" else "json"}'
        report_path = safe_path(root, report_rel)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        env['CONTINUITY_REPORT'] = str(report_path.resolve())
    argv, recorded = _resolve(command)
    from .coverage import redact
    # Redact the joined command too: a label and its value are often two separate arguments.
    joined = redact(' '.join(recorded))
    recorded = [part if part in joined else '[REDACTED]' for part in (redact(p) for p in recorded)]
    try:
        proc = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True, encoding='utf-8',
                              errors='replace', timeout=timeout)
        output, code = proc.stdout + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as error:
        def text(v):
            return v.decode('utf-8', 'replace') if isinstance(v, bytes) else (v or '')
        output, code = text(error.stdout) + text(error.stderr) + '\nTIMEOUT\n', 124
    except OSError as error:
        output, code = str(error), 127
    from .coverage import redact
    output = redact(_clip(output.replace(str(root.resolve()), '<root>')))
    summary = summarize(output)
    report, report_error = None, None
    if report_format:
        try:
            path = safe_path(root, report_rel)
            if path.stat().st_size > MAX_REPORT_BYTES:
                raise WorkspaceError('report exceeds 10 MiB')
            raw = path.read_bytes()
            report = {'format': report_format, 'path': report_rel, 'sha256': sha(raw)}
            parsed = parse_report(raw.decode('utf-8-sig'), report_format)
            parsed['explicit_failure'] |= summary['explicit_failure']
            summary = parsed
        except (OSError, ValueError) as error:
            report_error = str(error)
            summary = dict(parser='report-' + report_format, known=False, total=0, passed=0, failed=0, errors=0,
                           skipped=0, explicit_failure=True)
    after_files = fingerprint(root, source_only=True)
    changed = difference(before_files, after_files)
    source_stable = before_files == after_files
    empty_run = kind == 'check' and bool(EMPTY_RUN.search(output))
    missing = missing_expected(output, expected or [])
    accepted = (code == 0 and source_stable and not summary['explicit_failure'] and not empty_run and not missing
                and (kind == 'check' or passed(summary)))
    reasons = []
    if code != 0:
        reasons.append(f'exit code {code}')
    if not source_stable:
        names = changed['added'] + changed['modified'] + changed['removed']
        reasons.append('the command changed watched files: ' + ', '.join(names[:8]) +
                       '. Write test output under an excluded path or add it to WORKSPACE exclude')
    if missing:
        reasons.append('the output lacks what the acceptance expects: ' + '; '.join(f'"{m}"' for m in missing[:4]))
    if empty_run:
        reasons.append('the command reports that no tests ran; a run with zero tests is not evidence')
    if kind == 'test' and not passed(summary):
        reasons.append('no passing tests were recognized' if not summary['known'] else
                       f'tests: {summary["passed"]} passed, {summary["failed"]} failed, {summary["errors"]} errors')
    if report_error:
        reasons.append('report: ' + report_error)
    data = dict(schema='verification.v5', command=recorded, label=label, started_at=started, finished_at=now(),
                writer=writer, revision=revision, kind=kind, exit_code=code, source=digest(after_files),
                source_files=after_files,
                source_stable=source_stable, task_definitions=definitions, summary=summary, report=report,
                report_error=report_error, accepted=accepted, reasons=reasons, output=output,
                for_tasks=list(for_tasks or []), surface=surface(output, after_files),
                expected=[e.pattern if hasattr(e, 'pattern') else e for e in expected or []],
                output_sha256=sha(output.encode('utf-8')))
    safe_label = re.sub(r'[^A-Za-z0-9_-]', '-', label)[:48] or 'check'
    rel = f'docs/archive/checks/{safe_label}-{os.urandom(6).hex()}.json'
    atomic_write(safe_path(root, rel), json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    return rel, data


def load(root: Path, rel: str, required_kind: str) -> dict:
    if not EVIDENCE_RE.fullmatch(rel):
        raise WorkspaceError(f'invalid evidence path "{rel}"; evidence lives in docs/archive/checks/*.json')
    data = json.loads(read(root, rel))
    if data.get('schema') != 'verification.v5' or data.get('accepted') is not True or data.get('exit_code') != 0:
        raise WorkspaceError(f'{rel} is not accepted evidence')
    if sha(data.get('output', '').encode('utf-8')) != data.get('output_sha256'):
        raise WorkspaceError(f'{rel}: recorded output was edited')
    if data.get('kind') != required_kind:
        raise WorkspaceError(f'{rel}: evidence kind is {data.get("kind")}, the task acceptance needs {required_kind}')
    summary = summarize(data['output'])
    if data.get('report'):
        report = data['report']
        raw = safe_path(root, report['path']).read_bytes()
        if sha(raw) != report.get('sha256'):
            raise WorkspaceError(f'{rel}: report attachment changed')
        explicit = summary['explicit_failure']
        summary = parse_report(raw.decode('utf-8-sig'), report['format'])
        summary['explicit_failure'] |= explicit
    if summary != data.get('summary'):
        raise WorkspaceError(f'{rel}: recorded summary does not match the recorded output')
    if required_kind == 'test' and not passed(summary):
        raise WorkspaceError(f'{rel}: no passing tests')
    gone = [e for e in data.get('expected') or [] if e not in data['output'] and not _matches(e, data['output'])]
    if gone:
        raise WorkspaceError(f'{rel}: recorded output lacks the expected "{gone[0]}"')
    if summary['explicit_failure']:
        raise WorkspaceError(f'{rel}: output reports a failure')
    return data


def evidence_paths(value: str) -> list:
    return EVIDENCE_RE.findall(value or '')
