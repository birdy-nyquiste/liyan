# Domain docs

How engineering skills should consume this repository’s domain documentation when exploring the codebase.

## External product documentation

The external product documentation is the Notion hub [立言阁](https://app.notion.com/p/birdy13/3b94deb05c4b8094b230db72d7eab395?source=copy_link).

It currently contains the product overview, server documentation, and documentation for the secretariat, browser extension, mobile application, and workbench clients.

Use Notion for externally maintained product documentation. Use the local domain files described below for shared terminology and architecture decisions that agents must consult while changing this repository.

## Before exploring, read these

- **`CONTEXT.md`** at the repository root.
- **`docs/adr/`** — read ADRs that affect the area being changed.

If these files do not exist, proceed silently. Do not suggest creating them preemptively. The `/domain-modeling` skill, including when reached through `/grill-with-docs` or `/improve-codebase-architecture`, creates them when terms or decisions are resolved.

## File structure

This is a single-context repository:

    /
    ├── CONTEXT.md
    ├── docs/
    │   ├── agents/
    │   └── adr/
    │       ├── 0001-example-decision.md
    │       └── 0002-another-decision.md
    └── src/

`CONTEXT.md` and `docs/adr/` are created lazily. Their absence at the beginning of the project is expected.

## Use the glossary’s vocabulary

When output names a domain concept in an issue title, proposal, hypothesis, or test name, use the term defined in `CONTEXT.md`. Do not drift to synonyms that the glossary explicitly avoids.

If a needed concept is absent from the glossary, reconsider whether the output is inventing language. If the gap is real, note it for `/domain-modeling`.

## Flag ADR conflicts

If proposed work contradicts an existing ADR, surface the conflict explicitly instead of silently overriding it:

> Contradicts ADR-0007 — but worth reopening because…
