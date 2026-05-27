# Subagent Orientation Enforcement (PreToolUse Hook)

**Date:** 2026-05-06
**Status:** Shipped — `mems setup install-hooks`
**Companion plan:** `~/.claude/plans/share-this-password-with-memoized-mitten.md`

## Why

Three documented occurrences of subagents dispatched via the `Agent` tool with **zero `mempalace_*` calls** during code investigations:

| Date | User-wing memory | Pattern |
|------|------------------|---------|
| 2026-04-28 | `user-d51dbc54` | 25 cmds, 17 reads, 0 mempalace |
| 2026-04-29 | `user-2fb9634b` | 12 Bash, 18 Reads, 0 mempalace |
| 2026-05-06 | `user-bb7e5553` (this fix) | 7 Reads, 12 cmds, 0 mempalace |

Each prior fix was procedural — first the snippet at `~/.claude/snippets/mempalace-orientation.md`, then a "prepend this" rule in `~/.claude/CLAUDE.md`. Both rely on the parent agent remembering to inject the snippet at dispatch time. The 2026-04-29 memory (`user-2fb9634b`) called this out verbatim: *"Procedural memory alone is brittle for this class of problem."* The third recurrence on 2026-05-06 confirmed it.

**Root cause** (`user-8d48f38575`): subagents do not inherit `~/.claude/CLAUDE.md`. Anything the parent doesn't put in the prompt is invisible to them. The Memory Palace Protocol that gates the parent's filesystem reads simply does not exist for a subagent.

## What ships

A single Claude Code `PreToolUse` hook on the `Agent` tool, plus a one-shot installer script that matches the existing `scripts/install_<tool>.sh` pattern (cf. `install_cursor.sh`, `install_codex.sh`).

```
integration/claude_code/pretooluse_agent_orientation.py   # the hook
scripts/install_claude_code.sh                             # one-shot installer
tests/test_pretooluse_agent_orientation.py                 # 17 cases
```

### Hook contract

The hook reads a JSON payload on stdin (per Claude Code's hook contract), inspects the `Agent` tool call, and writes either an empty stdout (approve) or a `{"decision": "block", "reason": "..."}` body. It is **read-only** — it never calls `mempalace_*`, so it cannot loop on itself.

### Decision logic

`decision = "block"` iff ALL are true:

1. `hook_event_name == "PreToolUse"` and `tool_name == "Agent"`.
2. `tool_input.subagent_type` is unset OR is one of `Explore`, `general-purpose`. Other agent types (`feature-dev:*`, `code-simplifier`, etc.) cannot call `mempalace_*` regardless, so blocking them is pointless friction.
3. The prompt looks like a code task — contains a code keyword (`code`, `file`, `function`, `bug`, `fix`, `refactor`, `test`, `debug`, `implement`, `investigate`, `trace`, …) OR a path-like token (`\b(\w+/)+\w+\.(ts|tsx|js|jsx|py|java|go|rs|md|yaml|yml|json|sh)\b`).
4. The prompt does NOT contain the literal `Memory Palace orientation` heading or any `mempalace_search`-class API mention.
5. The prompt does NOT contain `# skip-mempalace-orientation` (the explicit opt-out).

Block message:

> Subagent prompt is missing the Memory Palace orientation block. Prepend the contents of `~/.claude/snippets/mempalace-orientation.md` (with `{{wing}}` and `{{drawer_count}}` filled in) before dispatching. If this subagent intentionally does not need mempalace, add the literal token `# skip-mempalace-orientation` anywhere in the prompt to override.

### Distinct from the doom-loop anti-pattern

`feedback_mempalace_hook_doom_loop` warns against `UserPromptSubmit`/`Stop` hooks that **call mempalace** during the user-prompt cycle. This hook only **inspects outbound `Agent` tool args** and never invokes `mempalace_*`. No loop surface. The two are disjoint.

## How to install

From the mems repo root:

```sh
./scripts/install_claude_code.sh
```

Backs up `~/.claude/settings.json` to `settings.json.bak.<UTC-timestamp>` before any change. Idempotent — re-running on an already-installed config is a no-op (skip message). The script is bash + a small Python heredoc for the JSON merge (jq + nested arrays would be brittle).

## Verifying it works

After installing, in a fresh Claude Code session ask the parent to dispatch a code-task subagent without orientation, e.g. *"use Explore to find every TODO comment in `mems_cli/`"*. The hook should block; the message above appears in the agent's output. Re-ask with *"include Memory Palace orientation in the prompt"* — passes.

For the negative cases: a non-code Explore (*"summarize this article"*) and a `feature-dev:*` dispatch both pass cleanly.

## Out of scope (for follow-ups)

- **Auto-prepending the orientation block.** `PreToolUse` hooks return allow/deny; they don't rewrite tool args. We use block-with-message instead.
- **Parent-level enforcement** (PreToolUse on `Read`/`Glob`/`Grep` checking that mempalace was called recently). Different problem; high doom-loop risk; the parent has CLAUDE.md visible at all times — keep that loop procedural.
- **Tunnel injection on cross-repo signals.** Issue M3 from `2026-04-19-protocol-audit.md`; tracked separately.

## References

- Plan file: `~/.claude/plans/share-this-password-with-memoized-mitten.md`
- Snippet the hook validates against: `~/.claude/snippets/mempalace-orientation.md`
- Prior audit: `docs/superpowers/2026-04-19-protocol-audit.md`
- User-wing memories: `user-d51dbc54`, `user-2fb9634b`, `user-d123d479` (decision), `user-bb7e5553` (observation)
