"""Common English words of six or more letters, to tell a word from a password after "password".

Built from words that appear in 25 or more Python standard library modules, plus words that follow
"password" in ordinary writing (reset, manager, policy, hashing). Lower case, one string to keep the
file small.
"""

COMMON_WORDS = frozenset("""
absolute abspath abstract accept accepted accepts access according account accounts across action active
actual actually adding addition additional address administrator against algorithm allowed allows almost
already alternative although always amount another anything anyway appear appears append appended application
applications appropriate arbitrary argument arguments around assert assigned associated assume assumed attempt
attempted attempts attribute attributes authenticate authenticated authentication authorization automatically
available background backward backwards basename bcrypt because become becomes before beginning behavior
behaviour better between binary blocking blocks boolean bottom breach broken buffer builtin builtins button
bytearray callable callback called caller calling cancel cannot caught certain change changed changes changing
character characters charset checked checking checks children chunks classes classmethod cleartext client
clients closed closing codecs collections column columns command commands comment comments common compare
comparison compatibility compatible compile compiled compiler complete complex complexity component components
compromise compromised condition conditions config configuration configure configured confirm connect
connection considered consists constants constructor contain contained containing contains content contents
context contextlib continue control controls convenience conversion convert converted cookie cookies copied
copies copyright correct correctly corresponding create created creates creating creation current currently
custom darwin database debugging decimal decode decoded decoding decrypt default defaults define defined
defines definition delete deleted depending depends deprecated derived described description descriptor
desired destroy details detect determine determined dialog dictionary difference different digits direct
directly directories directory dirname disable disabled discard display displayed distribution distutils
docstring document documentation double duplicate during earlier easier effect either element elements enable
enabled encode encoded encoding encodings encountered encrypt encrypted encryption ending endswith enough
ensure entire entries enumerate environ environment equivalent errors escape escaped events everything exactly
example except exception exceptions executable execute executed execution existing exists expand expect
expected expiration expire expired expires expiry explicit explicitly exposed exposure expression extend
extended extension extensions external factory failed failing failure fallback family faster feature fields
figure filename filenames fileno filesystem filter finally finished follow followed following follows forgot
forgotten format formatted formatting forward frozenset fullname function functionality functions functools
further future gencodec general generate generated generator geometry getattr getcwd getregentry getvalue
global globals greater groups guaranteed handle handled handler handlers handles handling happen happens
hasattr hashed hashes hashing having header headers height helper hidden history however identical identifier
idlelib ignore ignored immediately implement implementation implemented implements import important imported
importlib imports include included includes including incorrect indent indentation indicate indicates
indicating information inherited initial initialization initialize initialized inputs insecure insert inside
install installed instance instances instead integer integers intended interface internal interpreted
interpreter invalid invoke isfile isinstance issubclass issues iterable iteration iterator itertools itself
keychain keyring keyword keywords kwargs lambda larger latter leading leaked legacy length libraries library
likely lineno listdir listed literal little loaded loader locale locals location logging logins logout longer
looking lookup lstrip machine machinery mainloop making management manager managers mapping marked masked
master matches matching maximum maxsize meaning mechanism member members memory memoryview message messages
metaclass method methods minimum missing modified modify module modules multiple namedtuple namespace native
nbytes necessary needed negative neither nested newline normal normally normcase normpath nothing notice
number numbers numeric object objects occurs offset omitted opened opening operation operations operator
optimization option optional optionally options origin original others otherwise output outside overridden
override package packages parameter parameters parent parsed parser parsing partial particular partition
passed passing pathname pattern patterns perform performance perhaps permission pickle plaintext platform
platforms please points policies policy position positive possible possibly prefix present prevent previous
previously printed printing private probably problem problems process processed processes processing produce
program prompt prompted prompts proper properly properties property protect protected protection protocol
provide provided provides public purpose purposes python quoted quotes raised raises random rather reached
readable reading readline really reason reasons received recent recognized recommended record records recover
recovery recursion recursive recursively reduce reference references register registered registry regular
related relative release remaining remove removed replace replaced replacement report represent representation
representing represents request requested requests require required requirement requirements requires reserved
resets resource resources response restore result resulting results retries return returned returning returns
reused reverse reversed rotate rotated rotating rotation rstrip running runtime salted scheme screen script
scripts scrypt search second seconds section secure secured security select selected selection semantics
sending separate separated separator sequence sequences server service services session sessions setattr
setdefault setting settings several shared sharing should shouldn shutdown signal signature signin signup
silently similar simple simplefilter simply single skipped skipping socket software something sorted source
spaces special specific specification specified specifies specify specifying splitext splitlines stacklevel
standard started starting starts startswith statement states static staticmethod status stderr stdout storage
stored storing stream streamreader streamwriter strength strict string strings strong struct structure
subclass subclasses subprocess subsequent subset succeeded success suffix suitable supplied support supported
supporting supports suppress syntax system systems tables target temporary terminated testing thanks therefore
things though thread threading threads through timeout tkinter together tokenize tokens traceback trailer
trailing transform translate treated trying tuples typically typing unchanged undefined underlying unexpected
unicode unique unittest unknown unless unlink unsafe unsupported update updated updates updating urllib useful
username usernames usually validate validated validation values variable variables various verbose verbosity
verification verified verify verifying version versions visible warning warnings weaker whatever whether
whitespace widget window windows within without working wrapped wrapper writable writing written
stayed remains remained became appeared needs anywhere nowhere somewhere
""".split())
