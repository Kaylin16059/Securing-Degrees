from flask import Flask, render_template, request, redirect, url_for, g
import sqlite3
from pathlib import Path
from datetime import date
import urllib.parse

app = Flask(__name__)

# ── OPTIONAL: Basic Auth for internal-only access ──────────────────────────
# To enable: set DASHBOARD_USER and DASHBOARD_PASS in Railway Variables tab
import functools, os
from flask import request, Response

def check_auth(username, password):
    u = os.environ.get("DASHBOARD_USER")
    p = os.environ.get("DASHBOARD_PASS")
    if not u or not p:
        return True  # no env vars set = auth disabled
    return username == u and password == p

def requires_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response(
                "Authentication required.", 401,
                {"WWW-Authenticate": "Basic realm='Dashboard'"}
            )
        return f(*args, **kwargs)
    return decorated
# ───────────────────────────────────────────────────────────────────────────
# To protect all routes, add @requires_auth above each @app.route decorator.
# ───────────────────────────────────────────────────────────────────────────



DB_PATH = Path(__file__).parent / "data" / "school_partnership_dashboard.sqlite"
PER_PAGE = 100

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def badge_class(stage):
    return {
        "Prospecting": "badge-prospecting",
        "Contacted": "badge-contacted",
        "Meeting Set": "badge-meeting",
        "Follow Up": "badge-followup",
        "Partnered": "badge-partnered",
        "Not Interested": "badge-notinterested",
    }.get(stage, "badge-default")

