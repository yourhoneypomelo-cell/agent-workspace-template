"""Advisory Markdown checks for layout and plain wording. They never block a save."""
from __future__ import annotations

import re
from pathlib import Path

from .schema import GUIDE_DIR, SKILLS, TEMPLATE_DIR

MAX_LINE = 120
FILLER = (
    'seamless', 'seamlessly', 'robust', 'leverage', 'delve', 'cutting-edge', 'state-of-the-art', 'game-changer',
    'in conclusion', 'it is important to note', "it's important to note", 'needless to say', 'rest assured',
    'best-in-class', 'world-class', 'supercharge', 'unlock the power', 'bulletproof',
)
# Phrase patterns adapted from sloptrim (Apache-2.0), which reports a 0 to 6.7% false positive rate.
# Single vocabulary words are left out: the overused words change with each model generation.
AI_TELLS = tuple((re.compile(p, re.I), advice) for p, advice in (
    (r',\s+(?:highlighting|symbolizing|emphasizing|underscoring|showcasing|fostering|cultivating|encompassing|'
     r'embodying)\s+(?:the|its|their|a|an|how|our)\b', 'adds a trailing comment; end the sentence'),
    (r"\b(?:it'?s worth (?:noting|mentioning) that|it bears (?:noting|mentioning)|one thing to (?:consider|keep in mind) is)",
     'announces a point; state it'),
    (r',\s+(?:paving the way for|with broader implications for|signaling a shift toward)\b', 'inflates the stakes; cut it'),
    (r"\b(?:is|are|was|were)n'?t\s+(?:just|merely)\s+(?:a |an |the )?\w+\s*[,;]\s*(?:it'?s|it is|they are|but)\b",
     'is a "not X, it is Y" contrast; state Y'),
    (r"\b(?:I hope this helps|let me know if you|feel free to (?:ask|reach out)|great question|you(?:'?re| are) absolutely right)",
     'is chat phrasing; remove it from documents'),
    (r'\b(?:serves as an? (?:testament|reminder|cornerstone|beacon|catalyst)|stands as an?|boasts an?)\b',
     'avoids "is"; write "is" or the actual verb'),
    (r'^\s*(?:in summary|to summarize|all in all|in essence),', 'starts a recap; the reader just read it'),
    (r"\b(?:let'?s (?:dive in|unpack)|without further ado|here'?s the (?:kicker|thing))\b", 'is a staged reveal; cut it'),
    (r'\b(?:has|have) been (?:refactored|improved) to\b', 'narrates a change; describe the current state'),
    # Chinese, measured on 30,691 pre-2022 human paragraphs (Vue, Docker, Pro Git, TiDB, d2l, ruanyf weekly) against
    # 75,463 agent-written ones: chat residue 0 human hits. Jargon: these four words have 0 hits in Vue, Docker and
    # ruanyf weekly and 1,067 in the owner's agent docs; 打掉 抓手 赋能 底层逻辑 had 1-2 human hits each and were left out.
    (r'你说得对|希望(?:这|以上)[^。\n]{0,12}(?:对你|对您)有(?:所)?帮助|如有(?:任何)?(?:疑问|问题)[，,]?(?:请)?随时',
     'is chat phrasing; remove it from documents'),
    (r'(?<![验接吸回])收口(?!径)|坐实|拉齐|颗粒度', 'is workplace jargon; name the action and its object'),
))
CJK_RE = re.compile('[\u3400-\u9fff\uf900-\ufaff]')
BOLD_RE = re.compile(r'\*\*[^*\n]+?\*\*')
MAX_CJK_PARAGRAPH = 300  # paragraphs over this: human Chinese docs 0.28%, agent docs 3.53%
MAX_BOLD = 2  # three or more bold spans: human 0.13% (zh) and 0.25% (en), agent docs 16% (zh) and 4.5% (en)
EMOJI_RE = re.compile('[\U0001F300-\U0001FAFF\u2600-\u27BF]')
FENCE_RE = re.compile(r'^ {0,3}(`{3,}|~{3,})')


