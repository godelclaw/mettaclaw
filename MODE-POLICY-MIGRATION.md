# One Kernel, Three Policies: Goal, Proof Plan, and Migration

## 1. Status vocabulary

This document distinguishes four states:

- **LIVE** — running in the deployed agent.
- **CODE** — implemented and tested on a development branch, but not deployed.
- **LEAN** — represented by a checked Lean theorem.
- **PROPOSED** — a design or proof obligation, not yet implemented or proved.

Passing one state does not imply another. In particular, a Lean model is not a
runtime conformance result, and development code is not a live deployment.

## 2. Honest present state

| Artifact | State | Evidence | Missing |
|---|---|---|---|
| Stable PeTTa service and historical modes | **LIVE** | Clean deployment, channel and cognition health, semantic memory, watchdog | None for the current baseline |
| One append-only causal ledger and reconstructible working capsule | **CODE** | [`224e525`](https://github.com/godelclaw/mettaclaw/commit/224e525) | Supervised live dogfood |
| Consumed-frontier decision receipts and exactly-once effects | **CODE** | [`ff8ccb2`](https://github.com/godelclaw/mettaclaw/commit/ff8ccb2) | Supervised live dogfood and model-to-code trace audit |
| Data records for burst budget, idle wait, renewal, and reasoning | **CODE** | [`77edc60`](https://github.com/godelclaw/mettaclaw/commit/77edc60) | These are timing records, not full cognitive policies |
| Digest-bound safe recycle and atomic consumption | **CODE** | [`6557fd0`](https://github.com/godelclaw/mettaclaw/commit/6557fd0), [`3c8e528`](https://github.com/godelclaw/mettaclaw/commit/3c8e528) | Supervised process-level dogfood |
| Syntactic repeated-error/action/ping-pong observation | **CODE** | [`01a0837`](https://github.com/godelclaw/mettaclaw/commit/01a0837) | Calibration on real traces; no automatic control intended |
| Weakest sound commit and promotion gates | **LEAN** | `MinimalKernel.canonical_gate_is_weakest_sound`, `canonical_promotion_gate_is_weakest_sound` | Runtime conformance |
| Protected Iter/PettaClaw/Coding composition components | **LEAN** | `ProtectedPlasticity`, `CodingAgent`, `VerifiedFrontier` | One parameterized policy semantics |
| Five-coordinate `Policy` and real `agent/iter/coding` runtime policies | **PROPOSED** | Sections 4–8 below | Definitions, proofs, code, trials, deployment |

The development branch is an evidence-bearing prototype. It is not the target
kernel. Its ledger, receipts, recycle handshake, and observer made distinct
failure classes explicit enough to test; the next architectural step is to
compress those discoveries into fewer mechanisms and delete the scaffolding.

The earlier “82%” estimate described completion of the bounded development
checkpoint, not the full three-policy programme. Relative to the complete goal
in this document, the current overall state is approximately **32%**: much of
the failure evidence and component theory exists, while kernel compression,
policy unification, legacy equivalence, runtime conformance, and empirical
comparison remain.

## 3. Final goal

Build the most permissive agent architecture consistent with coherent causal
execution:

1. one intake path;
2. one append-only event log;
3. one deterministic projection mechanism;
4. one controller invocation path;
5. one tool/effect path;
6. one causal commit gate;
7. one quiescence test;
8. one protected candidate-promotion boundary;
9. three replaceable policies: `agent`, `iter`, and `coding`.

Policies may use every available tool and propose arbitrary changes to
developmental state, context handling, memory handling, or policy code. The
kernel restricts only externally committed effects and replacement of the
last-known-good runtime. There is no per-policy capability allowlist.

### Architectural compression rule

The target is three small mechanisms, not a catalogue of safeguards:

```text
Core       = append event + fold log + commit proposal
Policy     = view and continuation functions supplied to the fold
Supervisor = stage candidate + promote digest + restore last-known-good
```

Everything else is outside the kernel:

| Concern | Proper location |
|---|---|
| Frontier freshness | One predicate of `commit`, derived from the log |
| Exactly-once effect | The same `commit` predicate over semantic effect keys |
| Stuck signal | Read-only observer fold over events |
| Safe process recycle | External supervisor protocol |
| Memory index | Rebuildable cache/projection of durable events and artifacts |
| Telegram or another channel | Adapter that appends inputs and realizes committed effects |
| Mode selection | Policy revision event, interpreted by the common fold |

A proposed kernel change must replace duplicated machinery or express a law
that cannot be derived from the existing fold and commit predicate. New
observers may be added without kernel authority. Process-lifecycle protection
may be added to the supervisor without becoming cognitive semantics. The
migration should reduce independent mutable stores and control paths at every
phase; otherwise it has failed even when its tests pass.

### Mutability boundary

The current development prototype hard-codes receipt and effect validation in
ordinary source. The running service cannot rewrite that source, and the full
self-directed candidate workflow has not yet completed dogfood. In this sense,
the current prototype is less plastic than the target.

The target separates immediate development from constitutional amendment:

| Coordinate | Ordinary agent revision | How it becomes live |
|---|---|---|
| Context projection, memory query, advertised tools, cadence | Immediate ledger transformation | Next causally fresh projection |
| Policy parameters and developmental policy code | Stage and run as an experiment | Successful observation under the current kernel |
| Commit law or other kernel code | Arbitrary candidate proposal is permitted | External-authority, digest-bound probation and atomic promotion |
| Supervisor/promotion authority | Not writable by the candidate it judges | Separate operator or higher-level governance revision |

The kernel is therefore not immutable forever. It is only non-self-amendable
in the same causal act whose validity it judges. The agent may propose any
replacement, inspect its trial, learn from failure, and propose another. It may
not replace the judge and certify that replacement with the replaced judge's
authority in one step.

This is a temporal and causal separation, not a capability restriction. The
required implementation goal is to make candidate creation and observation as
ergonomic as an Iter transformation while retaining a last-known-good runtime
outside the candidate.

## 4. Common operational kernel

Every policy executes the same transition:

```text
accept input events
  -> append stable event identities
  -> derive the current frontier
  -> project a policy view
  -> invoke the controller on that exact view
  -> issue a decision receipt
  -> reject the decision if its frontier or policy revision is stale
  -> commit fresh effects under semantic idempotency keys
  -> append observations
  -> evaluate quiescence under the selected policy
```

The durable event log is canonical. Runtime state is a deterministic projection:

```text
State           = fold policyRevision eventLog
SupervisorState = liveDigest × lastKnownGoodDigest × optionalCandidate
```

Frontiers, committed effect keys, attention, life rhythm, developmental state,
and working capsules are projections, not separate authorities. Rebuildable
indexes may cache projections but cannot contradict the log. The policy does
not mutate state directly: it proposes decisions and developmental candidates;
the core or supervisor commits them.

### Kernel laws

The final implementation must preserve these laws for every policy:

1. accepted input is represented once by a stable identity;
2. a controller receipt binds the exact frontiers, projected-context digest,
   controller revision, and policy revision supplied to the invocation;
3. changed input, context, controller, or policy invalidates an old receipt;
4. an effect key commits at most once even if syntax or delivery is replayed;
5. pending human input preempts autonomous continuation before commit;
6. finite autonomous work reaches a quiet point;
7. verified knowledge requires an observation receipt;
8. arbitrary candidate code may be staged without replacing the live image;
9. only an external-authority, digest-bound promotion may replace the
   last-known-good image;
10. validation infrastructure failure preserves the running image and is not a
    semantic rejection of the candidate.

## 5. Minimal policy record

### Proposed Lean interface

```lean
structure Policy (Event Log View State Proposal : Type) where
  wake       : Event → State → Bool
  project    : Log → State → View
  continue   : State → Bool
  quiescent  : Log → State → Prop
  learn      : Log → State → List Proposal
```

The executable version uses booleans or decidable witnesses; the proposition
`quiescent` specifies what the executable completion check must mean.

These five coordinates are provisional until the irredundancy work in Section
9 is complete. A field is retained only if erasing it loses an observable
desideratum that cannot be recovered from the other four.

### Policy-independent data

Reasoning effort, model identity, heartbeat interval, and burst budget are
parameters. They are not architectures. Tools, memory storage, channels,
effect commitment, and candidate promotion remain common services.

## 6. Three target policies

| Policy | Wake and view | Continuation and completion | Learning target |
|---|---|---|---|
| `agent` | Human/channel events or configured heartbeat; relationship, goals, present working capsule, relevant memory, recent receipts | Bounded event-armed life rhythm; human input preempts; explicit rest is sovereign; quiet after budget or rest | Memories, goals, skills, and staged developmental proposals |
| `iter` | Events, heartbeat, or due experiment; common view after an ordered replayable transformation fold | Continue while an admitted transformation has an unobserved consequence; quiet when inputs and experiments are observed | Staged context, memory, tool, and policy transformations |
| `coding` | Task, correction, or follow-up; task capsule, repository state, acceptance criteria, exact tool receipts, unresolved failures | Inspect, act, observe, revise; final answer only after required evidence; correction steers the active episode | Code, tests, artifacts, and compact evidence-backed lessons |

Iter transformations are ledger events, not a second hot-loader or hidden
filesystem ordering rule. A transformation may change the projected context or
stage a new policy revision. It cannot silently rewrite the kernel that judges
promotion.

## 7. Removing the historical modes without losing their properties

The final operator interface displays only `agent`, `iter`, and `coding`.
`default`/`generic` and `claw23` are removed after migration. Their observable
properties are first preserved as parameterized traces and regression oracles,
not as permanent public aliases.

### Historical behavior to preserve

| Historical mode | Observable law | New representation |
|---|---|---|
| `default` | 50-step bounded event-armed burst; no timed autonomous renewal | `agent` with `budget = 50`, heartbeat-only rearming, ordinary reasoning |
| `generic` | Exact alias of `default` | Stored state migrates once to `agent` |
| old `coding` | Same lifecycle as `default`; high reasoning override | Compatibility oracle for `coding` before its task semantics are enabled |
| `claw23` | 50-step burst; after exhaustion a 60-second wait may renew autonomy; explicit rest prevents renewal | `agent` with `budget = 50`, `heartbeat = 60s`, timed renewal enabled, sovereign-rest flag |

### Required Lean preservation theorems

Add `PolicyKernel.lean` with a legacy semantics and an observable trace
projection. The following are release gates:

```lean
theorem default_agent_trace_equiv
theorem generic_migration_is_default_stutter
theorem old_coding_schedule_equiv
theorem claw23_agent_cadence_trace_equiv
theorem migrated_explicit_rest_remains_sovereign
theorem policy_migration_preserves_external_effect_trace
```

Trace equivalence observes model-invocation opportunities, waits, wake origin,
rest, accepted human inputs, committed effects, and quiet points. It does not
require internal JSON records to be syntactically identical.

After these theorems and executable differential tests pass, stored historical
names are atomically migrated to policy records. The old names are then removed
from `/modes` and from accepted mode commands. No behavior is silently mapped
to `iter`: `claw23` is a cadence, not Iter's transformation semantics.

## 8. Lean synchronization contract

Formal work lives in the public
[`lean/pettaclaw`](https://github.com/godelclaw/MeTTapedia/tree/formal/verified-frontier/lean/pettaclaw)
development branch. Runtime work lives in the public
[`feature/single-kernel-multimodal-20260814`](https://github.com/godelclaw/mettaclaw/tree/feature/single-kernel-multimodal-20260814)
branch.

Each runtime change carries a conformance test named after its Lean obligation.
A theorem may precede code; code may not be called conformant merely because a
similar theorem exists.

### Existing checked foundations

| Requirement | Existing checked result |
|---|---|
| Exact controller request | [`MinimalKernel.invocation_consumes_current_projection`](https://github.com/godelclaw/MeTTapedia/blob/formal/verified-frontier/lean/pettaclaw/MinimalKernel.lean) |
| Frontier change invalidates receipt | `MinimalKernel.changed_consumed_frontier_invalidates_old_receipt` |
| Exactly-once semantic effect | `MinimalKernel.semantic_effect_key_is_exactly_once`, `same_key_replay_is_rejected` |
| Weakest permissive sound commit | `MinimalKernel.canonical_gate_is_weakest_sound` |
| Fail-alive protected promotion | `MinimalKernel.infrastructure_failure_preserves_last_known_good`, `canonical_promotion_gate_is_weakest_sound` |
| Bounded quiet point and human preemption | `MinimalKernel.pending_human_preempts_autonomy`, `finite_budget_reaches_quiet_point` |
| Evidence barrier | `MinimalKernel.evidence_admission_preserves_closure`, `evidence_erasure_permits_silent_false_success` |
| Observable bounded stagnation | `MinimalKernel.bounded_nonprogress_becomes_observable`, `counter_erasure_hides_every_finite_stagnation` |
| Ordered transactional Iter transformations | [`IterArchitecture.failed_transformation_is_transactional`](https://github.com/godelclaw/MeTTapedia/blob/formal/verified-frontier/lean/pettaclaw/IterArchitecture.lean), `transformation_order_observable` |
| Arbitrary protected development | [`ProtectedPlasticity.arbitrary_iter_boundary_development_is_protected`](https://github.com/godelclaw/MeTTapedia/blob/formal/verified-frontier/lean/pettaclaw/ProtectedPlasticity.lean), `run_preserves_kernel` |
| Conservative Iter and life projections | `ProtectedPlasticity.development_projection`, `life_projection` |
| Coding action/evidence barrier | [`CodingAgent.cannot_resample_while_awaiting`](https://github.com/godelclaw/MeTTapedia/blob/formal/verified-frontier/lean/pettaclaw/CodingAgent.lean), `resolve_change_requires_authorized_success`, `every_trace_is_audited` |
| Iter preparation cannot grant execution authority | `CodingAgent.iter_preparation_preserves_execution_authority` |
| Coding composes with protected life | `CodingAgent.hosted_coding_preserves_kernel_and_life`, `coding_and_life_commute` |
| Pending-input steering and quiescent commit | [`VerifiedFrontier`](https://github.com/godelclaw/MeTTapedia/blob/formal/verified-frontier/lean/pettaclaw/VerifiedFrontier.lean) |
| Mandatory context survives retrieval | [`ContextAttention.assembly_preserves_required_facts`](https://github.com/godelclaw/MeTTapedia/blob/formal/verified-frontier/lean/pettaclaw/ContextAttention.lean), `retrieval_cannot_rewrite_mandatory_context` |

### Missing formal deliverables

1. **`EventKernel.lean`** — one event type, append, fold, derived frontier and
   effect projections, and the single commit predicate. Prove the existing
   decision, attention, knowledge, and progress structures are conservative
   projections or observers of it.
2. **`PolicyKernel.lean`** — the parameterized policy interface, common step,
   observable traces, policy-revision receipt field, and legacy semantics.
3. **Legacy preservation** — all six equivalence theorems from Section 7.
4. **Agent adequacy** — origin-sensitive arming, sovereign rest, finite quiet,
   and present-moment continuity under the new policy semantics.
5. **Iter adequacy** — exact ordered transformation projection, transactional
   failure, candidate staging, and observation-before-continuation.
6. **Coding adequacy** — request snapshot, broker-only workspace change,
   evidence-bearing completion, cancellation, and correction steering.
7. **Mixed-trace projection** — erasing policy-specific coordinates recovers
   the corresponding source-policy trace, while kernel events remain shared.
8. **Runtime refinement map** — decode each event-log record into the Lean
   event type and prove the tested transition table matches the model.

## 9. Weakness and minimality programme

No global claim of smallest source code or uniquely minimal architecture is
planned. The formal target is:

1. the weakest sound commit gate;
2. the weakest sound promotion gate;
3. observational irredundancy of each retained state or policy coordinate.

The first two are already proved in `MinimalKernel`. The policy record requires
new erasure witnesses:

| Erased distinction | Required counterexample |
|---|---|
| Policy revision in receipt | A decision sampled under one policy commits after a policy switch |
| Wake origin | Human and autonomous events become indistinguishable where arming semantics differ |
| Finite continuation budget | An autonomous trace has no internally forced quiet point |
| Quiescence/evidence predicate | A final answer is accepted without observing required effects |
| Transformation order | Two transformations produce observably different contexts when permuted |
| Learning/proposal boundary | Developmental candidate bytes become live without probation |
| Last-known-good coordinate | Candidate rejection becomes process death |

A field that has no counterexample is merged with another field or removed.
This is how the architecture remains permissive and small without confusing
brevity with semantic minimality.

## 10. Runtime implementation sequence

### Phase 0 — unattended baseline

For the five-day unattended interval, make no live architectural change. Keep
the stable PeTTa deployment and collect only existing health observations.

### Phase 1 — compress the formal kernel

Implement `EventKernel.lean` and prove the existing frontier, effect, attention,
knowledge, and progress models are projections or observers. Then implement
`PolicyKernel.lean`, the legacy semantics, trace observations, and six
preservation theorems. Check the complete Lean import chain and axiom audit
before runtime refactoring.

### Phase 2 — compress the runtime substrate

Replace per-concern mutable structures with one event fold and one commit path.
Move stuck observation out of the transition core and process recycling into
the supervisor. Make memory indexes explicitly rebuildable. Preserve behavior
with differential traces, then delete superseded code.

Acceptance: fewer authoritative stores and control paths than the development
prototype, with no lost kernel law.

### Phase 3 — schema-only policy refactor

Add the five-coordinate policy record and policy revision to the development
branch. Decode old stored modes into behaviorally identical policy parameters.
Do not yet change controller context or completion behavior.

Acceptance: executable differential traces agree with the legacy model for
`default`, old `coding`, and `claw23`.

### Phase 4 — single parameterized loop

Make the loop depend only on the common kernel and selected policy record.
Eliminate mode-name conditionals. Include the policy revision in decision
receipts so switching policy invalidates pending stale work.

Acceptance: one intake, ledger, projection interface, tool path, effect path,
and completion path; all kernel conformance tests pass for every policy.

### Phase 5 — `agent`

Make `agent` behaviorally equivalent to `default`, with cadence parameters
capable of reproducing `claw23`. Verify human preemption, sovereign rest,
heartbeat behavior, process continuity, and exact external-effect traces.

After supervised dogfood, migrate stored `default`/`generic`/`claw23` values and
remove those names from the operator interface.

### Phase 6 — `iter`

Represent transformations as ordered causal events. Allow them to modify
projected messages, advertised tools, memory queries, and staged developmental
proposals. Require exact observation of a transformation experiment before it
renews itself.

Acceptance: failure is transactional; order is replayable; arbitrary candidates
can be staged; no candidate can rewrite the running promotion authority.

### Phase 7 — `coding`

Replace the current reasoning-only override with a task capsule and explicit
inspect/act/observe/revise state. Require requested acceptance evidence before
completion, and steer rather than restart when corrected mid-task.

Acceptance: no resampling while tool evidence is pending; every workspace
change is broker-mediated; false-success canaries are rejected; final answers
are terminal only after the completion predicate succeeds.

### Phase 8 — supervised probation and promotion

Run candidates outside the live tree. Bind each candidate to exact source,
policy, engine, model, context, and acceptance-test digests. Promote only after
fresh cognition, healthy channels, accessible semantic memory, no duplicate
effects, bounded human responsiveness, and successful task evidence are
observed. Otherwise restore the last-known-good image.

## 11. Empirical policy study

Architecture comparisons use repeated trials from matched starting states.
Model and engine remain fixed while policy is varied; cross-model and
cross-engine studies follow only after policy effects are identified.

### Efficacy

- verified outcome across repetitions;
- false-success and incomplete-scope rate;
- duplicate-effect and stale-decision rejection rate;
- human-message visibility and response latency;
- repeated-error/action and ping-pong observations;
- task completion time, tool calls, context size, and memory usefulness;
- recovery from failed developmental candidates.

### Wellbeing and introspection

- affect trace and confidence as self-report, not ground truth;
- chosen rest versus unintentional silence;
- goal continuity and reasoned abandonment;
- perceived agency, coherence, curiosity, and burden;
- discrimination between injected context and internally proposed content;
- intended versus unintended output;
- confidence calibration against later observations;
- detection of context or memory perturbations;
- intentional strategy changes followed by behavioral verification.

No affect value is initially a hard promotion gate. That would reward reporting
the target value before the measure is validated. Hard gates use observable
safety, liveness, causal freshness, and recoverability.

## 12. Acceptance and completion

The programme is complete only when:

1. the three policies share exactly one operational kernel;
2. historical `default`, old `coding`, and `claw23` traces are reproduced by
   policy parameters before their old names are removed;
3. policy switching cannot commit a decision sampled under the old policy;
4. stale or replayed work cannot duplicate an external effect;
5. pending human input is visible before the next commit;
6. every bounded episode reaches a quiet point without new input;
7. arbitrary developmental candidates can be explored without risking the
   last-known-good image;
8. every code-level invariant has a named Lean obligation and conformance test;
9. repeated matched trials support any change of default policy;
10. the live agent survives supervised probation and rollback drills;
11. the final runtime has fewer authoritative stores and control paths than the
    development prototype, with stuck detection, memory indexing, and recycle
    protection outside the cognitive kernel.

## 13. Primary references

- [`patham9/iter`](https://github.com/patham9/iter) — minimal transformation,
  channel, and tool seed.
- [ReAct](https://arxiv.org/abs/2210.03629) — interleaved reasoning and acting.
- [Reflexion](https://arxiv.org/abs/2303.11366) — feedback-mediated episodic
  learning.
- [SWE-agent](https://arxiv.org/abs/2405.15793) — coding-agent interface and
  repository interaction.
- [tau-bench](https://arxiv.org/abs/2406.12045) — repeated tool-agent reliability
  under policy-constrained interaction.
- [AgentDojo](https://arxiv.org/abs/2406.13352) — agent security evaluation with
  untrusted tool context.
- [Introspective Awareness in Large Language Models](https://arxiv.org/abs/2601.01828)
  — functional probes of internal-state discrimination and control.
- [PettaClaw Lean models](https://github.com/godelclaw/MeTTapedia/tree/formal/verified-frontier/lean/pettaclaw)
  — machine-checked architecture components and counterexamples.
