# Iter and Omega isolated upstream cores

These cores are selectable modes in **both Lila and Gödel**.
This work implements Stages 3–4 plus the host integration of the separately
qualified loops. Each agent retains its identity and uses its own mode state
directory and process. The native LLM client remains a later task.

**Status:** the isolated offline goal is qualified. Both standalone cores run;
the fixed twelve-scenario matrix per mode, six semantic mutants, relevant
upstream tests, Lean models and 380 observed trace checks pass. Omega uses an
explicit loader adapter for its pinned PeTTa v1.0.4 utility semantics. Vendored
files and existing upstream test files remain unchanged. The production loader
uses current evaluator semantics instead of the old utility reevaluation shim.

## Production modes

The existing `/modes` menu exposes `godelclaw`, `coding`, `iter` and `omega`.
`/mode iter` and `/mode omega` select the actual standalone loops; `iter` is
no longer an alias. Mode changes persist and request a supervised recycle.
The UI distinguishes the requested selection from the currently running loop.
`/mode godelclaw` returns to the previous local loop.

`launch.py` prepares private state and launches the selected MeTTa entrypoint.
It freezes the agent-wide selection path before changing CWD. The installed
CeTTa bundle includes its library directory beside the binary. Tests exercise
this installed layout with implicit selection-path defaults.

Iter uses native tool-call JSON through the existing owned HTTP transport and
the configured provider/model. Anthropic messages translate native tool-use
IDs, argument objects, grouped tool results and token-limit stop reasons at
this boundary. Claude requests use `tool_choice=auto`; Iter's existing loop
rejects/retries replies with no tools. Recent Claude models reject forced-tool
API options ([provider contract](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)).
The OpenAI-specific `enable_thinking` option is omitted on Anthropic, consistent
with the existing text provider's default thinking settings. Omega uses the
existing command-text provider adapter, including its Anthropic path. No new
credential client exists.

Lila uses her existing durable CWP Telegram service. Gödel keeps his existing
Bot API client in a separate process, with a private local channel socket. That
process keeps his controls responsive during provider requests. Both preserve
their existing bot, identity, model selection and operator lifecycle latch.

Inputs are acknowledged after history checkpoints. Mode switches before a
checkpoint leave the input with its existing channel owner. Iter experience,
Omega history, remembered text and transformations are mode-private. Omega's
embedding/NAL/PLN/plugin add-ons are not loaded; its advertised skills list only
the connected tools. Its `remember`/`query` adapter currently stores and searches
mode-private text rather than embeddings. All these differences are explicit
in the generated `adapter-ledger.json`.

Production process verification, using scripted HTTP/CWP peers:

```sh
MODE_TEST_CETTA_BIN=/path/to/installed/cetta \
  python -m unittest discover -s tests -p test_upstream_mode_runtime.py
```

The test runs both actual loops, verifies provider protocol shapes, saved input,
restarts and cooperative exits. Runtime receipts contain event metadata, not
provider prompts or credentials.

Live verification on 2026-09-30 completed a real provider/tool turn, history
checkpoint and supervised restart for each of Lila/Iter, Lila/Omega,
Gödel/Iter and Gödel/Omega. Both agents returned to `godelclaw` afterward.
Gödel kept his selected Claude model; signed thinking blocks are retained in
Iter's existing `reasoning_details` checkpoint field and passed back unchanged
until its upstream context cleanup prunes them. The native Anthropic boundary
tests exercise batch IDs, grouped results, reasoning signatures, token stops
and sanitized failure pacing:

```sh
python -m unittest discover -s tests -p test_iter_anthropic_provider.py
```

The local deployment receipt and original-file backups are kept outside the
garden, in the operator's integration verification directory. This live check
qualifies startup, turns and recovery; it is not a long-duration soak.

## Pins and review locations

