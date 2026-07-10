# Design QA

- source visual truth path: `C:\Users\jingx\AppData\Local\Temp\codex-clipboard-a34c3f5c-79f9-4066-86cf-f270c7e69859.png`
- focused source path: `C:\Users\jingx\AppData\Local\Temp\codex-clipboard-8dfccd30-0872-4cc5-8601-2eb366798e67.png`
- implementation: `C:\GoogleDrive\TP\09_reports\factor-explorer.html`
- implementation screenshot path: unavailable
- viewport: source 2048 x 758; implementation target uses 25% / 75% wide-screen grid
- state: SP500, full sample, evidence mode

## Full-view comparison evidence

The source screenshot was inspected. It shows unused horizontal space around a centered 1580px shell and three wide rows above the plot. The implementation now removes the maximum width, places the four market selectors and those three rows in a 25% left rail, and keeps the verdict, plot, detail rail, and evidence content in the remaining width.

Rendered comparison is blocked because Browser Use does not expose the current `file://` tab and rejects direct `file://` capture. No implementation screenshot is available, so visual fidelity cannot be claimed.

## Focused region comparison evidence

The focused source crop confirms the three groups to move: research coverage stats, candidate/period/mode controls, and candidate KPI cards. Static HTML checks confirm that these groups now appear inside `.sidebar` before `#chart`, but their rendered spacing and wrapping remain unverified.

## Findings

- [P1] Rendered wide-screen layout cannot be verified.
  - Location: `.dashboard`, `.sidebar`, `.main-column`.
  - Evidence: source screenshots are available; implementation screenshot is unavailable.
  - Impact: the 25% rail, two-column metric cards, and plot width may still need visual tuning.
  - Fix: refresh the local report, capture the same wide viewport, and compare it with the supplied source.

## Comparison history

- Iteration 1: identified excessive centered max-width and three horizontal pre-plot rows. Updated the generator to a full-width 25% / 75% layout and regenerated the report. Post-fix visual evidence is blocked.

## Implementation checklist

- [x] Remove the 1580px maximum shell width.
- [x] Move four market selectors to the top of the left rail.
- [x] Move research stats, controls, and KPI cards into the left rail.
- [x] Keep the verdict, plot, explanation panel, and evidence tables in the main column.
- [x] Restore the original stacked layout below 1200px.
- [ ] Capture and compare the rendered wide-screen result.

final result: blocked
