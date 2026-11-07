"""Credentials in text the tool writes: what it redacts, and what the credential scan of ws check reports."""
from __future__ import annotations

import re
from pathlib import Path

from .core import CREDENTIALS, watched_files
from .schema import CHAT_DIR

LABEL_EN = (r'(?<![A-Za-z])((?:client[_-]?)?secret(?:[_-]?key)?|password|passwd|pwd|passphrase|'
            r'api[_-]?key|access[_-]?key|private[_-]?key|auth[_-]?token|access[_-]?token|token|authorization|key|pw|pass)(?![A-Za-z])')
LABEL_ZH = r'(密码|口令|密钥|秘钥|令牌|私钥)'
QUOTED = r'"([^"\n]{4,128})"|\'([^\'\s][^\'\n]{3,127})\'(?![A-Za-z0-9])|`([^`\n]{4,128})`'
BARE = r'([^\s"\'`|，,。；;、）)\]}<>][^\s"`|，,。；;、）)\]}<>]{2,126}[^\s"\'`|，,。；;、）)\]}<>])'
SEP_EN = r'["\']?\s*(?:[:=：＝]|\s+is\s+)\s*(?:(?:bearer|basic|token)\s+)?'
SEP_ZH = r'\s*(?:[:=：＝]|是|为)?\s*'
SECRET_PATTERNS = (
    # label: value, label = value, "label": "value", label is value
    re.compile(r'(?i)' + LABEL_EN + r'(' + SEP_EN + r')(?:' + QUOTED + '|' + BARE + ')'),
    re.compile(LABEL_ZH + r'(' + SEP_ZH + r')(?:' + QUOTED + '|' + BARE + ')'),
    # Markdown table row: | label | value |
    re.compile(r'(?i)(?:\*\*)?((?<![A-Za-z])(?:password|passwd|secret|api[_-]?key|token)|密码|口令|密钥|令牌)'
               r'(?:\*\*)?(\s*\|\s*)(?:' + QUOTED + '|' + BARE + ')'),
)
# A login stated in plain words: "root 登录用 Xy7kq9Lm2", "passphrase Xy7kq9Lm2", "ssh admin@host Xy7kq9Lm2".
# Separators are bounded and possessive-free so a line of spaces cannot make the pattern backtrack.
CUE = re.compile(r'(?i)(?:(?<![A-Za-z])(?:root|passphrase|pw|pwd)(?![A-Za-z])|登录|登陆|账号|用户名)'
                 r'[ \t]{0,3}(?:用|的|是|为|with|is|:|：|=)?[ \t]{0,3}(?:用|是|为)?[ \t]{0,3}'
                 r'([A-Za-z0-9!@#$%^&*_+=.-]{8,64})(?![A-Za-z0-9])')
# The host must look like one: user@host, an IPv4 address or a dotted name. A bare word made the rule fire on
# 151 lines in 49 of 10,140 local user messages, nearly all session names and paths; this form fired on 2 (both real).
HOST = r'(?:\d{1,3}(?:\.\d{1,3}){3}|[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){0,4})'
AFTER_LOGIN = re.compile(r'(?<![A-Za-z0-9._-])(?:[A-Za-z0-9._-]{1,64}@' + HOST + r'|\d{1,3}(?:\.\d{1,3}){3}'
                         r'|[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){1,4})'
                         r'[ \t]{1,3}(?:password|密码|pw)?[ \t]{0,3}([A-Za-z0-9!@#$%^&*_+=-]{8,64})(?![A-Za-z0-9.])')
# A password made only of letters. Layer 1: the label and a separator make it a value, so only
# placeholders are spared. Layer 2: label and word with no separator ("my password hunterhunter");
# a common English word there is prose ("password manager"), anything else is a value.
PASSWORD_LABEL = r'(?:(?<![A-Za-z0-9])(?:password|passwd|pwd|passphrase)(?![A-Za-z])|口令|密码)'
LETTERS_AFTER_SEPARATOR = re.compile(r'(?i)' + PASSWORD_LABEL + r'["\']?[ \t]{0,3}(?:[:=：＝]|[ \t]is[ \t]|是|为)'
                                     r'[ \t]{0,3}["\']?([A-Za-z]{6,64})(?![A-Za-z0-9_./(-])')