def reusable_docs(root: Path) -> list:
    # README.md is not checked: in the template it is the repository front page, in a project the product's own page.
    paths = ['AGENTS.md', *[f'{GUIDE_DIR}/{p.name}' for p in sorted((root / GUIDE_DIR).glob('*.md'))],
             *[f'.agents/skills/{s}/SKILL.md' for s in SKILLS],
             *[p.relative_to(root).as_posix() for p in sorted((root / TEMPLATE_DIR).rglob('*.md'))]]
    return [p for p in dict.fromkeys(paths) if (root / p).is_file()]


def check(text: str, rel: str) -> list:
    issues = []
    lines = text.split('\n')
    fence = False
    previous_level = 0
    h1 = 0
    front = text.startswith('---\n')
    unit = []  # (line number, prose) of the current paragraph or list item

    def flush():
        if unit:
            joined = ' '.join(prose for _, prose in unit)
            han = len(CJK_RE.findall(joined))
            if han > MAX_CJK_PARAGRAPH:
                issues.append(f'{rel}:{unit[0][0]}: paragraph of {han} Chinese characters; split it below {MAX_CJK_PARAGRAPH}')
            bold = len(BOLD_RE.findall(joined))
            if bold > MAX_BOLD:
                issues.append(f'{rel}:{unit[0][0]}: {bold} bold spans in one paragraph; bold only the term a reader must not miss')
            unit.clear()

    for number, line in enumerate(lines, 1):
        if front:
            if number > 1 and line == '---':
                front = False
            continue
        if FENCE_RE.match(line):
            fence = not fence
            flush()
            continue
        if fence:
            continue
        if not line.strip() or line.startswith(('#', '|', '<!--')) or re.match(r'\s*([-*+]|\d+\.) ', line):
            flush()
        if line != line.rstrip():
            issues.append(f'{rel}:{number}: trailing whitespace')
        heading = re.match(r'^(#{1,6}) ', line)
        if heading:
            level = len(heading[1])
            h1 += level == 1
            if previous_level and level > previous_level + 1:
                issues.append(f'{rel}:{number}: heading jumps from level {previous_level} to {level}')
            previous_level = level
            if number > 1 and lines[number - 2].strip():
                issues.append(f'{rel}:{number}: add a blank line before the heading')
            if line.rstrip().endswith((':', '.', '!')):
                issues.append(f'{rel}:{number}: headings take no closing punctuation')
        if line.startswith(('|', '<!--')):
            continue
        if not heading:
            unit.append((number, re.sub(r'`[^`]*`', '', line)))
        if re.search(r'https?://', line):
            continue
        # A mostly Chinese line is a whole paragraph on one line; the paragraph check measures it instead.
        if len(line) > MAX_LINE and len(CJK_RE.findall(line)) * 10 < len(line) * 3:
            issues.append(f'{rel}:{number}: line is {len(line)} characters; wrap prose at {MAX_LINE}')
        prose = re.sub(r'`[^`]*`', '', line)
        if '\u2014' in prose or re.search(r'[A-Za-z,] -- [a-z]', prose):
            issues.append(f'{rel}:{number}: dash used as punctuation; use a period or comma')
        if EMOJI_RE.search(prose):
            issues.append(f'{rel}:{number}: decorative symbol or emoji')
        if re.search(r'!{2,}|\?{2,}|\.{4,}', prose):
            issues.append(f'{rel}:{number}: repeated punctuation')
        # Full-width semicolons count only in prose: list items chain them legitimately (7,452 hits otherwise).
        wide = prose.count('；')
        wide = 0 if wide < 3 or re.match(r'\s*(?:[-*+]|\d+[.)])\s', prose) else wide
        if prose.count(';') + wide >= 2 and not re.search(r'\d[;；]\s*\d', prose):
            issues.append(f'{rel}:{number}: several semicolons in one line; split into sentences')
        lowered = prose.lower()
        for word in FILLER:
            if re.search(r'\b' + re.escape(word) + r'\b', lowered):
                issues.append(f'{rel}:{number}: filler wording "{word}"; state the concrete behavior')
        for pattern, advice in AI_TELLS:
            found = pattern.search(prose)
            if found:
                issues.append(f'{rel}:{number}: "{found.group(0).strip(", ")}" {advice}')
    flush()
    if h1 != 1:
        issues.append(f'{rel}: needs exactly one level-1 heading, found {h1}')
    if not text.endswith('\n') or text.endswith('\n\n'):
        issues.append(f'{rel}: end the file with exactly one newline')
    return issues


