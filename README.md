## MeTTaClaw

<img width="362" alt="image" src="https://github.com/user-attachments/assets/197d745f-1562-4d31-88c2-b813a56ccbf1" />

An agentic AI system implemented in MeTTa, guided by the MeTTaClaw proposal and an agent core inspired by Nanobot.
Beyond basic tool use, it features embedding-based long-term memory represented entirely in MeTTa AtomSpace format.

Long-term memory is deliberately maintained by the agent via `(remember string)` for adding memory items and `(query string)` for querying related memories.
The agent can learn and apply new skills and declarative knowledge through the use of memory items.

In addition, an initial set of OpenClaw-like tools is implemented, including web search, file modification, communication channels, and access to the operating system shell and its associated tools.

Simplicity of design, ease of prototyping, ease of extension, and transparent implementation in MeTTa were the primary design criteria.
The agent core comprises approximately 200 lines of code.

**Special Features**

- MeTTaClaw uses a token-efficient agentic loop, enabling low-cost long-term operation and embodiment in domains that require real-time learning and decision-making.

- The agent can learn to represent its memories in different ways, including such that allow other Hyperon components to operate on the same memories within the same Atomspace. Each memory item is stored as a triplet `(timestamp, atom, embedding)`, while the agent remains flexible in choosing the representation for the atom itself. Consequently, the agent is not hardcoded to any particular memory representation, and different formats can co-exist in the same atom space.