WEAK_AFTER_SEPARATOR = re.compile(r'(?i)' + PASSWORD_LABEL + r'["\']?[ \t]{0,3}(?:[:=：＝]|[ \t]is[ \t]|是|为)'
                                  r'[ \t]{0,3}["\']?((?=[a-z\d]{6,24}(?![A-Za-z0-9_.(-]))(?:[a-z]{2,20}\d{1,8}|\d{6,16}))')
LETTERS_AFTER_LABEL = re.compile(r'(?i)' + PASSWORD_LABEL + r'[ \t]{1,3}([A-Za-z]{6,64})(?![A-Za-z0-9_./(-])')
# A mixed value right after the word: "password Hunter2xyz9", "--password Hunter2xyz9". The old AFTER_LOGIN caught
# this by reading "--password" as a host; the narrowed host form does not, so the case has its own rule.
BEARER = re.compile(r'(?i)(?<![A-Za-z])bearer[ \t]{1,3}([A-Za-z0-9._~+/=-]{16,512})')
VALUE_AFTER_LABEL = re.compile(r'(?i)' + PASSWORD_LABEL + r'[ \t]{1,3}([A-Za-z0-9!@#$%^&*_+=-]{8,64})(?![A-Za-z0-9.])')
ENV_SECRET = re.compile(r'(?<![A-Za-z0-9_])[A-Z][A-Z0-9_]{0,40}(?:PASSWORD|PASSWD|PASS|SECRET|TOKEN|API_?KEY)=([^\s\'"`]{6,128})')
SSH_LINE = re.compile(r'(?i)\b(?:ssh|sshpass|mysql|psql)\b')
URL_CREDENTIAL = re.compile(r'(?i)(?<![a-z0-9+.-])[a-z][a-z0-9+.-]{0,15}://([^\s:/@]{1,128}):([^\s@/]{4,128})@')
URL_QUERY = re.compile(r'(?i)[?&](key|token|access_token|api_key|apikey|secret|sig|password)=([^\s&#]{8,})')
TOKEN_PATTERN = re.compile(
    r'\b(?:sk-[A-Za-z0-9_-]{16,}|sk_(?:live|test)_[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|gh[ousr]_[A-Za-z0-9]{20,}'
    r'|github_pat_[A-Za-z0-9_]{20,}|npm_[A-Za-z0-9]{30,}|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}'
    r'|AIza[0-9A-Za-z_-]{30,}|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b'
    r'|-----BEGIN [A-Z ]*PRIVATE KEY-----')
TOKEN_KINDS = (('sk_live_', 'Stripe key'), ('sk_test_', 'Stripe key'), ('sk-', 'API key (sk-)'), ('github_pat_', 'GitHub token'),
               ('gh', 'GitHub token'), ('npm_', 'npm token'), ('xox', 'Slack token'), ('AKIA', 'AWS key'),
               ('AIza', 'Google API key'), ('eyJ', 'JWT'), ('-----BEGIN', 'private key'))


def token_kind(value: str) -> str:
    """A name for a prefixed token. Never a slice of the value: labels reach ws check output and hook text."""
    return next((name for prefix, name in TOKEN_KINDS if value.startswith(prefix)), 'token')


# Words that follow "token:" or "password:" in ordinary documentation.
COMMON_VALUES = frozenset("""
redacted none null unknown example changeme password secret token required optional true false yes no
default empty string integer number boolean bytes length limit count budget usage oauth oauth2 jwt bearer
basic digest manager vault env environment variable value placeholder hidden masked omitted provided
""".split())
FULLWIDTH = {ord(c): ord(c) - 0xFEE0 for c in '０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ'}


