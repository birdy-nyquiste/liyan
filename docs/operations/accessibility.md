# Accessibility and responsiveness

What this release is gated on, stated as thresholds rather than as intentions,
so a release either meets them or does not.

立言阁 is a workbench for a small number of invited writers doing slow, careful
work. That shapes what matters here: long reading, long forms, and a lot of
waiting on work that is running elsewhere. The failures worth gating on are the
ones that make waiting indistinguishable from breakage.

## Thresholds

Each of these is either enforced by a test or checked by hand before release.
Nothing is listed as an aspiration.

| # | Threshold | How it is checked |
| --- | --- | --- |
| 1 | Every disabled control carries the reason it is disabled, as an accessible description | `src/components/accessibility.test.tsx` |
| 2 | Every action can be reached and taken from the keyboard alone | `src/components/accessibility.test.tsx`, `e2e/accessibility.spec.ts` |
| 3 | Focus moves to the work when the phase changes, and stays put through polling | `src/components/accessibility.test.tsx`, `useFocusWhen.ts` |
| 4 | Every panel is a named region a screen reader can list | `src/components/accessibility.test.tsx` |
| 5 | No sideways scrolling at 375, 768, or 1280 CSS pixels | `e2e/accessibility.spec.ts` |
| 6 | A focused control is inside the viewport | `e2e/accessibility.spec.ts` |
| 7 | Every state change a user waits on is announced, not only redrawn | By hand, below |
| 8 | Text contrast meets WCAG 2.1 AA (4.5:1 body, 3:1 large text and controls) | By hand, below |

## Why these and not a score

An automated audit reports what it can measure, and what it can measure is
mostly markup. The failures this product actually has are about time: a 知言 run
takes minutes, a user waits without a pointer on the thing they are waiting for,
and a status that changes silently is a product that appears to have stopped.
That is threshold 7, and no linter finds it.

The two thresholds that are still by hand are there for the same reason. Both
are cheap to check and neither survives being automated badly.

## The disabled-control rule

The workbench disables a lot: 立言 waits for every 知言报告, 保存 Revision waits
for an edit, 删除 waits for a publication to finish, 重试 waits out a backoff the
server owns. Every one of those is a rule a user cannot guess.

A disabled button is also skipped by keyboard navigation, so a reason sitting in
a paragraph beside it is never read out with it. The rule is therefore not "show
the reason" but **`aria-describedby` from the control to the reason**, which is
what the tests assert.

Disabled rather than hidden, throughout. A control that disappears teaches
nothing about how to get it back.

## Checking the two by hand

**Announcements (7).** With VoiceOver on macOS (⌘F5), start a 知言 run and do
nothing. Every transition — 处理中, 已完成, 失败 — must be spoken without moving
focus. What to look for: a status region that is replaced rather than updated
announces nothing, and a `role="alert"` that mounts late is announced twice.

**Contrast (8).** Sample the palette in `apps/web/src/styles.css` with any
contrast checker, in both the default and the dark rendering if one exists. The
places this has gone wrong before are the quiet ones: `.form-hint` grey on white
and disabled button text — which threshold 1 has just made load-bearing, because
a reason nobody can read is not a reason.

## Responsive breakpoints

Two, and they are in `apps/web/src/styles.css`:

- **`max-width: 640px`** — the phone layout. Task areas stack; nothing sits side
  by side.
- **`min-width: 1100px`** — the wide layout, where 来源, 知言, and 立言 can be
  read next to each other.

Between them is the default: one column, comfortable measure. The e2e checks
sample 375, 768, and 1280 because those are the three sides of those two lines.

The measure of an article is capped at `68ch` on purpose. A 立言文章 is meant to
be read, and full-window lines are not.

## What is deliberately not gated

- **A perfect Lighthouse or axe score.** Useful, not a gate: it reports markup,
  and the thresholds above are about behaviour over time.
- **Screen reader support beyond VoiceOver.** The user base is known and small.
  This is a scope decision, and it is the first thing to revisit if that changes.
- **Internationalization.** The workbench is Chinese throughout, by design
  (`CONTEXT.md`). Nothing here is about translating it.
