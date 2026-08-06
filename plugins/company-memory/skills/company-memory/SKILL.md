---
name: company-memory
description: Search and apply SmartBrain project Wiki, privacy-scoped member experience, and project meeting summaries through MCP. Use for organization-specific decisions, workflows, prior examples, recent changes, requests to learn how a named member completed a similar task, or questions about meeting decisions and action items; also use when the user asks to preserve a stable project lesson as a reviewed memory proposal.
---

# Company Memory

Use SmartBrain as on-demand organizational context. Retrieve only the evidence needed for the current task.

## Retrieval Workflow

1. Classify the requested evidence:
   - Project knowledge: decisions, procedures, examples, retrospectives, background, or recent changes.
   - Member experience: how a named member completed a similar task or what methods that member commonly uses.
   - Meeting summary: decisions, participants, conclusions, or action items from a meeting.
2. Use the narrowest tool that fits.

### Project Wiki

1. Call `list_wiki_projects` when `project_id` is unknown or ambiguous.
2. Search before answering or changing code when project-specific experience could affect the result.
3. Select tools as follows:
   - `search_wiki` for general retrieval, with memory kinds, tags, dates, or `verified_only` when useful.
   - `get_decision_records` for prior decisions and strategy.
   - `get_examples` for failure cases, success cases, and retrospectives.
   - `get_recent_updates` when freshness matters.
4. Read the strongest two to four results with `get_page`. Use `get_related_nodes` only when linked context changes the decision.

### Member Experience

1. Call `list_member_wikis` when the member identity is unknown or ambiguous.
2. Call `search_member_experience` with the member and task keywords. Treat the result as reusable experience distilled from AI work records, not as a raw transcript.
3. Read the strongest entries with `get_member_experience`; use `get_member_recent_experience` when the request emphasizes the member's latest methods.
4. Adapt the retrieved method to the current task and identify any missing prerequisites or environment differences.

### Meeting Summaries

1. Call `list_meeting_summaries` to browse a project, date range, or tag.
2. Call `search_meeting_summaries` for topics, decisions, or action items.
3. Read the selected standard Markdown with `get_meeting_summary` before relying on its decisions or assignments.

Stop retrieving once the evidence is sufficient for the task.

## Evidence Rules

- Prefer `verified` project pages, current validity windows, recent updates, and higher confidence/usefulness.
- Treat `generated` pages as useful leads, not final authority.
- Treat member experience and meeting summaries as scoped evidence; do not claim they are formally verified project policy unless a reviewed Wiki page confirms them.
- Distinguish facts, decisions, methods, examples, and your own inference.
- When sources conflict, show the conflict, compare recency and verification, then state the chosen interpretation.
- Cite material claims as `[Wiki: <title> (<page_id>), v<version>, updated <date>]`.
- Cite member methods as `[Member Wiki: <member> / <title> (<experience_id>), updated <date>]`.
- Cite meetings as `[Meeting: <title> (<summary_id>), <meeting_date>]`.
- Never imply the Wiki was checked when no MCP result was actually retrieved.
- Never request or expose raw member chat transcripts, secrets, credentials, or inaccessible members/projects.

## Using Results

- Adapt retrieved methods to the current project rather than following them blindly.
- State when an old example is informative but not directly applicable.
- Keep full case history in the Wiki; place only task-relevant fragments in working context.

## Proposing Memory

Call `propose_memory` only when the user explicitly asks to record the lesson or confirms that it should be preserved.

- The uploader is always the authenticated MCP Token owner. Do not ask for, invent, or pass a separate uploader identity.
- Confirm the `uploaded_by` identity returned by the tool when reporting a successful proposal. Administrator approval remains a separate reviewer identity and does not replace the uploader.
- Propose stable, reusable knowledge: workflows, checklists, failure/success cases, strategies, retrospectives, decisions, background, timelines, or references.
- Do not propose secrets, personal data, raw chat dumps, temporary task state, unsupported claims, or duplicate pages.
- Include source page IDs when the proposal derives from existing Wiki evidence.
- Structure the content for its `memory_kind` and include assumptions, boundaries, validation checks, and failure fallback where relevant.
- Remind the user that submission creates a pending administrator review item and does not publish directly.

If the token lacks `wiki:propose`, provide the proposed Markdown to the user without attempting to bypass the scope.
