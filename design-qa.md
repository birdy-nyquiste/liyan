# Design QA — issue #23 workbench

- Source visual truth: `docs/design/workbench-chenjin.png`
- Rendered implementation: `docs/design/workbench-implementation.png`
- Viewport: 1440 × 640 CSS px, desktop, light mode, Simplified Chinese, authenticated task route, 知言 · 立言 view
- Normalization: source is 2880 × 1280 px at 2× density (1440 × 640 CSS px); implementation is 1440 × 640 px at 1× density. The comparison used the same CSS viewport and crop.
- State: one task with one completed 知言 report; 立言 has no Working Copy yet and its composer is empty.

## Full-view comparison evidence

Both views use the same persistent left rail, unified task header, source/work tabs, vertical 44/56 report/article split, independent workspace regions, quiet neutral surfaces, ink text, muted brass emphasis, and bottom-anchored 立言 composer. The implementation deliberately uses real generated report content and the production `liyan-mark.svg`, rather than copying the reference's example data.

## Focused region comparison evidence

The sidebar, task header, pane boundary, report surface, and composer were readable at the normalized full-view size, so a separate crop was unnecessary. The important small details—official mark, Lucide icon weight, tab underline, divider weight, disabled Send state, muted metadata, report card radius, and brass report heading—were inspected in the paired full-resolution captures.

## Required fidelity surfaces

- Fonts and typography: restrained Chinese serif is used for brand, task, report, and article hierarchy; controls and metadata retain a compact sans-serif treatment. Weight and line height preserve the reference's editorial/workbench distinction.
- Spacing and layout rhythm: major alignment, sidebar width, sticky header height, 44/56 split, quiet dividers, report padding, and bottom composer position match the approved direction. Responsive browser checks cover phone, tablet, and laptop without horizontal overflow.
- Colors and visual tokens: neutral warm canvas, pale gray navigation, deep ink foreground, muted brass emphasis, quiet borders, and restrained state colors are consistent with 沉金. Dark/system modes use the same semantic tokens.
- Image quality and asset fidelity: the official production SVG is used directly. No target imagery or logo was replaced with CSS art, emoji, or a substitute SVG.
- Copy and content: primary Chinese copy is concise and domain distinctions remain explicit: 草稿 is user-facing, Blog Preview is not called public publication, and 结果未知 has no retry action.
- Accessibility and interaction: semantic tabs, menus, dialogs, source/report expansion, visible keyboard focus, mobile drawer navigation, and responsive ordering are covered by component and browser tests.

## Findings

- No actionable P0/P1/P2 visual mismatch remains.
- No actionable P3 mismatch remains. 草稿历史 now opens from the compact document toolbar in a right-side Sheet and restores focus to its trigger when closed.

## Comparison history

1. Initial implementation capture: the 立言 composer appeared near the top of the empty document instead of remaining anchored at the bottom. Classified P2 because it materially changed the document-workspace hierarchy.
2. Fix: the 立言 pane became a full-height flex document surface and the composer group was ordered after the document/history content with bottom auto-spacing and a quiet divider.
3. Post-fix evidence: `docs/design/workbench-implementation.png` at 1440 × 640 shows the composer at the foot of the 立言 pane, aligned with the approved reference. The P2 finding is resolved.
4. Review fix: moved 草稿历史 into the reference-aligned right-side Sheet without displacing the Working Copy or composer. The normalized capture was regenerated after this change.

## Primary interactions and runtime checks

- Tested signed-out introduction, authenticated redirect, persistent shell, mobile drawer, task creation, canonical task URL, task-stage navigation, 44/56 desktop panes, mobile stacking/overflow, generation, explicit 草稿 save/restore, publication Preview, and terminal 结果未知 behavior.
- Browser console errors checked: none.
- Browser workflow result at the time of this report: 14 passed, 1 environment-dependent URL-source test skipped; the dedicated normalized design capture test passed.

final result: passed
