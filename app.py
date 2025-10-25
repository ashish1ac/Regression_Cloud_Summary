from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from datetime import datetime, timedelta
import pytz
import os

# ----------------------------
# Config
# ----------------------------
APP_TZ = "Asia/Kolkata"
DEFAULT_LOG_BASE_URL = os.environ.get("LOG_BASE_URL", "https://logs.example.com/request/")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///regdash.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ----------------------------
# Models
# ----------------------------
class Run(db.Model):
    __tablename__ = "runs"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.String(32), unique=True, index=True, nullable=False)
    scheduler = db.Column(db.String(128), index=True, nullable=False, default="BLR-NSP-SCHEDULER1")
    cloud = db.Column(db.String(32), index=True, nullable=True)  # "blr-cloud4" | "blr-cloud5"
    started_at = db.Column(db.DateTime, nullable=False, index=True)
    ended_at = db.Column(db.DateTime, nullable=True, index=True)
    status = db.Column(db.String(16), nullable=False)  # PASSED/FAILED/KILLED/etc.
    reason = db.Column(db.String(128), nullable=True)  # failure reason bucket
    subreason = db.Column(db.String(256), nullable=True)  # free-form message
    notes = db.Column(db.Text, nullable=True)

    def to_dict(self, with_links: bool = True):
        d = {
            "request_id": self.request_id,
            "scheduler": self.scheduler,
            "cloud": self.cloud,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "status": self.status,
            "reason": self.reason,
            "subreason": self.subreason,
            "notes": self.notes,
        }
        if with_links:
            d["log_url"] = f"{DEFAULT_LOG_BASE_URL}{self.request_id}"
        return d

# ----------------------------
# Helpers
# ----------------------------
def get_window_bounds(ref_dt_local: datetime = None):
    """Compute 24h window from 10:00 local to next-day 10:00 local."""
    tz = pytz.timezone(APP_TZ)
    now_local = ref_dt_local or datetime.now(tz)
    # Anchor is today's 10:00:01, else yesterday 10:00:01
    ten_am_today = tz.localize(datetime(now_local.year, now_local.month, now_local.day, 10, 0, 1))
    if now_local >= ten_am_today:
        start_local = ten_am_today
    else:
        start_local = ten_am_today - timedelta(days=1)
    end_local = start_local + timedelta(days=1)
    # store/compare as naive UTC in DB
    start_utc = start_local.astimezone(pytz.UTC).replace(tzinfo=None)
    end_utc = end_local.astimezone(pytz.UTC).replace(tzinfo=None)
    return start_local, end_local, start_utc, end_utc

def parse_dt_local(s, fmt="%Y-%m-%d %H:%M:%S"):
    if not s:
        return None
    tz = pytz.timezone(APP_TZ)
    return tz.localize(datetime.strptime(s, fmt)).astimezone(pytz.UTC).replace(tzinfo=None)


def parse_iso_utc(value: str):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo:
        return dt.astimezone(pytz.UTC).replace(tzinfo=None)
    return dt


def resolve_window_from_request():
    """Determine which 24h window to use based on query args."""
    tz = pytz.timezone(APP_TZ)
    start_param = request.args.get("start")
    end_param = request.args.get("end")
    day_param = request.args.get("day")

    if start_param and end_param:
        start_utc = parse_iso_utc(start_param)
        end_utc = parse_iso_utc(end_param)
        if start_utc and end_utc:
            start_local = pytz.UTC.localize(start_utc).astimezone(tz)
            end_local = pytz.UTC.localize(end_utc).astimezone(tz)
            return start_local, end_local, start_utc, end_utc

    if day_param:
        try:
            day = datetime.strptime(day_param, "%Y-%m-%d")
            ref_local = tz.localize(datetime(day.year, day.month, day.day, 12, 0, 0))
            return get_window_bounds(ref_local)
        except ValueError:
            pass

    return get_window_bounds()

# ----------------------------
# Routes (pages)
# ----------------------------
@app.route("/")
def index():
    start_local, end_local, start_utc, end_utc = get_window_bounds()
    q = Run.query.filter(Run.started_at >= start_utc, Run.started_at < end_utc)
    total_runs = q.count()
    status_counts = (
        db.session.query(Run.status, func.count(Run.id))
        .filter(Run.started_at >= start_utc, Run.started_at < end_utc)
        .group_by(Run.status)
        .all()
    )
    status_map = {s: c for s, c in status_counts}
    failures = (
        db.session.query(Run.reason, func.count(Run.id))
        .filter(Run.started_at >= start_utc, Run.started_at < end_utc, Run.status == "FAILED")
        .group_by(Run.reason)
        .all()
    )
    failures = [{"reason": r or "Unknown", "count": c} for r, c in failures]
    return render_template(
        "index.html",
        start_local=start_local,
        end_local=end_local,
        total_runs=total_runs,
        passed=status_map.get("PASSED", 0),
        failed=status_map.get("FAILED", 0),
        killed=status_map.get("KILLED", 0),
        failures=failures,
        window_label=f"{start_local.strftime('%b %d, %I:%M %p')} → {end_local.strftime('%b %d, %I:%M %p')}",
    )

