# 历史参考：Sector Rotation Map Design QA

> 这是 2026-07-26 的一次性视觉验收证据，不是当前 Dashboard 运行说明。

- Source visual truth: `C:\Users\jingx\AppData\Local\Temp\codex-clipboard-830c5411-7eb3-4053-a9cb-6d63fdda6e10.png`
- Implementation screenshot: `C:\GoogleDrive\TP\artifacts/dashboard_work\design_qa\sector-rotation-final-focused.png`
- Side-by-side comparison: `C:\GoogleDrive\TP\artifacts/dashboard_work\design_qa\sector-rotation-side-by-side.png`
- Viewport: 1440 × 1000 CSS px; browser capture 1425 × 990 px after scrollbar/chrome exclusion
- Source pixels: 753 × 557
- Focused implementation pixels: 1069 × 778
- Comparison normalization: implementation downscaled to 753 × 557 beside the unchanged source; device scale factor 1
- State: Sector page, US market, 6M trail, light TP dashboard theme

## Findings

No actionable P0/P1/P2 differences remain.

- [P3] Dense center cluster
  - Location: rotation plot around the 100/100 crosshair.
  - Evidence: several sectors finish close together, so short endpoint labels remain visually dense; the source also contains a dense center cluster but fewer series.
  - Impact: users may need to hover when several current points coincide.
  - Follow-up: keep the current short labels and hover isolation; add an optional sector filter only if real use shows this is still slow to scan.

## Required Fidelity Surfaces

- Fonts and typography: uses the dashboard's existing family, optical weights, and hierarchy rather than the source's legacy terminal-like typography. Axis and endpoint labels remain legible at the normalized comparison size; full sector names remain available in hover text and accessible labels.
- Spacing and layout rhythm: the focused component keeps essentially the same landscape proportion as the source. Four quadrants, centered 100/100 baselines, edge labels, axes, legend, and endpoint callouts are aligned consistently. The market and trail controls fit without changing the plot's primary hierarchy.
- Colors and visual tokens: the source's black chart is intentionally adapted to TP's light green visual system. Semantic quadrant colors remain distinct with restrained opacity, and series colors meet the surrounding dashboard's contrast level.
- Image quality and asset fidelity: no source raster asset belongs inside the production component. The analytical plot is rendered as resolution-independent SVG data visualization; there are no placeholder or generated decorative assets.
- Copy and content: bilingual quadrant labels, methodology, benchmark, as-of date, axis labels, and interaction hint are present. Proprietary JdK naming is intentionally not claimed.

## Full-view Comparison Evidence

`sector-rotation-side-by-side.png` shows the source and implementation at equal pixel dimensions. The implementation preserves the source's main information architecture: four semantic quadrants, centered reference lines, multi-period sector trails, emphasized current points, endpoint labels, axes, and legend.

## Focused Region Evidence

The component itself is the focused analytical region, so no additional crop is needed. The equal-size side-by-side comparison keeps axis text, trajectory density, quadrant treatments, and endpoint labels readable enough for judgment.

## Comparison History

1. Initial implementation: US, 12M, full sector names.
   - Finding: [P2] 19 long labels and 12 points per sector created excessive overlap around 100/100.
   - Fix: changed the default trail to 6M, retained a working 12M toggle, replaced endpoint text with stable short sector labels, and preserved full names in hover/accessibility text.
2. Post-fix implementation: US, 6M, short labels.
   - Evidence: `sector-rotation-final-focused.png` and `sector-rotation-side-by-side.png`.
   - Result: no actionable P0/P1/P2 visual issue remains.

## Interaction and Runtime Checks

- US/EU toggle: passed; chart accessible label updated to EU.
- 6M/12M toggle: passed; first trail changed from 6 to 12 realized points.
- Current sector point: passed; clicking the EU Banks endpoint opened the existing `EU Banks 月度分析` drawer.
- Drawer close: passed.
- Browser console errors/warnings: none.
- Responsive behavior: passed at 820 × 900 CSS px; controls stacked vertically, the page had no horizontal overflow, and the plot remained within its scroll container.

## Implementation Checklist

- [x] Use realized trailing returns only.
- [x] Preserve four-quadrant rotation structure.
- [x] Provide US/EU and 6M/12M controls.
- [x] Link current points to the existing monthly analysis drawer.
- [x] Pass backend tests and frontend production build.
- [x] Verify the live 8060 API and rendered bundle.

final result: passed