# A value that is code reading a secret: a call or subscript whose argument starts with a quote or a name.
CODE_READ = re.compile(r'''(?:[A-Za-z_]\w*\.(?:[A-Za-z_]\w*\.)*[A-Za-z_]\w*|(?i:get_?env|getenv|environ|env|secrets?|config|cfg|settings|vault|keyring|os\.getenv))[\[(](?:["']|[A-Za-z_]\w*[\])]|$)''')


def looks_like_secret(value: str) -> bool:
    """Decide whether a value after a credential label is a real secret."""
    value = value.strip().translate(FULLWIDTH)
    lowered = value.lower()
    if len(value) < 6 or lowered in COMMON_VALUES or lowered.startswith(('your', 'my_', 'xxx')):
        return False
    if value.startswith(('http', '$', '%', '<', '[', '~', '/', '.', '{', '(')) or re.fullmatch(r'\*+|x+|\.+|-+', lowered):
        return False
    if re.fullmatch(r'v?\d+(?:\.\d+)+', value) or re.fullmatch(r'\d{1,9}', value):
        return False  # a version or a count, for example "token: v2.3.3" or "token: 128000"
    if CODE_READ.match(value):
        return False  # code that reads the value, such as os.environ["X"] or getenv("X")
    if re.fullmatch(r'[a-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+', value) or re.fullmatch(r'[a-z]+\d{1,3}', value):
        return False  # an attribute path such as config.apiKey2, or a word with a counter such as value2
    if re.fullmatch(r'[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+', value):
        return False  # an environment variable name such as LITGW_API_KEY
    if (re.fullmatch(r'[a-z]+(?:[_-][a-z]+)*', value) and (len(value) < 10 or '_' in value or '-' in value)) \
            or re.fullmatch(r'[A-Z][a-z]+(?:[A-Z][a-z]+)*', value):
        return False  # a plain word or CamelCase name such as SecretManager
    if ' ' in value:
        return len(value) >= 12 and len(value.split()) >= 3  # a passphrase in quotes
    if re.search(r'[\u3000-\u9fff\uff00-\uffef]', value):
        return False  # Chinese prose after the word 密码, not a credential value
    return bool(re.search(r'\d', value) or (re.search(r'[a-z]', value) and re.search(r'[A-Z]', value))
                or re.search(r'[^A-Za-z0-9]', value))


def _letters_password(value: str, prose: bool) -> bool:
    """Whether a run of letters after a password label is a password, not a placeholder or a word."""
    from .words import COMMON_WORDS
    lowered = value.lower()
    if lowered in COMMON_VALUES or lowered.startswith(('your', 'xxx')):
        return False
    if re.fullmatch(r'[A-Z][A-Z_]+', value):
        return False  # an environment variable name
    return not (prose and lowered in COMMON_WORDS)


def _value_span(match):
    for index in range(3, match.re.groups + 1):
        if match.group(index) is not None:
            return index
    return None


# Names that contain "key" or "token" but hold no secret (from the gitleaks generic-key allowlist).
NOT_SECRET_NAME = re.compile(r'(?i)(?:primary|foreign|public|schema|idx|sort|partition)[_.-]?key|csrf[_.-]?token'
                             r'|key[_.-]?(?:id|name|size|file|path|type)\b')