@app.route("/details")
def details():
    """Detailed table with filters."""
    start = request.args.get("start")  # e.g., 2025-10-24 10:00:01
    end = request.args.get("end")
    start_local, end_local, start_utc, end_utc = get_window_bounds()
    if start and end:
        start_utc = parse_dt_local(start)
        end_utc = parse_dt_local(end)
    rows = (
        Run.query
        .filter(Run.started_at >= start_utc, Run.started_at < end_utc)
        .order_by(Run.started_at.desc())
        .all()
    )
    return render_template("details.html", rows=rows, start_local=start_local, end_local=end_local)

# ----------------------------
# APIs
# ----------------------------
@app.route("/api/summary")
def api_summary():
    start_local, end_local, start_utc, end_utc = resolve_window_from_request()
    q = Run.query.filter(Run.started_at >= start_utc, Run.started_at < end_utc)
    total_runs = q.count()
    status_counts = (
        db.session.query(Run.status, func.count(Run.id))
        .filter(Run.started_at >= start_utc, Run.started_at < end_utc)
        .group_by(Run.status)
        .all()
    )
    failures = (
        db.session.query(Run.reason, func.count(Run.id))
        .filter(Run.started_at >= start_utc, Run.started_at < end_utc, Run.status == "FAILED")
        .group_by(Run.reason)
        .all()
    )
    return jsonify({
        "window": {
            "start_iso": start_local.isoformat(),
            "end_iso": end_local.isoformat()
        },
        "total_runs": total_runs,
        "status_counts": {s: c for s, c in status_counts},
        "failures": [{"reason": r or "Unknown", "count": c} for r, c in failures]
    })

@app.route("/api/failures")
def api_failures():
    """List failed runs grouped by reason within window."""
    start_local, end_local, start_utc, end_utc = resolve_window_from_request()
    failed_runs = (
        Run.query.filter(Run.started_at >= start_utc, Run.started_at < end_utc, Run.status == "FAILED")
        .order_by(Run.reason, Run.started_at.desc())
        .all()
    )
    out = {}
    for r in failed_runs:
        key = r.reason or "Unknown"
        out.setdefault(key, []).append(r.to_dict())
    return jsonify(out)

@app.route("/api/runs")
def api_runs():
    """All runs in window (optionally filter by status/reason/scheduler/cloud)."""
    start_local, end_local, start_utc, end_utc = resolve_window_from_request()
    q = Run.query.filter(Run.started_at >= start_utc, Run.started_at < end_utc)
    status = request.args.get("status")
    reason = request.args.get("reason")
    scheduler = request.args.get("scheduler")
    cloud = request.args.get("cloud")
    if status:
        q = q.filter(Run.status == status)
    if reason:
        q = q.filter(Run.reason == reason)
    if scheduler:
        q = q.filter(Run.scheduler == scheduler)
    if cloud:
        q = q.filter(Run.cloud == cloud)
    rows = [r.to_dict() for r in q.order_by(Run.started_at.desc()).all()]
    return jsonify(rows)

@app.route("/api/by_cloud")
def api_by_cloud():
    """Aggregate counts per cloud and status within the 24h window."""
    start_local, end_local, start_utc, end_utc = resolve_window_from_request()
    rows = (
        db.session.query(Run.cloud, Run.status, func.count(Run.id))
        .filter(Run.started_at >= start_utc, Run.started_at < end_utc)
        .group_by(Run.cloud, Run.status)
        .all()
    )
    out = {}
    for cloud, status, cnt in rows:
        c = cloud or "unknown"
        out.setdefault(c, {})[status] = cnt
    return jsonify(out)


@app.route("/api/windows")
def api_windows():
    """List the last 7 selectable windows."""
    tz = pytz.timezone(APP_TZ)
    now_local = datetime.now(tz)
    windows = []
    for offset in range(7):
        ref = now_local - timedelta(days=offset)
        start_local, end_local, start_utc, end_utc = get_window_bounds(ref)
        windows.append({
            "label": start_local.strftime("%a, %b %d"),
            "range_label": f"{start_local.strftime('%b %d, %I:%M %p')} → {end_local.strftime('%b %d, %I:%M %p')}",
            "start_iso": start_utc.isoformat(),
            "end_iso": end_utc.isoformat()
        })
    return jsonify({"windows": windows})

