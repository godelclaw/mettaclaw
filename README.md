## CeTTaClaw

CeTTaClaw is a CeTTa-native port of the PeTTaClaw agent loop. The agent core
stays small and familiar; interpreter-level interfaces remain in CeTTa, while
agent-specific adapters remain here.

### Layout

- `src/` is the PeTTaClaw-shaped agent core plus focused configuration,
  Telegram, LLM, memory, search, and MCP adapters.
- `src/value.metta`, `src/text.metta`, and `src/wire.metta` keep compatibility
  helpers separated by responsibility rather than hiding them in a prelude.
- `runtime/` is the live daemon driver: run lock, bounded child command
  execution, turn commit, pending-send handling, and loop streaming.
- `scripts/` contains offline checks and the out-of-process MCP bridge.
- `CETTA_ROOT` points at a CeTTa checkout that provides the native interfaces
  used by the agent.

### Runtime Model

The live loop runs on a `BUILD=core` CeTTa binary.  Python stays outside the
agent loop behind explicit process or HTTP boundaries:

- ChromaDB memory is served by the localhost memory shim.
- Embeddings are served by the shared embedding daemon.
- MCP uses the bridge CLI in `scripts/` as a subprocess.

The live prompt, history, offset, secrets, and other mutable state are configured
through env files and are not committed to this repo.

### Setup

```bash
./initialize.sh
```

Then edit `config/local.toml` and `config/secrets.env`, or point
`CETTACLAW_SETTINGS` / `CETTACLAW_SECRETS` at existing managed env files.

### Tests

```bash
./run_tests.sh "$CETTA_ROOT/cetta"
```

The suite is offline: no Telegram send, no live offset commit, and no secrets
are printed.

### Running

Import smoke test:

```bash
./run.sh smoketest.metta
```

Live bounded daemon entrypoint:

```bash
./run_live_bounded.sh run_live_session_stream.metta
```

The launcher refuses to run when the configured legacy PeTTaClaw service or a
live CeTTaClaw run lock is active. Live Telegram sends require the launcher-provided
`CETTACLAW_LIVE_SEND_APPROVED=YES_SEND_LIVE_TELEGRAM` gate.
