# RegDash — Regression & Cloud Health Dashboard

RegDash is a lightweight Flask app used by the NSP automation team to monitor
daily regression runs and the health of the OpenStack clouds they depend on.
It aggregates the last 24‑hour window (10:00 → 10:00 IST) and provides a rich UI
with trend charts for the previous seven days.

![Dashboard preview](docs/dashboard.png) <!-- optional screenshot if available -->

---

## Features

- **Time-window selector:** Pick any of the last seven 24‑hour windows. KPI tiles,
  the status doughnut, failure bar chart, and cloud waffle tiles update instantly.
- **Cloud health trends:** Dedicated charts for `blr-cloud4` and `blr-cloud5`
  show rolling seven‑day pass percentage.
- **Interactive cards:** KPI tiles and chart cards include hover states and
  gradients for quick visual scanning.
- **Failure drill-down:** Display failure buckets for the active window and link
  into `/details` to see the runs behind each reason.
- **JSON ingest endpoint:** Drop real run data into the dashboard via `/ingest/json`.
- **Seed helpers:** Quickly demo the UI with synthetic data using CLI commands.

---

## Tech Stack

- **Flask 3 / Python 3.11+**
- **SQLAlchemy** with SQLite (default) or any SQLAlchemy-supported DB.
- **Bootstrap 5 + custom CSS** for layout.
- **Chart.js** for doughnuts, bars, and line charts.

---

## Getting Started

### 1. Create & activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt   # if present
# or manually:
pip install flask flask_sqlalchemy pytz
```

### 3. Configure environment variables *(optional)*

```bash
export FLASK_APP=app.py
export LOG_BASE_URL="https://logs.example.com/request/"
export DATABASE_URL="sqlite:///regdash.db"
```

### 4. Initialize & seed the database

```bash
flask reset-db        # drops & recreates tables (use carefully)
flask seed-week       # seeds seven distinct days of demo data
# or for a single-day snapshot:
# flask seed-demo
```

### 5. Run the dev server

```bash
flask run
```

Visit <http://127.0.0.1:5000/> to see the dashboard.

---

## Data Model Summary

`Run` represents a single regression request:

| field        | description                              |
|--------------|------------------------------------------|
| request_id   | unique ID (doubles as log link slug)     |
| scheduler    | e.g., `BLR-NSP-SCHEDULER1`               |
| cloud        | `blr-cloud4`, `blr-cloud5`, etc.         |
| started_at   | UTC timestamp (converted from IST input) |
| ended_at     | optional UTC timestamp                   |
| status       | `PASSED`, `FAILED`, `KILLED`, ...        |
| reason       | failure bucket                           |
| subreason    | detailed failure text                    |
| notes        | free-form comments                       |

---

## JSON Ingest API

`POST /ingest/json` with an array of runs:

```json
[
  {
    "request_id": "1761291703",
    "scheduler": "BLR-NSP-SCHEDULER1",
    "cloud": "blr-cloud4",
    "started_at": "2025-10-24T10:05:01",
    "ended_at": "2025-10-24T11:20:13",
    "status": "FAILED",
    "reason": "Stack Creation Failed",
    "subreason": "Helm install failed",
    "notes": "optional notes"
  }
]
```

On success, records are inserted/updated and you are redirected to `/details`.

---

## CLI Helpers

| Command          | Description                                             |
|------------------|---------------------------------------------------------|
| `flask reset-db` | Drop all tables and recreate them (use with caution).   |
| `flask seed-demo`| Seed ~110 runs for the active 24‑hour window.           |
| `flask seed-week`| Seed seven distinct days with varying pass/fail ratios. |

---

## Roadmap Ideas

- Authentication (Flask-Login / OAuth) for multi-user control.
- Export reports (PDF/CSV) for the selected window.
- Additional trend charts per failure reason or scheduler.
- Integrate real OpenStack quota metrics alongside regression results.

---

## License

MIT (or update with your license of choice).
