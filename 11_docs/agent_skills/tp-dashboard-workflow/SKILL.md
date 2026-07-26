---
name: tp-dashboard-workflow
description: Use this skill for TP system dashboard work in 08_presentation_layer, including UX refactors, root/default route changes, production/results page layout, tabs, drag ordering, pagination, visual density, new signal or model panels, Flask/Dash API payloads, React state, refresh jobs, registry entries, live 8060 verification, stale listener/static bundle triage, and visible dashboard audit.
---

# TP Dashboard Workflow

## Scope

Use this skill for dashboard changes, whether the request is visual/layout, data integration, route/default-entry behavior, or verification of what is actually served.

Primary files:
- `src/presentation_layer/apps/system_dashboard.py`
- `src/presentation_layer/apps/system_registry.py`
- `src/presentation_layer/apps/system_jobs.py`
- `08_presentation_layer/frontend/system_dashboard/src/App.jsx`
- `08_presentation_layer/frontend/system_dashboard/src/styles.css`
- `tests/presentation/test_presentation_layer_entrypoints.py`

## Choose The Path

1. **UX path**: use for page layout, tabs, root route, visual density, drag ordering, pagination, or first-screen behavior.
2. **Payload path**: use for new signal/model/output panels, API routes, dashboard state payloads, registry assets, or refresh buttons.
3. **Verification path**: use when the UI looks stale, the wrong port is served, an API payload is missing, or tests do not prove the visible behavior.

## Verification Audit Path

Use this path when the task is to prove that a dashboard change is actually visible or to debug why the dashboard still looks old.

- Start from the requested visible behavior, then inspect the intended backend insertion point in `system_dashboard.py` and frontend insertion point in `App.jsx`.
- Check `styles.css` only when layout, density, overflow, or visibility is part of the request.
- Confirm `/api/dashboard/state` or the specific API route contains the expected payload fields.
- Confirm `EMPTY_DASHBOARD_STATE`, React state defaults, rendered panels, and backend payloads are aligned.
- Confirm the actual listener on `8060`; do not treat a temporary service on another port as proof.
- Fetch root HTML and referenced `/client/assets/` JS/CSS, then search the served bundle for the expected section text, component marker, or class names.
- Prefer build/API/static checks before browser DOM checks when local browser tooling is flaky.
- Do not mutate production manifests, add broad tests, or refactor components as part of a verification audit unless explicitly requested.

## Implementation Rules

- Identify the authoritative artifact first. Prefer existing parquet/CSV/JSON outputs over recomputation.
- Preserve API payload contracts unless the requested UI cannot be built without a new field.
- Add backend payloads in `system_dashboard.py`; include them in `_dashboard_state_payload()` when the frontend initializes from `/api/dashboard/state`.
- Add refresh job endpoints only when an existing safe command rebuilds the artifact.
- Register assets in `system_registry.py` when they should appear in monitoring.
- Update `EMPTY_DASHBOARD_STATE` before using new frontend data.
- Reuse existing `DataTable`, panel, button, status, and form patterns.
- Keep operational controls and analytical results visually separated.
- Keep layouts dense and scan-friendly; do not build marketing-style sections.

## Verification

Use the smallest set that proves the requested behavior:

```powershell
python -m py_compile src\presentation_layer\apps\system_dashboard.py
python -m pytest tests\presentation\test_presentation_layer_entrypoints.py -q
npm run build --prefix 08_presentation_layer\frontend\system_dashboard
Invoke-RestMethod "http://127.0.0.1:8060/api/dashboard/state"
```

For served UI proof, confirm the actual listener on `8060`, fetch the root HTML, fetch referenced `/client/assets/` JS/CSS, and search for the new section text or class names. Browser DOM checks are secondary when local browser tooling is flaky.

## Known Failure Modes

- UI unchanged: stale `8060` process, stale static bundle, or verification hitting a temporary port.
- Payload missing while files exist: import/bootstrap or path mismatch. Verify with the live API.
- Browser DOM timeout: use build, pytest, API, and static asset checks first.
- Scope creep: do not introduce a new frontend framework or route library unless the current app cannot support the request.

## Reporting

Report:
- path used: UX, payload, or verification
- exact component, route, payload, or asset changed
- validation commands and results
- served port/bundle evidence
- whether fallback routes or compatibility behavior were preserved
- exact next fix if verification evidence fails
