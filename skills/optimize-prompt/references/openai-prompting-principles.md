# OpenAI Prompting Principles

Source: [Prompting | ChatGPT Learn](https://learn.chatgpt.com/docs/prompting)

Use this reference as a concise baseline for prompt optimization. If the user asks for the latest official guidance itself, refresh the source through the OpenAI documentation workflow rather than treating this summary as current evidence.

## Core model

OpenAI's guide does not require technical syntax or a universal template. Start in the user's own words and include only the parts that help:

- **Goal:** what ChatGPT should produce or change.
- **Context:** information and sources that can affect the result.
- **Output:** desired format, length, detail, audience, or intended use.
- **Boundaries:** what must stay unchanged, what to avoid, and what requires confirmation.

Use these as a diagnostic checklist, not mandatory headings.

## Optimization principles

1. Describe the result before prescribing the process.
2. Add only context that can change the answer, and say what each source is for.
3. Point to relevant files, images, connected sources, or current web sources when the task depends on them.
4. Use a small number of boundaries aimed at real failure modes.
5. Explain how the result will be used so length and organization fit the audience.
6. Ask for a final check when completeness, ownership, dates, citations, or consistency matter.
7. Prefer follow-up refinement over trying to encode every possible correction in the first prompt.

## Surface-specific application

### Chat

Optimize for direct questions, explanations, drafts, comparisons, plans, and everyday decisions. Usually one outcome plus the few details that change it is enough.

### ChatGPT Work

Use when the task draws on several sources or tools, changes files, follows multiple steps, or produces a substantial reusable deliverable. Name the source material, audience, deliverable, and review boundary. Require approval before sending, publishing, or changing information relied on by others.

### Codex

Name the behavior to understand or change, point to relevant code or reproduction evidence, preserve important constraints, and state how the work should be verified. For changing repositories or GitHub state, require current-state inspection rather than relying on remembered branch, PR, review, or CI status.

## Avoid over-prompting

- Do not add empty sections merely to fill a framework.
- Do not prescribe every search or reasoning step when the outcome and boundaries are sufficient.
- Do not request hidden chain-of-thought.
- Do not add a role persona unless domain framing meaningfully improves the result.
- Do not turn optional polish into required scope.