def sentences(text: str) -> set:
    body = re.sub(r'```.*?```', '', text, flags=re.S)
    body = re.sub(r'^\|.*$', '', body, flags=re.M)
    parts = re.split(r'(?<=[.?])\s+|(?<=[。！？])', ' '.join(body.split()))
    return {p.strip() for p in parts if len(p.strip()) >= 70 or len(CJK_RE.findall(p)) >= 25}


def duplicates(root: Path, paths: list) -> list:
    seen = {}
    issues = []
    for rel in paths:
        for sentence in sentences((root / rel).read_text(encoding='utf-8')):
            if sentence in seen and seen[sentence] != rel:
                issues.append(f'{rel}: repeats a sentence from {seen[sentence]}: "{sentence[:70]}..." Keep it in one place and link')
            seen.setdefault(sentence, rel)
    return issues


DATED_HEADING_RE = re.compile(r'^#{2,6} .*\b(?:19|20)\d\d-\d\d-\d\d\b')
LONG_PARAGRAPH = 6


def project_docs(root: Path) -> list:
    """Documents the agents of this project write: state files, project guides, specs and reports."""
    found = [*sorted((root / 'docs/state').glob('*.md')), *sorted((root / 'docs/guides').glob('*.md')),
             *sorted((root / 'docs/specs').glob('*/*.md')), *sorted((root / 'docs/reports').rglob('*.md'))]
    return [p.relative_to(root).as_posix() for p in found if p.is_file()]


# State rows are read first by every new session, so they hold the conclusion and a link; the detail lives in a
# spec, report or evidence file. These checks point at rows that grew past that. They never shorten anything.
# Measured on one 4-day field project: 15% of state cells were over 300 characters, 6.5% over 500, the longest 2,000.
CELL_LIMIT = 400
VERSION_RE = re.compile(r'\bv\d+(?:\.\d+)+\b')
ITEM_RE = re.compile(r'\((?:\d|[ivx]{1,3})\)|(?:^|\s)(?:\d|[ivx]{1,3})\)\s')
# Project-internal codes such as BLUE5 or ME-02. Common technical names are allowed.
CODE_RE = re.compile(r'(?<![\w./-])(?:[A-Z]{2,}\d{1,3}|[A-Z][A-Z0-9]{0,5}-\d{1,3}[A-Z]?)(?![\w.-])')
KNOWN_CODE = re.compile(r'^(?:UTF|SHA|MD|ISO|RFC|CVE|PEP|HTTP|TLS|SSL|IPV|AES|RSA|ED|EC|S3|H2|CP|GB|ES|ECMA|WCAG|OWASP|'
                        r'CWE|BLAKE|CRC|X)[-\d]|^[A-Z]{1,3}\d$', re.I)
DOC_LINK_RE = re.compile(r'(?<![\w/.])docs/[A-Za-z0-9_./-]+\.(?:md|json|txt)\b')
NEED_LINK = ('long cells, lists, version histories and undefined codes in docs/state/. Keep the conclusion in the row, '
             'move the detail to docs/specs/, docs/reports/ or the evidence file with a link, and delete nothing')


