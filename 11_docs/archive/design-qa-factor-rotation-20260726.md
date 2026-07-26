# Design QA: Four-Market Factor Rotation Map

- source visual truth path: `C:\GoogleDrive\TP\artifacts/scratch/codex_tmp\factor_rotation_qa\source-rotation-reference.png`
- implementation: `C:\GoogleDrive\TP\09_reports\factor-explorer.html`
- desktop screenshot: `C:\GoogleDrive\TP\artifacts/scratch/codex_tmp\factor_rotation_qa\implementation-desktop-1265x712.png`
- mobile screenshot: `C:\GoogleDrive\TP\artifacts/scratch/codex_tmp\factor_rotation_qa\implementation-mobile-390x844.png`
- combined comparison: `C:\GoogleDrive\TP\artifacts/scratch/codex_tmp\factor_rotation_qa\comparison-source-vs-implementation.png`
- viewport and density: source `755 x 557 px`; desktop `1265 x 712 CSS px`; mobile `390 x 844 CSS px`; density `1x`
- state: STOXX 600, latest `2026-07`, 6-observation trail, dark theme

## Full-View Comparison Evidence

The combined comparison was inspected with both artifacts in one image. The
implementation preserves the reference's four rotation quadrants, centered
100 lines, multi-period colored trails, direction markers, endpoint identifiers,
and latest-position labels. It intentionally adopts the existing TP Explorer
tokens and adds an as-of slider plus 6M/12M trail controls.

## Focused Region Comparison Evidence

The chart and current-position list are readable in the focused desktop crop.
Unlike the reference's overlapping direct labels, the implementation uses
`F1`-`F8` endpoints and a color-linked list containing the complete original
variable names, 12M active strength, 3M strength change, coordinates, and
quadrant. The mobile capture confirms a compact `460 x 390` viewBox followed by
the same full-name list.

## Required Fidelity Surfaces

- Fonts and typography: existing Inter/system/Segoe UI/Microsoft YaHei stack is
  retained; headings, controls, axes, endpoint codes, and dense list text have
  distinct sizes and no negative letter spacing.
- Spacing and layout: desktop uses a chart/list grid; tablet and mobile collapse
  to one column. The chart has stable dimensions and the page has no horizontal
  overflow at either tested viewport.
- Colors and tokens: eight distinct trail colors remain legible in light and
  dark token sets. Semantic quadrant fills and state badges use existing
  positive, warning, negative, and benchmark colors.
- Image and chart quality: the visualization is native vector data rendering,
  appropriate for quantitative paths and axes. No raster placeholder,
  decorative gradient, or fake illustration is used.
- Copy and content: all factor labels in the rotation list use original source
  variable names. The note defines the 100 thresholds and point-in-time policy.

## Interactions And Runtime

- Tested market switching for EU Small, SP500, STOXX 600, and Nasdaq.
- Tested 6M to 12M trails: STOXX 600 changed from 48 to 96 path points.
- Tested historical as-of movement from `2026-07` to `2018-09`.
- Confirmed the legacy performance chart still renders five paths:
  Top, Worst, Benchmark, Top/Worst ratio, and Top/Benchmark ratio.
- Browser console errors checked: none.

## Findings

No actionable P0, P1, or P2 findings remain.

Intentional differences from the reference are acceptable: this is an
RRG-inspired, auditable factor map rather than the proprietary JdK formula; the
TP design system replaces the reference's framed black chart and decorative
factor regions; complete names move to the linked list to prevent occlusion.

## Comparison History

- Iteration 1: mobile evidence grid inherited a `720 px` table minimum and caused
  horizontal overflow. Added `min-width: 0` to the main/evidence grid boundary
  and constrained selects. Post-fix body widths are `338 / 338 px`.
- Iteration 2: the original `960 x 455` chart became too small on mobile and the
  archived method suffix repeated after rebuilds. Added three responsive chart
  geometries and idempotent method construction. Post-fix mobile viewBox is
  `460 x 390`; method suffix count is one.
- Iteration 3: the narrow desktop chart was too tall. Split narrow mobile from
  compact desktop geometry. Post-fix dashboard viewBox is `620 x 430`.

## Follow-Up Polish

- P3: direct hover highlighting between a trail and its list row could improve
  dense-path inspection, but it does not block current use.

final result: passed

