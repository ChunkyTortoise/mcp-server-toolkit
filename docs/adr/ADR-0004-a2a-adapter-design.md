# ADR-0004: A2A Adapter Design

**Status:** Accepted
**Date:** 2026-04-26
**Deciders:** Cayman Roden

---

## Context

The Google A2A (Agent-to-Agent) protocol defines a standard way for agents to discover each
other and exchange tasks. MCP servers in this toolkit speak MCP natively. Adding A2A support
means four design decisions: which spec version to target, how to map MCP tools to A2A skills,
where to store task state, and whether to implement A2A streaming.

---

## Decision 1 -- A2A Spec Version

**Target google/A2A v0.2 public draft.** Implemented in
`mcp_toolkit/framework/a2a_adapter.py`. The adapter exposes `/.well-known/agent.json`
discovery (via `get_agent_card`) and the task lifecycle: `submitted` → `working` →
`completed` / `failed`.

### Rationale

- **Spec structure is stable**: The core task protocol (task submission, status states, agent
  card format) has not changed since the initial Google I/O announcement. Waiting for a
  numbered stable release would delay the implementation with no concrete benefit.
- **v0.2 draft is the de facto standard**: All known A2A-compatible consumers (Claude, open
  source agent frameworks) already target v0.2 semantics. Targeting an earlier or later draft
  would reduce interoperability.
- **Tradeoff accepted**: Breaking changes in a future v1.0 release may require updating the
  adapter. The surface area is small (one file, two dataclasses, one class) so migration cost
  is low.

---

## Decision 2 -- MCP Tool to AgentCard Skill Mapping

**Map each registered MCP tool name to a `skill.id`; use the tool docstring as
`skill.description`; hardcode `inputModes` and `outputModes` to `["text"]`.**

Two approaches were considered:

**Option A -- Natural-language mapping (chosen):** `skill.id = tool.name`,
`skill.description = tool.description`. Input/output modes hardcoded to `["text"]`.

**Option B -- Schema mapping:** Expose the full MCP JSON schema as the A2A input schema,
mirroring each parameter's type constraints.

### Rationale

- **Target consumers are LLM agents**: A2A consumers reason from natural-language skill
  descriptions, not from parsed JSON schemas. A concise description (`"Search documents by
  semantic similarity"`) is more actionable than a 20-field JSON schema.
- **Simpler implementation**: The natural-language mapping requires one pass over `list_tools()`.
  Schema mapping would require recursive schema translation with no demonstrated payoff.
- **Tradeoff accepted**: Agents cannot programmatically validate arguments against a schema
  before submission. All argument validation happens inside the MCP tool after the A2A task
  is submitted; failures surface as a `failed` task status with the error in `message`.

---

## Decision 3 -- Task State Persistence

**Store task state in an in-process dict (`self._tasks`).** Implemented as
`self._tasks: dict[str, A2ATaskStatus]` on `A2AAdapter`.

Two approaches were considered:

**Option A -- In-memory dict (chosen):** Task state lives in the adapter instance.
Zero infrastructure dependency.

**Option B -- Redis or database persistence:** Task state survives restarts and is
accessible across multiple server instances.

### Rationale

- **Tasks are short-lived**: All 9 pre-built servers execute tool calls synchronously and
  return within milliseconds. No task is in-flight long enough to need durable storage.
- **No cross-instance requirement**: The toolkit is designed for single-instance deployments
  where one MCP server handles one agent session. Cross-instance task lookup has no current
  use case.
- **Infrastructure cost**: Adding Redis dependency would require environment config, health
  checks, and connection management for a feature that has no demonstrated need.
- **Tradeoff accepted**: Task history is lost on server restart. This is a deliberate choice.
  A2A callers that need durable task history should implement their own task store at the
  caller layer. This is documented so future maintainers do not add Redis persistence
  without a concrete driving use case.

---

## Decision 4 -- Streaming Not Implemented

**SSE streaming is not implemented.** `A2ATaskStatus.to_dict()` returns a single terminal
status (`completed` or `failed`) per task. The `capabilities` block in the agent card
advertises `"streaming": True` per spec requirement but no SSE endpoint is wired.

Two approaches were considered:

**Option A -- No streaming (chosen):** All tasks return a complete result in one response.

**Option B -- SSE streaming:** `handle_task` would yield incremental `working` state updates
over a Server-Sent Events connection.

### Rationale

- **No server produces incremental output**: All 9 pre-built servers compute a complete
  result synchronously (LLM call, DB query, web scrape). There is no partial output to
  stream.
- **SSE requires FastAPI/Starlette integration**: Adding streaming would require wiring
  `StreamingResponse` and an event-loop-aware push mechanism. This adds non-trivial
  complexity with no current consumer.
- **Deferred, not rejected**: Streaming is deferred until a pre-built server exists that
  produces incremental output (e.g., a long-running document pipeline). At that point, the
  `handle_task` method can be replaced with an async generator without changing the
  `A2ATaskStatus` data model.

---

## Consequences

- Any A2A-compatible agent can discover MCP servers via `GET /.well-known/agent.json` and
  submit tasks via the task protocol. No MCP-specific knowledge required from the caller.
- Tool implementations do not change. `A2AAdapter` wraps any existing `EnhancedMCP` instance
  without modification.
- Task state is ephemeral. A2A callers that need durable history must persist it themselves.
- Streaming endpoints are absent. A2A callers that require SSE streaming cannot use this
  adapter until streaming is implemented.