@app.route("/")
def index():
    db = get_db()

    search      = request.args.get("search", "").strip()
    state       = request.args.get("state", "").strip()
    level       = request.args.get("level", "").strip()
    stage       = request.args.get("stage", "").strip()
    priority    = request.args.get("priority", "").strip()
    no_contacts  = request.args.get("no_contacts", "").strip()
    enrollment   = request.args.get("enrollment", "").strip()
    page         = max(1, int(request.args.get("page", 1)))

    where = "WHERE 1=1"
    params = []

    if search:
        where += " AND (school_name LIKE ? OR district_name LIKE ? OR city LIKE ?)"
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]
    if state:
        where += " AND state = ?"
        params.append(state)
    if level:
        where += " AND level = ?"
        params.append(level)
    if stage:
        where += " AND pipeline_stage = ?"
        params.append(stage)
    if priority:
        where += " AND priority = ?"
        params.append(priority)
    if no_contacts:
        where += " AND NOT EXISTS (SELECT 1 FROM contacts c WHERE c.school_id = schools.id)"
    enrollment_ranges = {
        "small":  ("enrollment > 0 AND enrollment < 100",   []),
        "medium": ("enrollment BETWEEN 100 AND 299",        []),
        "large":  ("enrollment BETWEEN 300 AND 599",        []),
        "xlarge": ("enrollment BETWEEN 600 AND 999",        []),
        "xxlarge":("enrollment >= 1000",                    []),
        "unknown":("(enrollment IS NULL OR enrollment = 0)",[]),
    }
    if enrollment and enrollment in enrollment_ranges:
        clause, ep = enrollment_ranges[enrollment]
        where += f" AND {clause}"
        params += ep

    filtered_total = db.execute(f"SELECT COUNT(*) AS c FROM schools {where}", params).fetchone()["c"]
    total_pages = max(1, (filtered_total + PER_PAGE - 1) // PER_PAGE)
    page = min(page, total_pages)
    offset = (page - 1) * PER_PAGE

    schools = db.execute(
        f"SELECT * FROM schools {where} ORDER BY rank ASC, priority_score DESC, school_name LIMIT ? OFFSET ?",
        params + [PER_PAGE, offset]
    ).fetchall()

    total = db.execute("SELECT COUNT(*) AS c FROM schools").fetchone()["c"]

    by_state = db.execute(
        "SELECT state, COUNT(*) AS count FROM schools GROUP BY state ORDER BY state"
    ).fetchall()

    stages = db.execute(
        "SELECT pipeline_stage, COUNT(*) AS count FROM schools GROUP BY pipeline_stage ORDER BY count DESC"
    ).fetchall()

    states         = db.execute("SELECT DISTINCT state FROM schools ORDER BY state").fetchall()
    levels         = db.execute("SELECT DISTINCT level FROM schools WHERE level IS NOT NULL ORDER BY level").fetchall()
    pipeline_stages = db.execute("SELECT DISTINCT pipeline_stage FROM schools ORDER BY pipeline_stage").fetchall()

    # Build query string for pagination links (without page param)
    qs_parts = {}
    if search:      qs_parts["search"] = search
    if state:       qs_parts["state"] = state
    if level:       qs_parts["level"] = level
    if stage:       qs_parts["stage"] = stage
    if priority:    qs_parts["priority"] = priority
    if no_contacts:  qs_parts["no_contacts"] = no_contacts
    if enrollment:   qs_parts["enrollment"] = enrollment
    query_string = urllib.parse.urlencode(qs_parts)

    no_contacts_total = db.execute(
        "SELECT COUNT(*) AS c FROM schools WHERE level != 'District/Network' AND NOT EXISTS (SELECT 1 FROM contacts c WHERE c.school_id = schools.id)"
    ).fetchone()["c"]

    return render_template(
        "index.html",
        schools=schools,
        total=total,
        filtered_total=filtered_total,
        by_state=by_state,
        stages=stages,
        states=states,
        levels=levels,
        pipeline_stages=pipeline_stages,
        search=search,
        selected_state=state,
        selected_level=level,
        selected_stage=stage,
        selected_priority=priority,
        selected_no_contacts=no_contacts,
        selected_enrollment=enrollment,
        no_contacts_total=no_contacts_total,
        page=page,
        total_pages=total_pages,
        query_string=query_string,
    )

@app.route("/school/<int:school_id>")
def school_detail(school_id):
    db = get_db()
    school = db.execute("SELECT * FROM schools WHERE id = ?", (school_id,)).fetchone()
    if school is None:
        return "School not found", 404

    contacts = db.execute(
        "SELECT * FROM contacts WHERE school_id = ? ORDER BY id DESC", (school_id,)
    ).fetchall()

    notes = db.execute(
        "SELECT * FROM pipeline_notes WHERE school_id = ? ORDER BY note_date DESC, id DESC", (school_id,)
    ).fetchall()

    return render_template("school_detail.html", school=school, contacts=contacts, notes=notes)

@app.route("/school/<int:school_id>/update", methods=["POST"])
def update_school(school_id):
    db = get_db()
    pipeline_stage = request.form.get("pipeline_stage", "Prospecting")
    priority = request.form.get("priority", "Medium")
    db.execute(
        "UPDATE schools SET pipeline_stage = ?, priority = ? WHERE id = ?",
        (pipeline_stage, priority, school_id)
    )
    db.commit()
    return redirect(url_for("school_detail", school_id=school_id))

@app.route("/school/<int:school_id>/add_contact", methods=["POST"])
def add_contact(school_id):
    db = get_db()
    contact_name = request.form.get("contact_name", "").strip()
    role         = request.form.get("role", "").strip()
    email        = request.form.get("email", "").strip()
    phone        = request.form.get("phone", "").strip()
    notes        = request.form.get("notes", "").strip()
    source       = request.form.get("source", "").strip()
    if contact_name or email:
        db.execute(
            "INSERT INTO contacts (school_id, contact_name, role, email, phone, notes, source) VALUES (?,?,?,?,?,?,?)",
            (school_id, contact_name, role, email, phone, notes, source)
        )
        db.commit()
    return redirect(url_for("school_detail", school_id=school_id))

@app.route("/school/<int:school_id>/add_note", methods=["POST"])
def add_note(school_id):
    db = get_db()
    stage     = request.form.get("stage", "Prospecting")
    note      = request.form.get("note", "").strip()
    next_step = request.form.get("next_step", "").strip()
    if note or next_step:
        db.execute(
            "INSERT INTO pipeline_notes (school_id, note_date, stage, note, next_step) VALUES (?,?,?,?,?)",
            (school_id, str(date.today()), stage, note, next_step)
        )
        db.execute("UPDATE schools SET pipeline_stage = ? WHERE id = ?", (stage, school_id))
        db.commit()
    return redirect(url_for("school_detail", school_id=school_id))



import csv
import io

@app.route("/export")
def export_csv():
    db = get_db()

    search   = request.args.get("search", "").strip()
    state    = request.args.get("state", "").strip()
    level    = request.args.get("level", "").strip()
    stage    = request.args.get("stage", "").strip()
    priority = request.args.get("priority", "").strip()

    where = "WHERE 1=1"
    params = []

    if search:
        where += " AND (s.school_name LIKE ? OR s.district_name LIKE ? OR s.city LIKE ?)"
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]
    if state:
        where += " AND s.state = ?"
        params.append(state)
    if level:
        where += " AND s.level = ?"
        params.append(level)
    if stage:
        where += " AND s.pipeline_stage = ?"
        params.append(stage)
    if priority:
        where += " AND s.priority = ?"
        params.append(priority)

    rows = db.execute(f"""
        SELECT
            s.rank,
            s.school_name,
            s.district_name,
            s.state,
            s.city,
            s.zip,
            s.level,
            s.grade_low,
            s.grade_high,
            s.enrollment,
            s.phone,
            s.website,
            s.pipeline_stage,
            s.priority,
            s.priority_score,
            s.priority_reason,
            GROUP_CONCAT(c.contact_name || ' (' || c.role || ')', ' | ') AS contacts,
            GROUP_CONCAT(c.email, ' | ') AS emails
        FROM schools s
        LEFT JOIN contacts c ON c.school_id = s.id
        {where}
        GROUP BY s.id
        ORDER BY s.rank ASC, s.priority_score DESC, s.school_name
    """, params).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Rank", "School Name", "District", "State", "City", "ZIP",
        "Level", "Grade Low", "Grade High", "Enrollment",
        "Phone", "Website", "Pipeline Stage", "Priority",
        "Priority Score", "Priority Reason", "Contacts", "Emails"
    ])
    for row in rows:
        writer.writerow(list(row))

    filename = "securing_degrees_schools"
    if state:   filename += f"_{state}"
    if stage:   filename += f"_{stage.replace(' ','_')}"
    if priority: filename += f"_{priority}"
    filename += ".csv"

    from flask import Response
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# ── BULK PIPELINE UPDATE ────────────────────────────────────────────────────

