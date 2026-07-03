# TP System Dashboard React Client

React/Vite client for the TP system dashboard job control flow.

It consumes the existing dashboard API on port 8060:

- `GET /api/dashboard/jobs/latest`
- `POST /api/dashboard/jobs/system-checks`
- `POST /api/dashboard/jobs/project`
- `POST /api/dashboard/jobs/pipeline`
- `GET /api/dashboard/jobs/<job_id>/events`

## Local Run

Start the Dash/API backend first:

```powershell
C:\GoogleDrive\TP\.venv_tp\Scripts\python.exe -m presentation_layer.cli system-dashboard --port 8060
```

Then run the React client:

```powershell
cd C:\GoogleDrive\TP\08_presentation_layer\frontend\system_dashboard
npm install
npm run dev
```

Open `http://127.0.0.1:8061/`.