def defined_terms(root: Path) -> set:
    """Codes listed in the first column of the Terms table in ARCHITECTURE.md."""
    try:
        text = (root / 'docs/state/ARCHITECTURE.md').read_text(encoding='utf-8')
    except OSError:
        return set()
    part = text.split('\n## Terms', 1)
    if len(part) < 2:
        return set()
    section = part[1].split('\n## ', 1)[0]
    return {c.strip().strip('`') for line in section.split('\n') if line.startswith('|')
            for c in line.strip('|').split('|')[:1]}


def state_rows(text: str, rel: str, root: Path | None = None, terms: set | None = None) -> list:
    """Row-level checks for docs/state/: one fact per cell, history in logs, codes defined, links that resolve."""
    issues = []
    headers = []
    undefined = {}
    for number, line in enumerate(text.split('\n'), 1):
        if not line.startswith('|'):
            headers = [] if not line.strip() else headers
            prose = re.sub(r'`[^`]*`', '', line)
        else:
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            if set(line) <= set('|- :'):
                continue
            if not headers:
                headers = cells
                continue
            prose = ' '.join(re.sub(r'`[^`]*`', '', c) for c in cells)
            row = cells[0] if re.fullmatch(r'[A-Z]\d+', cells[0]) else (cells[0] or 'row')
            for column, cell in zip(headers, cells):
                if column == 'Requirement' and (len(cell) > CELL_LIMIT or len(ITEM_RE.findall(cell)) >= 3):
                    # A requirement may be the user's own words; those are kept verbatim.
                    issues.append(f'{rel}:{number}: {row} requirement is long. Keep the user\'s words as they are; if '
                                  'the length is detail an agent added, move it to docs/specs/<slug>/requirements.md '
                                  'and set the Detail column to that path')
                    continue
                if len(cell) > CELL_LIMIT:
                    issues.append(f'{rel}:{number}: {row} {column.lower()} is {len(cell)} characters. Keep the conclusion '
                                  'here and move the detail to a spec, report or evidence file, linked by path; delete nothing')
                if cell.count(';') + cell.count('；') >= 3 or len(ITEM_RE.findall(cell)) >= 3:
                    issues.append(f'{rel}:{number}: {row} {column.lower()} lists several facts. One fact per cell: '
                                  'split it into rows, or move the list to a spec and link it')
                if len(set(VERSION_RE.findall(cell))) >= 3:
                    issues.append(f'{rel}:{number}: {row} {column.lower()} holds a version history. Describe the current '
                                  'behavior here; the history belongs in CHANGE_LOG or a spec')
        for code in CODE_RE.findall(prose):
            if not KNOWN_CODE.match(code) and code not in (terms or ()):
                undefined.setdefault(code, number)
        if root is not None:
            for path in DOC_LINK_RE.findall(line):
                if '<' not in path and not (root / path).exists():
                    issues.append(f'{rel}:{number}: names {path}, which does not exist. Moved detail must stay reachable')
    if undefined:
        names = sorted(undefined, key=undefined.get)
        issues.append(f'{rel}:{undefined[names[0]]}: {len(names)} codes a new session cannot look up: '
                      f'{", ".join(names[:8])}{" and more" if len(names) > 8 else ""}. Define each once in the Terms '
                      'table of ARCHITECTURE.md, or write what it is')
    return issues


CHOICE_RE = re.compile(r'\bor\b.*\bor\b|\(\d\).*\(\d\)|[,，]\s*(?:or|或|或者)\s', re.I)


def card_notes(text: str, rel: str) -> list:
    """next_step must be one action a new session can take; a list of options belongs in an open question."""
    match = re.search(r'^\| next_step \| (.+) \|$', text, re.M)
    if not match or not CHOICE_RE.search(match[1]) or re.search(r'\bQ\d+\b', match[1]):
        return []
    line = text[:match.start()].count('\n') + 1
    return [f'{rel}:{line}: next_step offers several options. Give the one next action, or record the choice as a '
            'question (ws add question) and name its ID here']