The following example demonstrates learning and decision-making in a textually represented grid-world environment adapted from [NACE](https://github.com/patham9/NACE):

![mettaclaw_in_nace_world](https://github.com/user-attachments/assets/c6c01839-234d-4505-baf6-4f2f3787c7b9)


This project also aims to explore the potential of Agentic Physical AI, a ROS2 package for mobile robots with manipulators is underway.

**Installation**

Prerequisites: [SWI-Prolog](https://www.swi-prolog.org/), a built local
[PeTTa](https://github.com/trueagi-io/PeTTa) checkout (this fork launches PeTTa's
own `run.sh`), and Python 3.11+. Then clone this repository and install the
Python dependencies into the environment PeTTa uses:

```
git clone https://github.com/godelclaw/mettaclaw
cd mettaclaw
pip install -r requirements.txt
./initialize.sh
```

`initialize.sh` creates local, ignored runtime files:

- `config/local.toml` — human-edited paths and ordinary settings (copied from `config/default.toml`).
- `config/secrets.env` — API keys, bot tokens, and Telegram identity or
  authorization IDs; kept mode 600.
- `.env` — generated runtime environment; do not edit directly.
- `memory/prompt.txt` — live identity, seeded from `identity/default-prompt.txt`.

Edit `config/local.toml` if your PeTTa checkout, Python environment,
provider/model, embedding model, memory paths, or channel differ from the
defaults. Put secrets only in `config/secrets.env`:

```
SYNTHETIC_API_KEY=sk-...
METTACLAW_TELEGRAM_BOT_TOKEN=123456789:...
METTACLAW_TELEGRAM_BOT_USERNAME=ExampleBot
METTACLAW_TELEGRAM_OPERATOR_IDS=<telegram-user-id>
```

The LLM provider is any OpenAI-compatible endpoint (default `api.synthetic.new`);
adjust `synthetic_base_url` / `synthetic_model` in `config/local.toml`. The
communication channel defaults to Telegram (set `[channel] kind` to `irc` or
`mattermost` to switch). Long-term memory (`remember` / `query`) is optional and
stays off until you set `embed_model` to a local Qwen3-Embedding-8B path. To use
your own agent identity, edit `identity/default-prompt.txt` before the first
`initialize.sh` (the seed), or `memory/prompt.txt` directly (the live copy).

Successful remembered-memory writes are journaled as dated JSONL records under
the ignored live `memory/` tree. Chroma is the derived similarity-search index.
The journal/index distinction is explicit, but automated index replay is not
implemented yet.

**Running**

Both methods launch from the repository root.

Before publishing, install the repository's public/private boundary check once:

```bash
git config core.hooksPath .githooks
python3 scripts/audit_public_tree.py --history
```

The pre-push hook rejects private runtime paths and any locally configured
credential or Telegram identity found in tracked history. It reports only the
affected path, never the private value.

*Wrapper (recommended).* `run.sh` regenerates `.env` from `config/local.toml`,
sources `config/secrets.env`, initializes runtime files, then starts the agent
loop:

```
./run.sh
```

The loop policy is mutable runtime state, separate from the protected source.
Use `(mode)`, `(modes)`, or `(mode-set "iter")` from the agent, and `/mode`,
`/modes`, or `/mode iter` from an authorized Telegram account. `agent` runs
bounded bursts armed by incoming events or the configured heartbeat; `coding`
keeps that cadence with high reasoning effort; `iter` renews autonomous work
after each 60-second idle boundary; and `iter-coding` composes that renewal with
high reasoning effort. These are ordered presets of named policy fragments,
not separate loops. `(nop)` ends one fast burst while leaving renewal enabled;
`(rest)` explicitly suspends it. The selected mode persists in the ignored
`memory/` state across restarts; the old names `default` and `generic` alias
`agent`, while `claw23` aliases `iter`.

To validate your PeTTa + Python setup without starting the loop, run the
import-only smoke test first — it loads the full library (git-cloning the
`petta_lib_chromadb` dependency into `./repos` on the first run) and exits:

```
./run.sh smoketest.metta        # prints SMOKE_OK and exits
```

*Direct.* After `initialize.sh` has generated `.env`, you can launch PeTTa
yourself in the same configured environment:

```
set -a; . .env; . config/secrets.env; set +a
"$PETTA_ROOT/run.sh" run.metta default
```

**Illustrations**

Long-Term Memory Recall:

<img width="638" height="125" alt="image" src="https://github.com/user-attachments/assets/0d4817ed-e743-4e44-8bd4-a10e27ea6380" />

Tool use:

<img width="1323" height="188" alt="image" src="https://github.com/user-attachments/assets/18ef19c4-010a-4c94-84ce-bb49277dccfc" />

Shell output of the actual invocation of the generated MeTTa code:

<img width="416" height="486" alt="image" src="https://github.com/user-attachments/assets/f5b27205-cdb2-47e7-821a-ffd93b3dd7c6" />

System also added it into its Atom Space storage (embedding vector omitted):

<img width="379" height="69" alt="image" src="https://github.com/user-attachments/assets/6aa59deb-33b4-42b9-a535-ae153b4b7a18" />

## Protected self-modification

The file tools create immutable proposals instead of rewriting the running
agent. A proposal contains the exact candidate bytes, their SHA-256 digest,
the prior target digest, and provenance. MeTTa candidates are parsed by PeTTa's
`top_forms` and `sread` without calling `process_form`. Optional semantic
evaluation runs without network, secrets, a writable host tree, or ambient
home-directory access.

Promotion is a separate operation for a supervisor that has a writable view of
the protected root. The agent runtime should see that root read-only:

```sh
python3 scripts/selfmod_supervisor.py verify PROPOSAL_ID \
  --root PROTECTED_ROOT --store PROPOSAL_STORE
python3 scripts/selfmod_supervisor.py promote PROPOSAL_ID \
  --root PROTECTED_ROOT --store PROPOSAL_STORE
```

Add `--semantic` to require sandboxed PeTTa evaluation. Configure locations
with `METTACLAW_PROTECTED_ROOT`, `METTACLAW_SELFMOD_PROPOSAL_STORE`, and
`PETTA_ROOT`. Optional external governance is enabled only when
`METTACLAW_SELFMOD_REQUIRE_GOVERNANCE=1`; its executable is supplied through
`METTACLAW_GGB_SELFMOD_CLI`.