def _scan(line: str):
    """Yield (start, end, label) for every credential value in one line."""
    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(line):
            index = _value_span(match)
            if index and looks_like_secret(match.group(index)) and \
                    not NOT_SECRET_NAME.search(line[max(0, match.start() - 12):match.start(index)]):
                yield match.start(index), match.end(index), match.group(1).lower()
    for match in LETTERS_AFTER_SEPARATOR.finditer(line):
        # After "is" the next word can be prose ("the password is correct"), so common words are spared.
        spoken = bool(re.search(r'(?i)[ \t]is[ \t]', line[match.start():match.start(1)]))
        if _letters_password(match.group(1), prose=spoken):
            yield match.start(1), match.end(1), 'password'
    for match in WEAK_AFTER_SEPARATOR.finditer(line):
        yield match.start(1), match.end(1), 'password'
    for match in LETTERS_AFTER_LABEL.finditer(line):
        if _letters_password(match.group(1), prose=True):
            yield match.start(1), match.end(1), 'password'
    for match in BEARER.finditer(line):
        if re.search(r'[A-Za-z]', match.group(1)) and re.search(r'\d', match.group(1)):
            yield match.start(1), match.end(1), 'bearer token'
    for match in VALUE_AFTER_LABEL.finditer(line):
        value = match.group(1)
        if re.search(r'[A-Za-z]', value) and re.search(r'\d', value) and looks_like_secret(value) \
                and not re.fullmatch(r'[a-z]+\d*|[\d.]+', value):
            yield match.start(1), match.end(1), 'password'
    for match in CUE.finditer(line):
        value = match.group(1)
        if re.search(r'[A-Za-z]', value) and re.search(r'\d', value) and looks_like_secret(value) \
                and not re.fullmatch(r'[\d.]+|[0-9a-f]{7,40}', value) and '.' not in value.strip('.'):
            yield match.start(1), match.end(1), 'login'
    if SSH_LINE.search(line) or 'password' in line.lower() or '密码' in line:
        # Only a login command or a password word makes "host value" a credential pair.
        for match in AFTER_LOGIN.finditer(line):
            value = match.group(1)
            if re.search(r'[A-Za-z]', value) and re.search(r'\d', value) and looks_like_secret(value) \
                    and not re.fullmatch(r'[a-z]+\d*|[\d.]+', value):
                yield match.start(1), match.end(1), 'login'
    for match in ENV_SECRET.finditer(line):
        value = match.group(1)
        if not value.startswith(('$', '%', '<', '{')) and value.lower() not in COMMON_VALUES:
            yield match.start(1), match.end(1), 'environment variable'
    for match in URL_CREDENTIAL.finditer(line):
        if looks_like_secret(match.group(2)) or len(match.group(2)) >= 6:
            yield match.start(2), match.end(2), 'url password'
    for match in URL_QUERY.finditer(line):
        yield match.start(2), match.end(2), 'url ' + match.group(1).lower()
    for match in TOKEN_PATTERN.finditer(line):
        yield match.start(), match.end(), token_kind(match.group(0))


# Invisible format characters split a key so no pattern matches it: zero-width space and joiners, soft hyphen,
# word joiner, BOM. They are removed only from a line that hides a credential, so emoji joiners elsewhere stay.
INVISIBLE = re.compile('[\u00ad\u180e\u200b-\u200f\u2060-\u2064\ufeff]')


def _visible(line: str) -> str:
    """The line itself, or the line without invisible characters when only that form shows a credential."""
    if not INVISIBLE.search(line):
        return line
    bare = INVISIBLE.sub('', line)
    return bare if _spans(bare) and not _spans(line) else line


# Host data that is neither user text nor a credential the user chose to keep: Codex stores compaction and
# reasoning as encrypted blobs the host can replay, so the raw copy never keeps them.
HOST_BLOBS = ('encrypted_content',)


def redact_json_lines(text: str) -> str:
    """Redact a JSON or JSONL transcript. Strings inside the JSON are redacted after decoding, so
    escaped quotes and \\u escapes cannot hide a credential. Encrypted host blobs are always dropped."""
    import json
    plain = keep_plain()
    if plain and not any(f'"{key}"' in text for key in HOST_BLOBS):
        return text

    def clean(value):
        if isinstance(value, str):
            if plain:
                return value
            # The raw copy is a backup kept out of version control, so blanking an ID that looks random
            # costs little, while a pasted key that survived here would defeat the Markdown redaction.
            return redact_pasted(value)
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, dict):
            return {k: '[removed: encrypted host data]' if k in HOST_BLOBS and isinstance(v, str) else clean(v)
                    for k, v in value.items()}
        return value

    stripped = text.lstrip()
    if stripped.startswith(('{', '[')):
        try:
            return json.dumps(clean(json.loads(text)), ensure_ascii=False)
        except ValueError:
            pass
    out = []
    for line in text.split('\n'):
        try:
            item = json.loads(line) if line.strip() else None
        except ValueError:
            out.append(line if plain else redact(line))
            continue
        out.append(line if item is None else json.dumps(clean(item), ensure_ascii=False))
    return '\n'.join(out)


