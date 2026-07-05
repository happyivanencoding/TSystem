---
name: tp-senior-engineer-task-execution
description: "Use this skill for TP coding tasks where the user expects senior-engineer discipline: clarify scope before coding, locate exact insertion points, make minimal contained changes, verify side effects, preserve dirty worktree changes, and deliver a file-by-file summary in Chinese."
---

# TP Senior Engineer Task Execution

## Scope

Use this skill as the execution discipline for TP repository work. It is not a domain skill by itself; combine it with the relevant TP skill for dashboard, pipeline, backtest, regime, country, or Score ML work.

## Required Procedure

1. Clarify the objective in one concise paragraph before editing.
2. Inspect current files and runtime state instead of relying on memory.
3. Identify exact files and insertion points.
4. Explain why each touched file is necessary.
5. Make the smallest change that satisfies the objective.
6. Do not refactor, add abstractions, add logging, or add tests unless needed for the request or risk.
7. Preserve user or prior worktree changes; never revert unrelated dirty files.
8. Verify with the narrowest commands that prove the requested behavior.
9. Summarize modified files, assumptions, and residual risks in Chinese.

## Preferred Tools

- Use `rg` or `rg --files` for search.
- Use `Get-Content` for focused reads on Windows.
- Use `apply_patch` for manual edits.
- Use parallel reads when inspecting independent files.
- Use repo-native commands and existing scripts before writing new tooling.

## Verification Standard

Choose evidence that matches the scope:
- Frontend dashboard: `npm run build`, targeted pytest, live API/static asset check against `8060`.
- Python pipeline: targeted module command, manifest inspection, output row/date validation.
- Backtest/report: generated run artifacts, summary JSON/CSV, final report/chart existence.
- Data update: canonical parquet row/date checks and manifest status.

Green tests alone are not enough if they do not cover the requested behavior. API checks alone are not enough if the user asked about visual UI. Static bundle checks are acceptable fallback when browser DOM tooling is flaky.

## Dirty Worktree Rules

- Read before editing files that are already modified.
- Ignore unrelated dirty files.
- Do not run `git reset --hard`, `git checkout --`, or destructive cleanup unless the user explicitly asks.
- When generated outputs change, distinguish intentional outputs from unrelated existing churn.

## Delivery Format

Respond in Chinese. Keep the final answer concise:
- what changed
- files modified
- verification commands and results
- assumptions or risks

Do not tell the user to copy files; the user shares the same workspace.
