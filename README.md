# RegDash (Regression Runs & Cloud Portal)

A lightweight Flask dashboard to visualize 24-hour regression runs (10:00 → 10:00 IST),
summaries, failure buckets, and drill-down details. Designed for NSP lab workflows.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install flask SQLAlchemy pytz

export FLASK_APP=app.py
flask init-db
flask seed-demo
flask run
```

Open http://127.0.0.1:5000/

### Environment
- `LOG_BASE_URL` (optional): base URL to build "Open Log" hyperlinks.
- `DATABASE_URL` (optional): SQLAlchemy URL (defaults to local SQLite file).

## Ingesting Real Data

POST JSON to `/ingest/json` with an array like:

```json
[
  {
    "request_id": "1761291703",
    "scheduler": "BLR-NSP-SCHEDULER1",
    "started_at": "2025-10-24T10:05:01",
    "ended_at": "2025-10-24T11:20:13",
    "status": "FAILED",
    "reason": "Stack Creation Failed",
    "subreason": "Helm install Failed",
    "notes": "optional notes"
  }
]
```

## Next Steps

- Add a `/cloud` page for OpenStack project quotas and usage.
- Add `/report/today` to render your exact email format.
- Add authentication (Flask-Login) for user actions.
- Add scheduler/domain filters across pages.