@app.route("/api/cloud_trend")
def api_cloud_trend():
    """Return per-cloud stats for the past N days (default 7)."""
    try:
        days = int(request.args.get("days", 7))
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(days, 30))

    tz = pytz.timezone(APP_TZ)
    now_local = datetime.now(tz)
    midnight_today = tz.localize(datetime(now_local.year, now_local.month, now_local.day, 0, 0, 0))
    start_local = midnight_today - timedelta(days=days - 1)
    end_local = midnight_today + timedelta(days=1)

    start_utc = start_local.astimezone(pytz.UTC).replace(tzinfo=None)
    end_utc = end_local.astimezone(pytz.UTC).replace(tzinfo=None)

    day_labels = [
        (start_local + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(days)
    ]

    date_expr = func.date(Run.started_at)
    rows = (
        db.session.query(date_expr.label("run_date"), Run.cloud, Run.status, func.count(Run.id))
        .filter(Run.started_at >= start_utc, Run.started_at < end_utc)
        .group_by("run_date", Run.cloud, Run.status)
        .all()
    )

    default_clouds = ["blr-cloud4", "blr-cloud5"]
    clouds = {c: {} for c in default_clouds}
    for run_date, cloud, status, count in rows:
        date_key = run_date if isinstance(run_date, str) else run_date.strftime("%Y-%m-%d")
        cloud_key = cloud or "unknown"
        day_bucket = clouds.setdefault(cloud_key, {}).setdefault(
            date_key, {"passed": 0, "failed": 0, "total": 0}
        )
        if status == "PASSED":
            day_bucket["passed"] += count
        else:
            day_bucket["failed"] += count
        day_bucket["total"] += count

    clouds_sorted = {}
    for cloud_name, stats_by_day in clouds.items():
        series = []
        for day in day_labels:
            bucket = stats_by_day.get(day, {"passed": 0, "failed": 0, "total": 0})
            series.append({"date": day, **bucket})
        clouds_sorted[cloud_name] = series

    return jsonify({
        "days": day_labels,
        "clouds": clouds_sorted,
        "window": {
            "start_iso": start_local.isoformat(),
            "end_iso": end_local.isoformat()
        }
    })

# ---------- simple data load endpoints (JSON) ----------
@app.route("/ingest/json", methods=["POST"])
def ingest_json():
    """
    Accepts JSON array of runs with fields:
    request_id, scheduler, cloud, started_at (ISO), ended_at (ISO),
    status, reason, subreason, notes
    """
    payload = request.get_json(force=True, silent=False)
    if not isinstance(payload, list):
        return jsonify({"error": "Expected a JSON array"}), 400
    added, updated = 0, 0
    for item in payload:
        rid = str(item["request_id"])
        rec = Run.query.filter_by(request_id=rid).first()
        if not rec:
            rec = Run(request_id=rid)
            db.session.add(rec)
            added += 1
        else:
            updated += 1

        rec.scheduler = item.get("scheduler", "BLR-NSP-SCHEDULER1")
        rec.cloud = item.get("cloud")  # "blr-cloud4" or "blr-cloud5"
        rec.started_at = datetime.fromisoformat(item["started_at"])
        rec.ended_at = datetime.fromisoformat(item["ended_at"]) if item.get("ended_at") else None
        rec.status = item.get("status", "FAILED")
        rec.reason = item.get("reason")
        rec.subreason = item.get("subreason")
        rec.notes = item.get("notes")
    db.session.commit()
    flash(f"Ingested {added} new, {updated} updated records.", "success")
    return redirect(url_for("details"))

# ----------------------------
# CLI helpers
# ----------------------------
@app.cli.command("seed-demo")
def seed_demo():
    """Seed 110 demo runs into the active 24h window, half to blr-cloud4 and half to blr-cloud5."""
    db.create_all()
    tz = pytz.timezone(APP_TZ)
    now = datetime.now(tz)
    ten = tz.localize(datetime(now.year, now.month, now.day, 10, 0, 1))

    # Seed inside the same 24h window the dashboard uses
    start = ten if now >= ten else ten - timedelta(days=1)

    reasons = [
        ("FAILED", "Stack Creation Failed", "Helm install Failed"),
        ("FAILED", "Stack Creation Failed", "Helm chart not found"),
        ("FAILED", "NSP pod failure", None),
        ("FAILED", "Quota Exceed", None),
        ("FAILED", "MISSING CASE", "CAM Bundle install failed"),
        ("FAILED", "MISSING CASE", "Unable to login to NSP Server"),
        ("FAILED", "Other Reasons", "Default root context file not found"),
        ("KILLED", None, None),
        ("PASSED", None, None),
    ]

    import random, time
    rid_base = int(time.time())  # unique base so re-running doesn't collide
    total = 110
    added = 0

    for i in range(total):
        req_id = str(rid_base + i)
        if Run.query.filter_by(request_id=req_id).first():
            continue  # idempotent

        status, reason, sub = random.choice(reasons)
        began = (start + timedelta(minutes=13 * i)).astimezone(pytz.UTC).replace(tzinfo=None)
        ended = began + timedelta(minutes=random.randint(20, 120))
        cloud = "blr-cloud4" if i < total / 2 else "blr-cloud5"

        db.session.add(Run(
            request_id=req_id,
            scheduler="BLR-NSP-SCHEDULER1",
            cloud=cloud,
            started_at=began,
            ended_at=ended,
            status=status,
            reason=reason,
            subreason=sub
        ))
        added += 1

    db.session.commit()
    print(f"Seeded demo data (added {added} rows) in active window.")


@app.cli.command("seed-week")
def seed_week():
    """
    Seed 7 distinct days of regression data so the dashboard/dropdowns can be exercised.
    This wipes existing rows for a clean slate.
    """
    import random
    import time

    db.drop_all()
    db.create_all()

    tz = pytz.timezone(APP_TZ)
    now = datetime.now(tz)
    rid_base = int(time.time())
    reasons = [
        "Stack Creation Failed",
        "NSP pod failure",
        "Quota Exceed",
        "MISSING CASE",
        "Other Reasons",
        "Selenium Down",
    ]
    subreasons = [
        "Helm install failed",
        "Config map missing",
        "VM quota exceeded",
        "Artifacts not copied",
        "Network policy blocked egress",
        "Daemonset crashloop",
    ]

    total_inserted = 0
    for day_offset in range(7):
        day_local = now - timedelta(days=day_offset)
        window_start_local = tz.localize(datetime(day_local.year, day_local.month, day_local.day, 10, 0, 1))
        window_start_utc = window_start_local.astimezone(pytz.UTC).replace(tzinfo=None)

        daily_total = 70 + day_offset * 10  # ensure every day differs
        pass_ratio = min(0.65, 0.30 + day_offset * 0.05)
        killed_ratio = 0.05 + day_offset * 0.01
        fail_ratio = max(0.15, 1 - pass_ratio - killed_ratio)

        counts = {
            "PASSED": int(daily_total * pass_ratio),
            "KILLED": int(daily_total * killed_ratio),
            "FAILED": daily_total  # placeholder; adjust below
        }
        counts["FAILED"] = daily_total - counts["PASSED"] - counts["KILLED"]

        statuses = (
            ["PASSED"] * counts["PASSED"] +
            ["KILLED"] * counts["KILLED"] +
            ["FAILED"] * counts["FAILED"]
        )
        random.shuffle(statuses)

        cloud_bias = min(0.85, 0.4 + 0.06 * day_offset)  # shift load toward cloud5 over the week
        minutes_step = max(5, int((24 * 60 - 30) / daily_total))

        for idx, status in enumerate(statuses):
            req_id = f"{rid_base}{day_offset:02d}{idx:03d}"
            began = window_start_utc + timedelta(minutes=idx * minutes_step)
            ended = began + timedelta(minutes=random.randint(20, 90))
            cloud_threshold = max(0.1, 1 - cloud_bias)
            cloud = "blr-cloud4" if (idx / float(daily_total)) < cloud_threshold else "blr-cloud5"
            reason = random.choice(reasons) if status == "FAILED" else None
            sub = random.choice(subreasons) if status == "FAILED" else None

            db.session.add(Run(
                request_id=req_id,
                scheduler="BLR-NSP-SCHEDULER1",
                cloud=cloud,
                started_at=began,
                ended_at=ended,
                status=status,
                reason=reason,
                subreason=sub
            ))
            total_inserted += 1

    db.session.commit()
    print(f"Seeded {total_inserted} runs covering the last 7 distinct days.")


@app.cli.command("reset-db")
def reset_db():
    db.drop_all()
    db.create_all()
    print("DB reset.")

if __name__ == "__main__":
    app.run(debug=True)
