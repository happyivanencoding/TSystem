---
name: tp-manual-git-sync
description: Use this skill when the user asks to sync, commit, or push the TP repository manually, especially with phrases like "同步git" or "同步". It keeps TP sync code/config/docs/small-files only, excludes datasets/caches/run outputs/nested Git metadata, avoids recreating automation, and applies the proven guarded commit/pull-rebase/push flow.
---

# TP Manual Git Sync

## Scope

Use this skill only for manual TP repository sync work in `C:\GoogleDrive\TP`.

Current user preference:
- Sync only when explicitly asked.
- Do not create or restore cron, heartbeat, or background sync automation.
- Sync code, configuration, documentation, and small files only.
- Exclude datasets, caches, run outputs, production input batches, large binaries, and nested Git metadata.

## Workflow

1. Start at the repo root.

```powershell
Set-Location C:\GoogleDrive\TP
git status --porcelain
```

2. If `git status --porcelain` is empty, stop and report that there is nothing to sync.

3. Inspect scope before staging.

```powershell
git status --short
git remote -v
```

4. Stage all changes only after confirming the request is a normal manual sync.

```powershell
git add -A
git diff --cached --name-only
```

5. Reject the sync before commit if staged paths include any blocked category:

- `.parquet`
- `.pkl`
- `.pickle`
- `.log`
- `node_modules`
- `venv`, `.venv`, `.venv_tp`
- `dist`, `build`
- `production_inputs`
- `backups`
- `_quarantine_`
- `artifacts/research/runs/historical` (historical read-only)
- `artifacts/backtests/runs`
- `08_dashboard_analysis/outputs`
- `artifacts/pipeline_runs/notebook_execution`
- `artifacts/scratch/codex_tmp`
- `.git`

6. Reject the sync if any staged file is larger than 50 MB.

7. Commit with a concise message that describes the actual staged change.

8. Rebase before pushing.

```powershell
git pull --rebase origin main
git push
```

Use HTTPS remote and Git Credential Manager if authentication is needed. Do not spend time on SSH key debugging unless the user explicitly asks.

## Verification

After pushing, report:

- current branch
- commit hash
- remote URL
- whether the push succeeded
- any files deliberately excluded or unstaged

Treat `LF will be replaced by CRLF` as a warning, not a failure, unless the command itself fails.

## Failure Rules

- If blocked files are staged, unstage only those paths and re-check the staged set before committing.
- If nested repos appear as gitlinks, stop and explain the risk before moving nested `.git` metadata.
- If `git pull --rebase` conflicts, stop and report the exact conflicted files.
- If the worktree has unrelated dirty changes, keep them unless the user explicitly asks to exclude or revert them.
