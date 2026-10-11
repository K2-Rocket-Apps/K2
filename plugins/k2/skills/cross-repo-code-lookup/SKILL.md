---
name: cross-repo-code-lookup
description: Use when you need to find a symbol, trace how two pieces of code relate, assess the blast radius of a change, or answer a project-status question (is a feature built, what does a design spec or build item say, what shipped) about a repository you are not currently working in, or when a memory.* tool you need will not load or returns an unusable result.
---

# Cross-repo code lookup

K2 Memory (the `memory.*` tools, served through your K2 gateway) indexes the repos your
organisation has connected to K2 Memory into a symbol-level graph, alongside a project layer of
design specs, build items, decisions and findings. It answers questions about repos you are
**not** currently inside. Inside your own repo, `Grep` and `Glob` are faster and never stale.

This skill is the protocol for choosing the right tool, in the right order, and for what to do
when a tool is not available.

## Why the protocol matters

A wrong answer that looks valid is worse than an explicit failure, because only the failure is
visible to whoever reads your output next. When a `memory.*` tool is unavailable, report
`UNKNOWN` rather than substituting a local database, a guessed port, or git history: those
sources can return well-formed results that describe a different, unrelated system.

## The protocol

0. **Same-repo question?** Use `Grep`/`Glob`, not a `memory.*` tool, and stop here. Nothing below
   applies inside the repo you are already working in.
1. **Exact symbol name known?** Call `memory.find_symbol` first. It is cheaper than a lexical
   search and the right first move whenever you have a precise name.
2. **No hits, or the name is not known?** Call `memory.search_code_chunks` as the lexical
   fallback.
3. **Blast-radius question?** Call `memory.impact_of` on the resolved symbol. When several symbols
   change together, pass them all in one call through its `targets` parameter rather than making
   one call per symbol.
4. **"How does A relate to B?"** Call `memory.trace_path`.
5. **Project-status question about another repo** ("is X built?", "what does this design spec or
   build item say?", "what shipped, and where?"). Do not reconstruct it from commit history or by
   browsing another checkout. Pick the structured tool that matches the question:
   - `memory.read_build_items` for backlog and status (full-text search with `q`, or an exact
     `id`);
   - `memory.read_design_spec` for the design of record (its build ledger records what actually
     shipped per phase, not just what was planned);
   - `memory.read_decisions` for why something was chosen;
   - `memory.read_findings` for what review already caught;
   - `memory.epic_status` or `memory.plan_status` for a rollup across an epic or plan.
6. **The tool you need is not available** (a deferred tool that will not load, or a tool search
   result you cannot use)? Retry loading it exactly once. If it is still unavailable, report
   `UNKNOWN` and name the step that failed.

If any `memory.*` result reports the target repo as `never_indexed`, say so and stop. Tell the
person to select that repo in the K2 Memory workspace so it gets indexed; do not guess, and do not
substitute another source.

Reading one exact, already-known file in another checkout (a route file, a config file) is still
fine. The anti-pattern is open-ended searching through another repo's history or tracker to answer
a question that a `memory.*` tool answers directly.

## Reading the result

- **Staleness stamp.** Every `memory.*` result carries `indexed_sha` and `indexed_at` for each
  repo it touched. Mention them when the answer depends on recent changes; the index may lag the
  repo.
- **Edge confidence.** Every edge records how it was derived:
  - `static`: parsed directly from source (imports, `new X`, direct calls);
  - `resolved`: inferred by a framework resolver (route string to controller, container binding,
    view include);
  - `heuristic`: a name or string match only. Treat it as a lead, not a fact.
- **Never say "nothing uses this"** when the truth is "no `static` edge was found". Report the
  confidence mix you actually got.