@app.route("/bulk_update", methods=["POST"])
def bulk_update():
    db = get_db()
    school_ids = request.form.getlist("school_ids")
    new_stage  = request.form.get("bulk_stage", "").strip()
    new_priority = request.form.get("bulk_priority", "").strip()

    # Build return URL from hidden fields
    return_qs = request.form.get("return_qs", "")

    if school_ids and (new_stage or new_priority):
        placeholders = ",".join("?" * len(school_ids))
        if new_stage and new_priority:
            db.execute(
                f"UPDATE schools SET pipeline_stage=?, priority=? WHERE id IN ({placeholders})",
                [new_stage, new_priority] + school_ids
            )
        elif new_stage:
            db.execute(
                f"UPDATE schools SET pipeline_stage=? WHERE id IN ({placeholders})",
                [new_stage] + school_ids
            )
        elif new_priority:
            db.execute(
                f"UPDATE schools SET pipeline_stage=priority WHERE id IN ({placeholders})",
                school_ids
            )
            db.execute(
                f"UPDATE schools SET priority=? WHERE id IN ({placeholders})",
                [new_priority] + school_ids
            )
        db.commit()

    redirect_url = f"/?{return_qs}" if return_qs else "/"
    return redirect(redirect_url)


# ── DISTRICTS VIEW ──────────────────────────────────────────────────────────

