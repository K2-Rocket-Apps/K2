---
name: memory-orchestrate
description: Use when asked to start a new multi-wave K2 Memory build plan, such as "declare a build plan for repo X" or "plan a build against issue 12", i.e. any request to begin the memory.declare_scope lifecycle from scratch.
---

# Memory orchestrate

Declare a new build plan with the `memory.declare_scope` tool through your K2 gateway, then
report it. This skill only declares the plan. It never starts a wave: `memory.declare_scope`
creates a build plan with `status: "declared"`, and waves are started separately from the K2
Memory workspace.

## Steps

1. If the request does not include at least a repo and a description of the scope, ask for both
   and stop. Do not guess a repo or invent a scope summary.
2. Work out the arguments:
   - `repo`: the repository named in the request.
   - `scope_summary`: the full human-readable description of the work. Always pass it.
   - `epic_issue_number`: if the request names an issue number (for example `#12`), pass those
     digits here **and** still pass the full description as `scope_summary`. The issue number
     narrows the scope; it does not replace the summary.
   - `max_waves`: only if the request states an explicit wave cap ("no more than 10 waves").
     Otherwise omit it and let the server apply its default.
   - `context_token_ceiling`: the per-wave context ceiling the request states, or `250000` if it
     states none. Unlike `max_waves`, never omit this field.
3. Call `memory.declare_scope` with `repo`, `scope_summary`, `epic_issue_number` (if parsed),
   `max_waves` (if parsed) and `context_token_ceiling` (always: the parsed value or `250000`).
4. Report the returned `build_plan_id` and the `context_token_ceiling` you used, and tell the
   person the plan is now visible in the K2 Memory workspace, where they can review it and start
   its waves. Do not start a wave yourself and do not offer to run waves from this session.
5. Set a `review_policy` only when the person explicitly asks for one. Never infer or invent it.
   When they do, pass it to `memory.declare_scope` as a compact JSON object matching that tool's
   `review_policy` field, including who authorised it and when.
