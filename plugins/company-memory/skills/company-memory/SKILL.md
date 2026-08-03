---
name: company-memory
description: Search and apply reviewed SmartBrain company memory through the Wiki MCP. Use when a task depends on organization-specific history, decisions, strategies, workflows, checklists, prior failures, successful examples, retrospectives, project background, or recent changes; also use when the user asks to preserve a stable new lesson as a reviewed memory proposal.
---

# Company Memory

Use the Wiki as on-demand organizational context. Do not load or summarize the entire Wiki into the conversation.

## Retrieval Workflow

1. Determine the project. Call `list_wiki_projects` when `project_id` is unknown or ambiguous.
2. Search before answering or changing code when company-specific experience could affect the result.
3. Use the narrowest tool that fits:
   - `search_wiki` for general retrieval, with memory kinds, tags, dates, or `verified_only` when useful.
   - `get_decision_records` for prior decisions and strategy.
   - `get_examples` for failure cases, success cases, and retrospectives.
   - `get_recent_updates` when freshness matters.
4. Read the strongest two to four results with `get_page`. Use `get_related_nodes` only when linked context changes the decision.
5. Stop retrieving once the evidence is sufficient for the task.

## Evidence Rules

- Prefer `verified` pages, current validity windows, recent updates, and higher confidence/usefulness.
- Treat `generated` pages as useful leads, not final authority.
- Distinguish facts, decisions, methods, examples, and your own inference.
- When sources conflict, show the conflict, compare recency and verification, then state the chosen interpretation.
- Cite material claims as `[Wiki: <title> (<page_id>), v<version>, updated <date>]`.
- Never imply the Wiki was checked when no MCP result was actually retrieved.

## Using Results

- Adapt retrieved methods to the current project rather than following them blindly.
- State when an old example is informative but not directly applicable.
- Keep full case history in the Wiki; place only task-relevant fragments in working context.

## Proposing Memory

Call `propose_memory` only when the user explicitly asks to record the lesson or confirms that it should be preserved.

- Propose stable, reusable knowledge: workflows, checklists, failure/success cases, strategies, retrospectives, decisions, background, timelines, or references.
- Do not propose secrets, personal data, raw chat dumps, temporary task state, unsupported claims, or duplicate pages.
- Include source page IDs when the proposal derives from existing Wiki evidence.
- Structure the content for its `memory_kind` and include assumptions, boundaries, validation checks, and failure fallback where relevant.
- Remind the user that submission creates a pending administrator review item and does not publish directly.

If the token lacks `wiki:propose`, provide the proposed Markdown to the user without attempting to bypass the scope.