@app.route("/districts")
def districts():
    db = get_db()

    search   = request.args.get("search", "").strip()
    state    = request.args.get("state", "").strip()
    stage    = request.args.get("stage", "").strip()
    page     = max(1, int(request.args.get("page", 1)))

    where = "WHERE district_name IS NOT NULL AND district_name != ''"
    params = []

    if search:
        where += " AND (district_name LIKE ? OR city LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    if state:
        where += " AND state = ?"
        params.append(state)
    if stage:
        where += " AND dominant_stage = ?"
        params.append(stage)

    # Build district rollup subquery
    rollup_sql = f"""
        SELECT
            district_name,
            state,
            COUNT(*) AS school_count,
            SUM(CASE WHEN enrollment IS NOT NULL THEN enrollment ELSE 0 END) AS total_enrollment,
            ROUND(AVG(CASE WHEN priority_score IS NOT NULL THEN priority_score END), 1) AS avg_priority_score,
            SUM(CASE WHEN priority = 'High' THEN 1 ELSE 0 END) AS high_count,
            SUM(CASE WHEN priority = 'Medium' THEN 1 ELSE 0 END) AS medium_count,
            SUM(CASE WHEN priority = 'Low' THEN 1 ELSE 0 END) AS low_count,
            SUM(CASE WHEN pipeline_stage = 'Partnered' THEN 1 ELSE 0 END) AS partnered_count,
            SUM(CASE WHEN pipeline_stage = 'Contacted' OR pipeline_stage = 'Meeting Set' OR pipeline_stage = 'Follow Up' THEN 1 ELSE 0 END) AS active_count,
            (SELECT pipeline_stage FROM schools s2
             WHERE s2.district_name = schools.district_name AND s2.state = schools.state
             GROUP BY pipeline_stage ORDER BY COUNT(*) DESC LIMIT 1) AS dominant_stage,
            MIN(city) AS city
        FROM schools
        {where}
        GROUP BY district_name, state
        HAVING school_count >= 1
    """

    count_sql = f"SELECT COUNT(*) FROM ({rollup_sql})"
    filtered_total = db.execute(count_sql, params).fetchone()[0]
    total_pages = max(1, (filtered_total + PER_PAGE - 1) // PER_PAGE)
    page = min(page, total_pages)
    offset = (page - 1) * PER_PAGE

    districts_data = db.execute(
        f"{rollup_sql} ORDER BY avg_priority_score DESC, school_count DESC LIMIT ? OFFSET ?",
        params + [PER_PAGE, offset]
    ).fetchall()

    states = db.execute("SELECT DISTINCT state FROM schools ORDER BY state").fetchall()
    pipeline_stages = db.execute("SELECT DISTINCT pipeline_stage FROM schools ORDER BY pipeline_stage").fetchall()

    qs_parts = {}
    if search: qs_parts["search"] = search
    if state:  qs_parts["state"] = state
    if stage:  qs_parts["stage"] = stage
    import urllib.parse
    query_string = urllib.parse.urlencode(qs_parts)

    return render_template(
        "districts.html",
        districts=districts_data,
        filtered_total=filtered_total,
        states=states,
        pipeline_stages=pipeline_stages,
        search=search,
        selected_state=state,
        selected_stage=stage,
        page=page,
        total_pages=total_pages,
        query_string=query_string,
    )


@app.route("/district/<path:district_name>")
def district_detail(district_name):
    db = get_db()
    state = request.args.get("state", "")

    where = "WHERE district_name = ?"
    params = [district_name]
    if state:
        where += " AND state = ?"
        params.append(state)

    schools = db.execute(
        f"SELECT * FROM schools {where} ORDER BY rank ASC, priority_score DESC, school_name",
        params
    ).fetchall()

    if not schools:
        return "District not found", 404

    # Aggregate stats
    stats = db.execute(f"""
        SELECT
            COUNT(*) AS school_count,
            SUM(CASE WHEN enrollment IS NOT NULL THEN enrollment ELSE 0 END) AS total_enrollment,
            ROUND(AVG(CASE WHEN priority_score IS NOT NULL THEN priority_score END), 1) AS avg_score,
            SUM(CASE WHEN priority='High' THEN 1 ELSE 0 END) AS high_count,
            SUM(CASE WHEN pipeline_stage='Partnered' THEN 1 ELSE 0 END) AS partnered_count,
            SUM(CASE WHEN pipeline_stage IN ('Contacted','Meeting Set','Follow Up') THEN 1 ELSE 0 END) AS active_count
        FROM schools {where}
    """, params).fetchone()

    stage_breakdown = db.execute(f"""
        SELECT pipeline_stage, COUNT(*) AS cnt
        FROM schools {where}
        GROUP BY pipeline_stage ORDER BY cnt DESC
    """, params).fetchall()

    return render_template(
        "district_detail.html",
        district_name=district_name,
        state=state,
        schools=schools,
        stats=stats,
        stage_breakdown=stage_breakdown,
    )


@app.route("/export/district/<path:district_name>")
def export_district_csv(district_name):
    db = get_db()
    state = request.args.get("state", "")

    where = "WHERE s.district_name = ?"
    params = [district_name]
    if state:
        where += " AND s.state = ?"
        params.append(state)

    rows = db.execute(f"""
        SELECT s.rank, s.school_name, s.district_name, s.state, s.city, s.zip,
               s.level, s.grade_low, s.grade_high, s.enrollment, s.phone, s.website,
               s.pipeline_stage, s.priority, s.priority_score, s.priority_reason,
               GROUP_CONCAT(c.contact_name || ' (' || c.role || ')', ' | ') AS contacts,
               GROUP_CONCAT(c.email, ' | ') AS emails
        FROM schools s
        LEFT JOIN contacts c ON c.school_id = s.id
        {where}
        GROUP BY s.id
        ORDER BY s.rank ASC, s.priority_score DESC
    """, params).fetchall()

    import csv, io
    from flask import Response
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Rank","School Name","District","State","City","ZIP","Level",
                     "Grade Low","Grade High","Enrollment","Phone","Website",
                     "Pipeline Stage","Priority","Priority Score","Priority Reason",
                     "Contacts","Emails"])
    for row in rows:
        writer.writerow(list(row))

    safe_name = district_name.replace(" ", "_").replace("/", "-")[:40]
    filename = f"district_{safe_name}.csv"
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