| Component | Exact source |
|---|---|
| Iter | `patham9/iter` `f4064d97849ecaccac7939315a3f1a68de15c3ef` |
| Omega | `singnet/Omega` `ee0618a293ec3662a32b10b09c6cbb073f59d6b2` |
| Omega reference evaluator | PeTTa v1.0.4 `7037f4c2ad378c52fc328004fe216d5118b674f0` |
| CeTTa qualification | `godelclaw/CeTTa` [`9a535530`](https://github.com/godelclaw/CeTTa/commit/9a5355309c57d94e99e5a279e088b69cbe4486d8), branch `qualify/upstream-core-tests-20260930`, with `src/library_proc.c` text-boundary support |
| Lean models | `godelclaw/MeTTapedia` [`a4dafeb37`](https://github.com/godelclaw/MeTTapedia/commit/a4dafeb37243a9f8546fede9561321a2348077a5), `lean/pettaclaw/`, branch `pettaclaw/upstream-cores-20260930` |
| Offline core implementation | `modes/iter/`, `modes/omega/` and `modes/conformance/` in this repository |
| Production mode integration | This worktree, branch `integration/upstream-modes-20260930` |

The per-mode `upstream-manifest.json` lists **every tracked upstream file**, its
classification, whether it was vendored, and its digest or exclusion reason.
All vendored bytes are unchanged and verified before conformance. MIT and
Apache licenses remain beside the respective upstream copies.

## Exact offline verification command

From this repository, using the pinned reference and the corresponding CeTTa
and Lean branches above. Set the paths for your own checkouts and interpreter:

```sh
python3 modes/conformance/qualify.py \
  --cetta "$CETTA_BIN" \
  --petta "$PETTA_REFERENCE_ROOT" \
  --python "$PETTA_PYTHON" \
  --formal-root "$FORMAL_ROOT" \
  --output "$QUALIFICATION_OUTPUT"
```

The output contains `qualification.json`, the binary digest and toolchain,
matrix summary, raw per-evaluator traces, mutant results and source-test logs.
Generated Lean replay and oleans remain in the formal worktree's `.build/`.
Lean checks run sequentially using the caller's environment.
No credentials, account settings, network providers or live channels are used.

`conformance/scenarios.json` freezes the twelve specifications per mode. The
memory specification has two threshold fixtures; restart specifications also
run a second fresh process against copied persisted state. Only fixture-root
paths are normalized. Roots have equal lengths, so source `CHARS_SENT` values
are compared intact. Clock and session IDs are explicitly controlled.

Mutants: Iter last-call-only `nop`, a 49-turn budget, and a nine-call cap;
Omega duplicate input rearming, inclusive wake comparison, and no decrement.
Each runs only the scenario that distinguishes it from the reference.

Omega's 23 existing parsing tests run unchanged with their fixture supplied
directly; no pytest install is required. Existing `src_skills.metta` and
`src_utils.metta` pass, with their complete output matching the pinned reference.
The native runtime copy uses the recorded legacy-semantics adapter below.
Focused controls also compare predicate reevaluation, ordered answers,
negation stopping at its first answer, computed skill names and held arguments.
UTF-8 locale is controlled on both evaluators. Iter has no upstream test suite
at this pin. The focused `lib/proc` text tests and original golden fixture pass.

Upstream audit (2026-09-30): freshly fetched trueagi-io/PeTTa main
`ae66fa8e41dcd5539d614706bd4e5cfb34f9608d` also fails Omega's unchanged
`src_utils.metta`. The input-demand migration was merged upstream in
[PR #212](https://github.com/trueagi-io/PeTTa/pull/212), on 2026-07-24.
Correcting only the old `Expression` annotation makes that suite pass on both
latest trueagi and in-house PeTTa. Empty-case reevaluation is a separate issue:
latest trueagi still reevaluates; in-house `5883475` changes it to once. The
Omega callers inspected do not demonstrate dependence on that second run;
the legacy side-effect probes here preserve an observed oracle behavior, not
an independently asserted Omega requirement. Machine-specific audit logs and
qualification receipts stay outside the published source tree.

## Entrypoints and host contracts

Iter's entrypoint is `(iter:start)` in `iter/core.metta`. The host selects an
isolated working directory containing `prompt.txt`, `tools/`, `channels/`,
`memory/`, `transformations/` and `experience.json`. MeTTa owns control flow,
retry selection, dispatch policy, cleanup boundaries, checkpointing and pacing.
`iter_host.py` boxes JSON values and reuses the pinned Python helper sections
for filesystem/component operations. Tool workers execute through `lib/proc`.

Omega's entrypoint remains `(omega)` in the **unchanged** vendored
`src/loop.metta`. `omega/offline.py` loads the isolated core with explicit host
bindings. The host supplies configuration, provider, channel, clock, optional
startup facilities and a private `repos/Omega/memory/` directory. Runtime copies
may persist state; the vendor directory is never a state directory.

The production launcher uses distinct per-agent `modes/iter` and `modes/omega`
state roots. The fixture adapters remain isolated from production adapters.

## LLM boundary findings

Iter uses OpenAI-style chat messages, `tool_choice="required"`, native tool-call
IDs, reasoning fields and finish reasons. Plain text is marked undelivered;
no-call replies trigger temporary retries. Calls are capped before dispatch,
and dispatch uses the loaded implementation snapshot, independently of schemas
modified by transformations. Budget exhaustion continues the current task;
`nop` anywhere in the batch starts a new burst after polling.

Omega sends one assembled prompt string with token and reasoning limits and
receives command text. Its pinned helper parses that text; there are no native
tool-call IDs or finish reasons at this interface. Provider errors escape the
loop. Context is assembled before receiving input; the signed loop counter
decrements even while idle; wake comparison is strict. These protocols must
remain distinct in the future native client.

## Divergence and add-on ledger

| Boundary | Treatment and evidence |
|---|---|
| Iter Python loop | Replaced by `core.metta`; the complete pinned Python loop is the offline oracle. Requests, ordered results, control and persistence match the fixed matrix. |
| Iter JSON representation | `Box` preserves opaque JSON/None; scalar comparisons use host JSON equality because PeTTa symbols and authored string literals have different native representations. |
| Iter helper functions and prompts | Pinned helper sections 0–3 and prompts reused unchanged. The offline oracle uses the pinned Python SDK interface; production uses the existing owned HTTP adapter. No native client. |
| Iter worker launch | Existing `lib/proc` with the same five-second deadline, inherited environment and process group. A thin Python launcher redirects all streams to DEVNULL before exec, matching upstream worker streams. Embedded Python's `sys.executable` is replaced with the explicit host interpreter. |
| `lib/proc` text | Local minimal patch accepts Python/Prolog text atoms in PeTTa mode; HE retains grounded-string validation. `proc_text_boundary.metta` and original golden fixture pass. |
| Iter provider/channel/time | Scripted SDK-shaped replies, fake receive events and a fixed clock. The reference loop is observed at its existing loop boundary; test termination occurs after the requested iteration count. |
| Omega main launcher | Deliberately not loaded: its missing `src/context.metta` import and network/embedding/NAL/PLN add-ons are outside isolated core qualification. No replacement upstream module is fabricated. |
| Omega optional startup | Embedding initialization, security-policy application and plugin initialization are fixture no-ops. Real services/providers/plugins are not qualified here; each excluded source file is in the manifest. |
| Omega channels/provider | Fake channel plus scripted string provider at the original interface. Unknown commands, errors, send suppression and history remain upstream control. TCP mock implementations are retained as source but not started. |
| Omega clock | Generated utility module substitutes only clock/sleep operations with controlled host bindings. Integer fixture timestamps model source comparisons; real-time/IO behavior remains a host assumption. |
| Omega v1.0.4 input annotations | Two declarations in generated runtime copies translate old held `Expression` inputs to current `Atom`, and old evaluated/unguarded `Atom` inputs to `%Undefined%`. Result types remain `Bool`. Source authority: PeTTa `7037f4c`, `src/translator.pl:349-369`. The reference keeps its original declarations. |
| Omega v1.0.4 Empty case | Only `empty-to-bool` receives a generated compatibility body: enumerate matching answers, then reevaluate its predicate under negation, stopping at the first answer. This preserves the old evaluator's observable second evaluation, including a predicate that becomes empty. Source authority: PeTTa `7037f4c`, `src/translator.pl:163-172`; `runtime-repros/legacy-input-demand.metta` checks effects and answer order against that oracle. Every translated form is recorded in `legacy-semantics-adapter.json`; no global evaluator policy changes. |
| Omega `joinPath` | Thin direct binding to unchanged `helper.joinPath`, replacing the source cross-`progn` variable binding at this host filesystem boundary. Both evaluators use this binding in core fixtures. |
| Omega prompt/history reads | CeTTa-only filesystem bindings preserve provider prompt fallback and byte-tail history reads. The reference executes the original memory functions. This avoids the native computed-library-path incompatibility. |
| Omega `string-replace` | CeTTa-only codec binding reproduces `split_string` separator-set semantics plus joining, including empty input. The oracle executes the original Prolog calls; `runtime-repros/empty-string-replace.metta` isolates the native failure. |
| Omega configuration bool | The declared `spamShield` field converts its text spelling at the host configuration boundary; it does not change loop policy. |
| Omega restart/checkpoint | History persists; control resets. Test termination is a fixture-only exit at the upstream sleep boundary; provider failure exits before that boundary. |
| Unadapted legacy probes | `runtime-repros/typed-predicate-test.metta` and `empty-string-replace.metta` retain the native incompatibility reproductions. The loader adapters preserve the required pinned behavior; this work does not claim that CeTTa generally implements the old dialect without them. |
| Other upstream material | Complete file-by-file manifest marks deployment, provider/channel, plugin, theory and ancillary material outside this isolated core. No agent add-ons are merged into either pinned source. |

## Lean boundary and source references

`IterArchitecture.lean` reuses the transformation/snapshot/restart proofs and
adds selected properties for `nop` anywhere in a batch, budget continuation and
checkpoint rollback. `observedCycle` exposes requests, dispatch, save, wait and
recovery. Source: `iter.py` sections 3–4, particularly response capping,
snapshot dispatch, checkpoint assignments and final pacing branches.

`OmegaArchitecture.lean` models signed counters, input novelty, strict wake,
provider/dispatch order and history control. Selected properties prove duplicate
input does not rearm, deadline equality does not wake, and provider failure
halts before dispatch/history. Source: `src/loop.metta` initialization and
iteration body; `src/memory.metta` history conditions. The observed dispatch
action means selection of a parsed command; it does not assert that an Error
command executes a tool. Context, parsing, results and formatted history entries
are explicit opaque host observations.

The generated replay checks 380 observed control/action projections from both
evaluators, including restarts. New proofs contain no `sorry` or new declared
axioms; standard Lean logical dependencies are printed by the model files.
This proves properties of the executable models and tests correspondence at
that boundary. It is not a full verification of Python, MeTTa, real providers,
arbitrary tool bodies or OS/filesystem behavior.

## Completion and boundaries

The exact command exits zero; its output `qualification.json` records every
required stage, the evaluator digest and the toolchain. Local verification
receipts bind the run to reviewed source digests and are not published. No blocker remains for this
isolated goal. Compatibility is established through the listed adapters,
not by redesigning the engine or changing the reference.

Mode registration, real providers/channels/tools and supervised startup are
implemented by `launch.py`, `runtime_host.py` and the agent host hooks described
above. The native CeTTa LLM client remains later work; credentials continue to
use the existing provider transport. All active code, worktrees, traces and
build outputs remain outside Zahrada.