def state_findings(root: Path, changed: set | None = None) -> list:
    """Row and growth findings in docs/state/, only in the files changed since the last checkpoint when given."""
    terms = defined_terms(root)
    found = []
    for path in sorted((root / 'docs/state').glob('*.md')):
        rel = path.relative_to(root).as_posix()
        if changed is None or rel in changed:
            text = path.read_text(encoding='utf-8')
            found += growth(text, rel) + state_rows(text, rel, root, terms) + card_notes(text, rel)
    return found


def state_count(root: Path, changed: set | None = None) -> int:
    return len(state_findings(root, changed))


ROW_ID_RE = re.compile(r':\d+: ([A-Z]\d+) ')


def fix_hint(finding: str) -> str:
    """A command that fixes one finding without losing what the row holds."""
    match = ROW_ID_RE.search(finding)
    if match and (' characters.' in finding or 'lists several facts' in finding or 'version history' in finding):
        rid = match[1]
        return (f'ws set {rid} --move-detail docs/reports/<topic>.md --set "<column>=<conclusion>. Detail: '
                'docs/reports/<topic>.md"')
    if 'codes a new session cannot look up' in finding:
        return 'add a row per code to the Terms table in docs/state/ARCHITECTURE.md'
    if 'next_step offers several options' in finding:
        return 'ws add question --set "question=..." then ws card --set "next_step=Ask the user Q<n>, then ..."'
    return 'see ws lint'


def cell_notes(fields: dict) -> list:
    """Notes for ws add and ws set: a value that will be hard to read in the brief. The value is stored as given."""
    return [f'{key.lower()} is {len(value)} characters. It is saved in full; for the next session, keep the conclusion in '
            'the row and move the detail to docs/specs/<slug>/ or docs/reports/, with the path in the row'
            for key, value in fields.items() if len(value) > CELL_LIMIT]


def growth(text: str, rel: str) -> list:
    """Patterns that make a current-facts file grow without adding facts."""
    issues = []
    current = rel.startswith('docs/state/')
    fence = False
    paragraph = []

    def flush():
        if len(paragraph) > LONG_PARAGRAPH:
            issues.append(f'{rel}:{paragraph[0][0]}: paragraph of {len(paragraph)} lines; split it into a record '
                          'form with one fact per field (STRUCTURE.md, "Record forms")')
        paragraph.clear()

    for number, line in enumerate(text.split('\n'), 1):
        if FENCE_RE.match(line):
            fence = not fence
            flush()
            continue
        if fence:
            continue
        if current and DATED_HEADING_RE.match(line):
            issues.append(f'{rel}:{number}: dated heading in a current-facts file. Update the fact where it '
                          'lives; the tool logs the history')
        if line.strip() and not line.startswith(('|', '#', '<!--')) and not re.match(r'\s*([-*]|\d+\.) ', line):
            paragraph.append((number, line))
        else:
            flush()
    flush()
    return issues


def run(root: Path, extra: list | None = None) -> list:
    paths = reusable_docs(root) + [p for p in (extra or []) if (root / p).is_file()]
    issues = []
    for rel in paths:
        issues += check((root / rel).read_text(encoding='utf-8'), rel)
    terms = defined_terms(root)
    for rel in project_docs(root):
        text = (root / rel).read_text(encoding='utf-8')
        issues += growth(text, rel) + [i for i in check(text, rel) if 'level-1 heading' not in i]
        if rel.startswith('docs/state/'):
            issues += state_rows(text, rel, root, terms) + card_notes(text, rel)
    return issues + duplicates(root, reusable_docs(root)) + duplicates(root, [p for p in project_docs(root)
                                                                          if p.startswith('docs/state/')])


def growth_count(root: Path, changed: set | None = None) -> int:
    """Number of growth and row findings in docs/state/, for the checkpoint reminder."""
    return state_count(root, changed)