# ── CONTACT IMPORT ──────────────────────────────────────────────────────────

@app.route("/import_contacts", methods=["GET", "POST"])
def import_contacts():
    db = get_db()
    result = None

    if request.method == "POST":
        file = request.files.get("contact_file")
        if not file or not file.filename.endswith(".csv"):
            result = {"error": "Please upload a CSV file."}
        else:
            import csv, io
            content_str = file.stream.read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(content_str))
            rows = list(reader)

            # Detect columns flexibly
            cols = [c.lower().strip() for c in reader.fieldnames or []]
            def find_col(candidates):
                for c in candidates:
                    for original in (reader.fieldnames or []):
                        if original.lower().strip() == c:
                            return original
                return None

            col_school  = find_col(["school_name","school","name"])
            col_name    = find_col(["contact_name","name","full_name","contact"])
            col_role    = find_col(["role","title","position"])
            col_email   = find_col(["email","email_address","e-mail"])
            col_phone   = find_col(["phone","phone_number","tel"])
            col_notes   = find_col(["notes","note","comments"])
            col_source  = find_col(["source","source_url","url"])

            if not col_school:
                result = {"error": "Could not find a 'school_name' column. Make sure your CSV has a school_name column."}
            else:
                # Build school name -> id map
                cur = db.cursor()
                cur.execute("SELECT id, school_name FROM schools")
                db_map = {r[1].strip().upper(): r[0] for r in cur.fetchall()}

                inserted = skipped = updated = 0
                unmatched = set()

                for row in rows:
                    school_name = str(row.get(col_school, "") or "").strip()
                    if not school_name:
                        continue

                    # Try exact then partial match
                    sid = db_map.get(school_name.upper())
                    if not sid:
                        for k, v in db_map.items():
                            if school_name.upper() in k or k in school_name.upper():
                                sid = v
                                break

                    if not sid:
                        unmatched.add(school_name)
                        skipped += 1
                        continue

                    contact_name = str(row.get(col_name, "") or "").strip() if col_name else ""
                    role         = str(row.get(col_role, "") or "").strip() if col_role else ""
                    email        = str(row.get(col_email, "") or "").strip() if col_email else ""
                    phone        = str(row.get(col_phone, "") or "").strip() if col_phone else ""
                    notes        = str(row.get(col_notes, "") or "").strip() if col_notes else ""
                    source       = str(row.get(col_source, "") or "").strip() if col_source else "imported"

                    if not contact_name and not email:
                        skipped += 1
                        continue

                    # Check for duplicate email
                    if email:
                        exists = cur.execute(
                            "SELECT id FROM contacts WHERE school_id=? AND email=?", (sid, email)
                        ).fetchone()
                        if exists:
                            updated += 1
                            cur.execute(
                                "UPDATE contacts SET contact_name=?, role=?, phone=?, notes=? WHERE id=?",
                                (contact_name, role, phone, notes, exists[0])
                            )
                            continue

                    cur.execute(
                        "INSERT INTO contacts (school_id, contact_name, role, email, phone, notes, source) VALUES (?,?,?,?,?,?,?)",
                        (sid, contact_name, role, email, phone, notes, source)
                    )
                    inserted += 1

                db.commit()
                result = {
                    "inserted": inserted,
                    "updated": updated,
                    "skipped": skipped,
                    "unmatched": sorted(list(unmatched))[:20],
                    "total": len(rows)
                }

    return render_template("import_contacts.html", result=result)

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