WINDOW = 4000
OVERLAP = 400


def _spans(line: str) -> set:
    """Credential spans in one line. A long line is scanned in overlapping windows, so a pathological
    line costs milliseconds instead of minutes and no credential is lost at a window edge."""
    if len(line) <= WINDOW:
        return {(s, e) for s, e, _ in _scan(line)}
    found = set()
    for offset in range(0, len(line), WINDOW - OVERLAP):
        found |= {(offset + s, offset + e) for s, e, _ in _scan(line[offset:offset + WINDOW])}
    return found


RANDOM_TOKEN = re.compile(r'(?<![A-Za-z0-9_+=./-])([A-Za-z0-9_+=-]{24,128})(?![A-Za-z0-9_+=./-])')
# Prefixes of host message and call IDs, which look random but are not secrets.
ID_PREFIX = re.compile(r'(?i)^(?:call_|toolu_|msg_|req_|sess_|resp_|run_|chatcmpl|file_|org_|proj_|asst_|thread_|co-|vertex_)')


def _entropy(value: str) -> float:
    import math
    counts = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    return -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())


# A 16-31 character random key (B43; 24-31 added after the 3.6.0 review). Measured on 10,140 local user messages after the rules above: 17 messages, all real
# keys or session cookies, plus 2 camelCase names. Only for user text: a state row has no other copy to restore from.
SHORT_TOKEN = re.compile(r'(?<![A-Za-z0-9_+=./\\%#?&<(:\[{-])([A-Za-z0-9+]{16,31})(?![A-Za-z0-9_+=./-])')
FORMULA = re.compile(r'(?:[A-Z][a-z]?\d{0,3})+')  # a chemical formula such as C6H12O6Na2Cl
CAMEL = re.compile(r'(?:[A-Z]?[a-z]{2,}|\d{1,4})+')  # an identifier such as parseUtf8ToJson2
URL_BEFORE = re.compile(r'(?:https?://|www\.)\S*$')


def _has_word(value: str) -> bool:
    from .words import COMMON_WORDS
    low = value.lower()
    return any(low[i:j] in COMMON_WORDS for i in range(len(low)) for j in range(i + 6, min(len(low), i + 20) + 1))


def _mixed(value: str) -> bool:
    return bool(re.search(r'[a-z]', value) and re.search(r'[A-Z]', value) and re.search(r'\d', value))


# Labels precise enough to warn on (B41). On 10,140 local user messages these fired on 65 (0.64%), mostly real.
# Bare "key", "token", "pass" and "login" are left out: they fire on prose about keys.
NOTICE_LABELS = frozenset({'password', 'passwd', 'pwd', 'passphrase', '密码', '口令', '密钥', '秘钥', '私钥',
                           'api_key', 'api-key', 'apikey', 'auth_token', 'auth-token', 'access_token', 'client_secret',
                           'client-secret', 'secret_key', 'bearer token', 'environment variable', 'url password', *dict(TOKEN_KINDS).values()})


def credential_kinds(text: str, limit: int = 20000) -> list:
    """Names (never values) of the precise credential kinds in a user message, for the prompt hook notice."""
    text = text[:limit]
    kinds = {label for line in text.split('\n') for _, _, label in _scan(_visible(line[:WINDOW])) if label in NOTICE_LABELS}
    clean = redact(text)
    if _short_and_pairs(clean) != clean:
        kinds.add('unlabeled key')
    return sorted(kinds)


def redact_pasted(text: str) -> str:
    """redact() plus unlabeled random tokens. For text the user typed, where a pasted key has no label.
    Measured on 5,191 local user messages from Claude, Codex and Kiro: the token rule fired 18 times, 12 on values that
    redact() already removed. It cannot catch hex keys or short passwords."""
    if keep_plain():
        return text
    text = redact(text)
    def replace(match):
        value = match.group(1)
        if ID_PREFIX.match(value) or re.fullmatch(r'[0-9a-fA-F-]+', value) or 'base64,' in text[max(0, match.start() - 8):match.start()]:
            return value
        if not _mixed(value):
            return value
        return '[REDACTED]' if _entropy(value) >= 4.3 else value
    return _short_and_pairs(RANDOM_TOKEN.sub(replace, text))


def _short_and_pairs(text: str) -> str:
    """B43 short keys, applied after redact(). Account pairs (email|value) were measured and left out: 7 of 11
    ordinary lines such as tab-separated rosters were redacted, against 2 real hits."""
    def short(match):
        value = match.group(1)
        if not _mixed(value) or ID_PREFIX.match(value) or FORMULA.fullmatch(value) or CAMEL.fullmatch(value) \
                or _entropy(value) < 3.6 or _has_word(value) or URL_BEFORE.search(text[max(0, match.start() - 200):match.start()]):
            return value
        return '[REDACTED]'
    return SHORT_TOKEN.sub(short, text)


def keep_plain() -> bool:
    """The user decided this project keeps credentials as written (WORKSPACE "credentials": "plain")."""
    return CREDENTIALS.get() == 'plain'


def redact(text: str) -> str:
    """Replace credential values in free text. Keeps the label so the reader knows what was removed.
    Does nothing when the user decided to keep credentials as written."""
    if keep_plain():
        return text
    out = []
    for line in text.split('\n'):
        line = _visible(line)
        spans = sorted(_spans(line))
        merged = []
        for start, end in spans:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        for start, end in reversed(merged):
            line = line[:start] + '[REDACTED]' + line[end:]
        out.append(line)
    return '\n'.join(out)


def find_secrets(text: str) -> list:
    """(line number, label) of likely credentials. Placeholders and environment variable names are allowed."""
    found = []
    for number, line in enumerate(text.split('\n'), 1):
        found += [(number, label) for label in sorted({label for _, _, label in _scan(_visible(line))})]
    return found


def project_file_in_agents(rel: str) -> bool:
    """A file under .agents/ that the template does not own: a report, script or note an agent put there."""
    from .schema import STATIC_FILES
    return (rel.startswith('.agents/') and not rel.startswith(('.agents/cache/', '.agents/template/'))
            and rel not in STATIC_FILES and rel not in ('.agents/.gitattributes', '.agents/.gitignore', '.agents/hooks.json'))


def secret_warnings(root: Path) -> list:
    """Credentials written into project files. Silent when the user decided to keep credentials as written."""
    warnings = []
    if keep_plain():
        return warnings
    for rel in watched_files(root):
        # Project files kept under .agents/ by mistake (reports, task notes) are scanned too; template files are not.
        if not (rel.startswith(('docs/', 'ops/')) or project_file_in_agents(rel)) or rel.startswith(CHAT_DIR + '/'):
            continue
        if not rel.endswith(('.md', '.txt', '.json', '.yaml', '.yml', '.toml', '.ini', '.ps1', '.sh', '.py', '.env.example')):
            continue
        try:
            text = (root / rel).read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        for number, label in find_secrets(text)[:3]:
            fix = ('history rows stay as they are' if rel.startswith('docs/logs/') else
                   'the user has not chosen to keep credentials in files: ask, then set WORKSPACE "credentials", '
                   'or name the variable or file that holds it')
            warnings.append(f'{rel}:{number}: looks like a credential ({label}). {fix[0].upper() + fix[1:]}')
    return warnings
