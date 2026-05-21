from flask import (Flask, render_template, request, redirect,
                   url_for, g, flash, Response, send_from_directory)
import sqlite3, csv, io, os, uuid, mimetypes
from pathlib import Path
from datetime import datetime
from functools import wraps

from flask_login import (LoginManager, UserMixin, login_user,
                         logout_user, login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash

# ── APP SETUP ──────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production-please")

UPLOAD_FOLDER  = Path(__file__).parent / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)
MAX_MB         = 16
ALLOWED_EXT    = {
    "png","jpg","jpeg","gif","webp","svg",        # images
    "pdf","doc","docx","xls","xlsx","ppt","pptx", # documents
    "txt","csv","md","log",                        # text
    "zip","tar","gz",                              # archives
}
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

def is_image(mimetype):
    return mimetype and mimetype.startswith("image/")

login_manager = LoginManager(app)
login_manager.login_view        = "login"
login_manager.login_message     = "Please log in to access MKM Projects."
login_manager.login_message_category = "info"

# ── DATABASE ───────────────────────────────────────────────────────────────
DB_PATH  = Path(__file__).parent / "data" / "helpdesk.sqlite"
PER_PAGE = 50

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db:
        db.close()

# ── USER MODEL ─────────────────────────────────────────────────────────────
class User(UserMixin):
    def __init__(self, id_, username, display_name, role):
        self.id           = id_
        self.username     = username
        self.display_name = display_name
        self.role         = role

@login_manager.user_loader
def load_user(user_id):
    db  = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return None
    return User(row["id"], row["username"], row["display_name"], row["role"])

def admin_required(f):
    """Decorator: admin-only routes."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role != "admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated

# ── TEMPLATE HELPERS ───────────────────────────────────────────────────────
def status_badge(status):
    return {"Open":"badge-open","In Progress":"badge-progress",
            "Resolved":"badge-resolved","Closed":"badge-closed"}.get(status,"badge-default")

def priority_badge(priority):
    return {"High":"badge-high","Medium":"badge-medium",
            "Low":"badge-low"}.get(priority,"badge-default")

app.jinja_env.globals["status_badge"]   = status_badge
app.jinja_env.globals["priority_badge"] = priority_badge

# ── AUTH ───────────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db       = get_db()
        row      = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            user = User(row["id"], row["username"], row["display_name"], row["role"])
            login_user(user, remember=request.form.get("remember") == "on")
            return redirect(request.args.get("next") or url_for("index"))
        error = "Invalid username or password."
    return render_template("login.html", error=error)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))

# ── USER MANAGEMENT (admin only) ───────────────────────────────────────────
@app.route("/users")
@admin_required
def manage_users():
    db    = get_db()
    users = db.execute("SELECT id, username, display_name, role, created_at FROM users ORDER BY username").fetchall()
    return render_template("users.html", users=users)

@app.route("/users/new", methods=["POST"])
@admin_required
def new_user():
    db       = get_db()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    display  = request.form.get("display_name", "").strip() or username
    role     = request.form.get("role", "agent")
    if username and password:
        try:
            db.execute(
                "INSERT INTO users (username, password_hash, display_name, role) VALUES (?,?,?,?)",
                (username, generate_password_hash(password), display, role)
            )
            db.commit()
            flash(f"User '{username}' created.", "success")
        except sqlite3.IntegrityError:
            flash(f"Username '{username}' already exists.", "danger")
    return redirect(url_for("manage_users"))

@app.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    if user_id == current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("manage_users"))
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    flash("User deleted.", "info")
    return redirect(url_for("manage_users"))

@app.route("/users/<int:user_id>/change_password", methods=["POST"])
@admin_required
def change_password(user_id):
    db       = get_db()
    password = request.form.get("password", "").strip()
    if password:
        db.execute("UPDATE users SET password_hash=? WHERE id=?",
                   (generate_password_hash(password), user_id))
        db.commit()
        flash("Password updated.", "success")
    return redirect(url_for("manage_users"))

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    db    = get_db()
    error = None
    if request.method == "POST":
        current_pw = request.form.get("current_password", "")
        new_pw     = request.form.get("new_password", "").strip()
        display    = request.form.get("display_name", "").strip()
        row        = db.execute("SELECT password_hash FROM users WHERE id=?",
                                (current_user.id,)).fetchone()
        if display:
            db.execute("UPDATE users SET display_name=? WHERE id=?",
                       (display, current_user.id))
        if new_pw:
            if not check_password_hash(row["password_hash"], current_pw):
                error = "Current password is incorrect."
            elif len(new_pw) < 6:
                error = "New password must be at least 6 characters."
            else:
                db.execute("UPDATE users SET password_hash=? WHERE id=?",
                           (generate_password_hash(new_pw), current_user.id))
        if not error:
            db.commit()
            flash("Profile updated.", "success")
            return redirect(url_for("profile"))
    user_row = db.execute("SELECT * FROM users WHERE id=?", (current_user.id,)).fetchone()
    return render_template("profile.html", user=user_row, error=error)

# ── TICKET LIST ────────────────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    db     = get_db()
    search          = request.args.get("search",          "").strip()
    status          = request.args.get("status",          "").strip()
    priority        = request.args.get("priority",        "").strip()
    cat_id          = request.args.get("category",        "").strip()
    assignee_filter = request.args.get("assignee_filter", "").strip()
    page            = max(1, int(request.args.get("page", 1)))

    where, params = "WHERE 1=1", []
    if search:
        where  += " AND (t.subject LIKE ? OR t.description LIKE ? OR t.assignee LIKE ?)"
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]
    if status:
        where += " AND t.status = ?";       params.append(status)
    if priority:
        where += " AND t.priority = ?";     params.append(priority)
    if cat_id:
        where += " AND t.category_id = ?";  params.append(cat_id)
    if assignee_filter:
        where += " AND t.assignee = ?";     params.append(assignee_filter)

    filtered_total = db.execute(f"SELECT COUNT(*) AS c FROM tickets t {where}", params).fetchone()["c"]
    total_pages    = max(1, (filtered_total + PER_PAGE - 1) // PER_PAGE)
    page           = min(page, total_pages)
    offset         = (page - 1) * PER_PAGE

    tickets = db.execute(f"""
        SELECT t.*, c.name AS cat_name, c.color AS cat_color
        FROM tickets t LEFT JOIN categories c ON c.id = t.category_id
        {where}
        ORDER BY CASE t.priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
                 CASE t.status   WHEN 'Open'  THEN 1 WHEN 'In Progress' THEN 2 ELSE 3 END,
                 t.created_at DESC
        LIMIT ? OFFSET ?
    """, params + [PER_PAGE, offset]).fetchall()

    total         = db.execute("SELECT COUNT(*) AS c FROM tickets").fetchone()["c"]
    status_counts = db.execute("SELECT status, COUNT(*) AS cnt FROM tickets GROUP BY status").fetchall()
    categories    = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    assignees     = db.execute("SELECT * FROM assignees ORDER BY name").fetchall()

    import urllib.parse
    qs_parts = {}
    if search:          qs_parts["search"]          = search
    if status:          qs_parts["status"]          = status
    if priority:        qs_parts["priority"]        = priority
    if cat_id:          qs_parts["category"]        = cat_id
    if assignee_filter: qs_parts["assignee_filter"] = assignee_filter
    query_string = urllib.parse.urlencode(qs_parts)

    return render_template("index.html",
        tickets=tickets, total=total, filtered_total=filtered_total,
        status_counts=status_counts, categories=categories, assignees=assignees,
        search=search, selected_status=status, selected_priority=priority,
        selected_category=cat_id, selected_assignee=assignee_filter,
        page=page, total_pages=total_pages, query_string=query_string,
    )

# ── CSV EXPORT — TICKETS ───────────────────────────────────────────────────
@app.route("/export/tickets")
@login_required
def export_tickets():
    db     = get_db()
    search          = request.args.get("search",          "").strip()
    status          = request.args.get("status",          "").strip()
    priority        = request.args.get("priority",        "").strip()
    cat_id          = request.args.get("category",        "").strip()
    assignee_filter = request.args.get("assignee_filter", "").strip()

    where, params = "WHERE 1=1", []
    if search:
        where  += " AND (t.subject LIKE ? OR t.description LIKE ? OR t.assignee LIKE ?)"
        params += [f"%{search}%"]*3
    if status:          where += " AND t.status = ?";      params.append(status)
    if priority:        where += " AND t.priority = ?";    params.append(priority)
    if cat_id:          where += " AND t.category_id = ?"; params.append(cat_id)
    if assignee_filter: where += " AND t.assignee = ?";    params.append(assignee_filter)

    rows = db.execute(f"""
        SELECT t.id, t.subject, t.description, c.name AS category,
               t.priority, t.status, t.assignee,
               t.total_time_spent, t.created_at, t.updated_at
        FROM tickets t LEFT JOIN categories c ON c.id = t.category_id
        {where}
        ORDER BY t.created_at DESC
    """, params).fetchall()

    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["ID","Subject","Description","Category","Priority",
                "Status","Assignee","Total Hours","Created","Updated"])
    for r in rows:
        w.writerow([f"TK-{r['id']:03d}", r["subject"], r["description"] or "",
                    r["category"] or "", r["priority"], r["status"],
                    r["assignee"] or "", r["total_time_spent"] or 0,
                    r["created_at"][:10], r["updated_at"][:10]])

    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=mkm_tickets.csv"})

# ── CSV EXPORT — NOTES / TIME LOG ─────────────────────────────────────────
@app.route("/export/time_log")
@login_required
def export_time_log():
    db   = get_db()
    rows = db.execute("""
        SELECT n.id, t.id AS ticket_id, t.subject, n.author,
               n.note, n.time_spent, n.created_at
        FROM notes n
        JOIN tickets t ON t.id = n.ticket_id
        ORDER BY n.created_at DESC
    """).fetchall()

    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["Note ID","Ticket ID","Ticket Subject","Author","Note","Hours","Date"])
    for r in rows:
        w.writerow([r["id"], f"TK-{r['ticket_id']:03d}", r["subject"],
                    r["author"], r["note"],
                    r["time_spent"] if r["time_spent"] else "",
                    r["created_at"][:10]])

    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=mkm_time_log.csv"})

# ── CSV EXPORT — ASSIGNEES ────────────────────────────────────────────────
@app.route("/export/assignees")
@login_required
def export_assignees():
    db   = get_db()
    rows = db.execute("""
        SELECT a.name,
               COUNT(t.id)                                    AS ticket_count,
               SUM(CASE WHEN t.status='Open'        THEN 1 ELSE 0 END) AS open_tickets,
               SUM(CASE WHEN t.status='In Progress' THEN 1 ELSE 0 END) AS inprog_tickets,
               SUM(CASE WHEN t.status='Resolved'    THEN 1 ELSE 0 END) AS resolved_tickets,
               ROUND(COALESCE(SUM(n.time_spent),0),1)         AS total_hours
        FROM assignees a
        LEFT JOIN tickets t  ON t.assignee   = a.name
        LEFT JOIN notes   n  ON n.ticket_id  = t.id AND n.time_spent IS NOT NULL
        GROUP BY a.id ORDER BY a.name
    """).fetchall()

    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["Assignee","Total Tickets","Open","In Progress","Resolved","Total Hours"])
    for r in rows:
        w.writerow([r["name"], r["ticket_count"], r["open_tickets"],
                    r["inprog_tickets"], r["resolved_tickets"], r["total_hours"]])

    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=mkm_assignees.csv"})

# ── TICKET DETAIL ──────────────────────────────────────────────────────────
@app.route("/ticket/<int:ticket_id>")
@login_required
def ticket_detail(ticket_id):
    db     = get_db()
    ticket = db.execute("""
        SELECT t.*, c.name AS cat_name, c.color AS cat_color
        FROM tickets t LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.id = ?
    """, (ticket_id,)).fetchone()
    if ticket is None:
        return "Ticket not found", 404
    notes       = db.execute("SELECT * FROM notes WHERE ticket_id = ? ORDER BY created_at DESC", (ticket_id,)).fetchall()
    categories  = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    assignees   = db.execute("SELECT * FROM assignees ORDER BY name").fetchall()
    attachments = db.execute("SELECT * FROM attachments WHERE ticket_id=? ORDER BY uploaded_at DESC", (ticket_id,)).fetchall()
    return render_template("ticket_detail.html",
        ticket=ticket, notes=notes, categories=categories,
        assignees=assignees, attachments=attachments,
        is_image=is_image)

# ── NEW TICKET ─────────────────────────────────────────────────────────────
@app.route("/new", methods=["GET", "POST"])
@login_required
def new_ticket():
    db         = get_db()
    categories = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    assignees  = db.execute("SELECT * FROM assignees ORDER BY name").fetchall()
    if request.method == "POST":
        subject     = request.form.get("subject",     "").strip()
        description = request.form.get("description", "").strip()
        category_id = request.form.get("category_id") or None
        priority    = request.form.get("priority",    "Medium")
        status      = request.form.get("status",      "Open")
        assignee    = request.form.get("assignee",    "Unassigned").strip() or "Unassigned"
        now         = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if assignee != "Unassigned":
            db.execute("INSERT OR IGNORE INTO assignees (name) VALUES (?)", (assignee,))
        if subject:
            cur = db.execute("""
                INSERT INTO tickets (subject, description, category_id, priority, status, assignee, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?)
            """, (subject, description, category_id, priority, status, assignee, now, now))
            db.commit()
            return redirect(url_for("ticket_detail", ticket_id=cur.lastrowid))
    return render_template("new_ticket.html", categories=categories, assignees=assignees)

# ── EDIT TICKET ────────────────────────────────────────────────────────────
@app.route("/ticket/<int:ticket_id>/edit", methods=["GET", "POST"])
@login_required
def edit_ticket(ticket_id):
    db     = get_db()
    ticket = db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if ticket is None:
        return "Ticket not found", 404
    categories = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    assignees  = db.execute("SELECT * FROM assignees ORDER BY name").fetchall()
    if request.method == "POST":
        subject     = request.form.get("subject",     "").strip()
        description = request.form.get("description", "").strip()
        category_id = request.form.get("category_id") or None
        priority    = request.form.get("priority",    "Medium")
        status      = request.form.get("status",      "Open")
        assignee    = request.form.get("assignee",    "Unassigned").strip() or "Unassigned"
        now         = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if assignee != "Unassigned":
            db.execute("INSERT OR IGNORE INTO assignees (name) VALUES (?)", (assignee,))
        db.execute("""
            UPDATE tickets SET subject=?,description=?,category_id=?,priority=?,status=?,assignee=?,updated_at=?
            WHERE id=?
        """, (subject, description, category_id, priority, status, assignee, now, ticket_id))
        db.commit()
        return redirect(url_for("ticket_detail", ticket_id=ticket_id))
    return render_template("edit_ticket.html", ticket=ticket, categories=categories, assignees=assignees)

# ── ADD NOTE ───────────────────────────────────────────────────────────────
@app.route("/ticket/<int:ticket_id>/add_note", methods=["POST"])
@login_required
def add_note(ticket_id):
    db       = get_db()
    note     = request.form.get("note",   "").strip()
    author   = request.form.get("author", current_user.display_name).strip() or current_user.display_name
    status   = request.form.get("status", "").strip()
    time_raw = request.form.get("time_spent", "").strip()
    now      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        time_spent = float(time_raw) if time_raw else None
        if time_spent is not None and time_spent < 0:
            time_spent = None
    except ValueError:
        time_spent = None
    if note:
        db.execute("INSERT INTO notes (ticket_id, note, author, created_at, time_spent) VALUES (?,?,?,?,?)",
                   (ticket_id, note, author, now, time_spent))
        if status:
            db.execute("UPDATE tickets SET status=?,updated_at=? WHERE id=?", (status, now, ticket_id))
        total = db.execute(
            "SELECT COALESCE(SUM(time_spent),0) FROM notes WHERE ticket_id=? AND time_spent IS NOT NULL",
            (ticket_id,)
        ).fetchone()[0]
        db.execute("UPDATE tickets SET total_time_spent=? WHERE id=?", (total, ticket_id))
        db.commit()
    return redirect(url_for("ticket_detail", ticket_id=ticket_id))

# ── DELETE TICKET ──────────────────────────────────────────────────────────
@app.route("/ticket/<int:ticket_id>/delete", methods=["POST"])
@login_required
def delete_ticket(ticket_id):
    db   = get_db()
    # Remove attachment files from disk first
    atts = db.execute("SELECT filename FROM attachments WHERE ticket_id=?", (ticket_id,)).fetchall()
    for att in atts:
        fp = UPLOAD_FOLDER / att["filename"]
        if fp.exists():
            fp.unlink()
    db.execute("DELETE FROM attachments WHERE ticket_id=?", (ticket_id,))
    db.execute("DELETE FROM notes        WHERE ticket_id=?", (ticket_id,))
    db.execute("DELETE FROM tickets      WHERE id=?",        (ticket_id,))
    db.commit()
    return redirect(url_for("index"))

# ── DASHBOARD API ──────────────────────────────────────────────────────────
@app.route("/api/dashboard")
@login_required
def api_dashboard():
    from flask import jsonify
    db = get_db()
    total       = db.execute("SELECT COUNT(*) AS c FROM tickets").fetchone()["c"]
    open_       = db.execute("SELECT COUNT(*) AS c FROM tickets WHERE status='Open'").fetchone()["c"]
    inprog      = db.execute("SELECT COUNT(*) AS c FROM tickets WHERE status='In Progress'").fetchone()["c"]
    high        = db.execute("SELECT COUNT(*) AS c FROM tickets WHERE priority='High'").fetchone()["c"]
    total_hours = float(db.execute("SELECT COALESCE(SUM(time_spent),0) FROM notes WHERE time_spent IS NOT NULL").fetchone()[0])
    by_status         = [dict(r) for r in db.execute("SELECT status,COUNT(*) AS cnt FROM tickets GROUP BY status ORDER BY cnt DESC").fetchall()]
    by_priority       = [dict(r) for r in db.execute("SELECT priority,COUNT(*) AS cnt FROM tickets GROUP BY priority ORDER BY cnt DESC").fetchall()]
    by_category       = [dict(r) for r in db.execute("SELECT c.name,c.color,COUNT(t.id) AS cnt FROM categories c LEFT JOIN tickets t ON t.category_id=c.id GROUP BY c.id ORDER BY cnt DESC").fetchall()]
    by_assignee       = [dict(r) for r in db.execute("SELECT assignee,COUNT(*) AS cnt FROM tickets WHERE assignee!='Unassigned' GROUP BY assignee ORDER BY cnt DESC LIMIT 8").fetchall()]
    hours_by_assignee = [dict(r) for r in db.execute("SELECT author,ROUND(SUM(time_spent),1) AS hrs FROM notes WHERE time_spent IS NOT NULL GROUP BY author ORDER BY hrs DESC LIMIT 8").fetchall()]
    return jsonify(total=total,open_=open_,inprog=inprog,high=high,total_hours=total_hours,
                   by_status=by_status,by_priority=by_priority,by_category=by_category,
                   by_assignee=by_assignee,hours_by_assignee=hours_by_assignee)

# ── ASSIGNEES ──────────────────────────────────────────────────────────────
@app.route("/assignees")
@login_required
def assignees():
    db   = get_db()
    rows = db.execute("""
        SELECT a.id, a.name, COUNT(t.id) AS ticket_count
        FROM assignees a LEFT JOIN tickets t ON t.assignee = a.name
        GROUP BY a.id ORDER BY a.name
    """).fetchall()
    return render_template("assignees.html", assignees=rows)

@app.route("/assignees/new", methods=["POST"])
@login_required
def new_assignee():
    db   = get_db()
    name = request.form.get("name", "").strip()
    if name and name.lower() != "unassigned":
        db.execute("INSERT OR IGNORE INTO assignees (name) VALUES (?)", (name,))
        db.commit()
    return redirect(url_for("assignees"))

@app.route("/assignees/<int:assignee_id>/delete", methods=["POST"])
@login_required
def delete_assignee(assignee_id):
    db  = get_db()
    row = db.execute("SELECT name FROM assignees WHERE id = ?", (assignee_id,)).fetchone()
    if row:
        db.execute("UPDATE tickets SET assignee='Unassigned' WHERE assignee=?", (row["name"],))
        db.execute("DELETE FROM assignees WHERE id = ?", (assignee_id,))
        db.commit()
    return redirect(url_for("assignees"))

# ── CATEGORIES ─────────────────────────────────────────────────────────────
@app.route("/categories")
@login_required
def categories():
    db   = get_db()
    cats = db.execute("SELECT c.*,COUNT(t.id) AS ticket_count FROM categories c LEFT JOIN tickets t ON t.category_id=c.id GROUP BY c.id ORDER BY c.name").fetchall()
    return render_template("categories.html", categories=cats)

@app.route("/categories/new", methods=["POST"])
@login_required
def new_category():
    db = get_db()
    name  = request.form.get("name",  "").strip()
    color = request.form.get("color", "cyan").strip()
    if name:
        db.execute("INSERT INTO categories (name, color) VALUES (?,?)", (name, color))
        db.commit()
    return redirect(url_for("categories"))

@app.route("/categories/<int:cat_id>/delete", methods=["POST"])
@login_required
def delete_category(cat_id):
    db = get_db()
    db.execute("UPDATE tickets SET category_id=NULL WHERE category_id=?", (cat_id,))
    db.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    db.commit()
    return redirect(url_for("categories"))

# ── DASHBOARD ──────────────────────────────────────────────────────────────
@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    total       = db.execute("SELECT COUNT(*) AS c FROM tickets").fetchone()["c"]
    open_       = db.execute("SELECT COUNT(*) AS c FROM tickets WHERE status='Open'").fetchone()["c"]
    inprog      = db.execute("SELECT COUNT(*) AS c FROM tickets WHERE status='In Progress'").fetchone()["c"]
    high        = db.execute("SELECT COUNT(*) AS c FROM tickets WHERE priority='High'").fetchone()["c"]
    total_hours = db.execute("SELECT COALESCE(SUM(time_spent),0) FROM notes WHERE time_spent IS NOT NULL").fetchone()[0]
    by_status         = db.execute("SELECT status,COUNT(*) AS cnt FROM tickets GROUP BY status ORDER BY cnt DESC").fetchall()
    by_priority       = db.execute("SELECT priority,COUNT(*) AS cnt FROM tickets GROUP BY priority ORDER BY cnt DESC").fetchall()
    by_category       = db.execute("SELECT c.name,c.color,COUNT(t.id) AS cnt FROM categories c LEFT JOIN tickets t ON t.category_id=c.id GROUP BY c.id ORDER BY cnt DESC").fetchall()
    by_assignee       = db.execute("SELECT assignee,COUNT(*) AS cnt FROM tickets WHERE assignee!='Unassigned' GROUP BY assignee ORDER BY cnt DESC LIMIT 8").fetchall()
    hours_by_assignee = db.execute("SELECT n.author,ROUND(SUM(n.time_spent),1) AS hrs FROM notes n WHERE n.time_spent IS NOT NULL GROUP BY n.author ORDER BY hrs DESC LIMIT 8").fetchall()
    recent            = db.execute("SELECT t.*,c.name AS cat_name,c.color AS cat_color FROM tickets t LEFT JOIN categories c ON c.id=t.category_id ORDER BY t.created_at DESC LIMIT 5").fetchall()
    return render_template("dashboard.html",
        total=total,open_=open_,inprog=inprog,high=high,total_hours=total_hours,
        by_status=by_status,by_priority=by_priority,by_category=by_category,
        by_assignee=by_assignee,hours_by_assignee=hours_by_assignee,recent=recent)

# ── ATTACHMENTS ────────────────────────────────────────────────────────────

@app.route("/ticket/<int:ticket_id>/upload", methods=["POST"])
@login_required
def upload_attachment(ticket_id):
    db = get_db()
    # Verify ticket exists
    if not db.execute("SELECT id FROM tickets WHERE id=?", (ticket_id,)).fetchone():
        return "Ticket not found", 404

    files = request.files.getlist("files")
    if not files or all(f.filename == "" for f in files):
        flash("No files selected.", "danger")
        return redirect(url_for("ticket_detail", ticket_id=ticket_id))

    uploaded = 0
    for f in files:
        if f.filename == "":
            continue
        if not allowed_file(f.filename):
            flash(f"'{f.filename}' — file type not allowed.", "danger")
            continue

        original_name = f.filename
        ext           = original_name.rsplit(".", 1)[1].lower()
        stored_name   = f"{uuid.uuid4().hex}.{ext}"
        save_path     = UPLOAD_FOLDER / stored_name

        f.save(str(save_path))
        size      = save_path.stat().st_size
        mimetype  = f.mimetype or mimetypes.guess_type(original_name)[0] or "application/octet-stream"

        db.execute("""
            INSERT INTO attachments (ticket_id, filename, original_name, mimetype, size_bytes, uploaded_by)
            VALUES (?,?,?,?,?,?)
        """, (ticket_id, stored_name, original_name, mimetype, size, current_user.display_name))
        uploaded += 1

    db.commit()
    if uploaded:
        flash(f"{uploaded} file{'s' if uploaded>1 else ''} uploaded.", "success")
    return redirect(url_for("ticket_detail", ticket_id=ticket_id))


@app.route("/attachments/<int:att_id>/download")
@login_required
def download_attachment(att_id):
    db  = get_db()
    row = db.execute("SELECT * FROM attachments WHERE id=?", (att_id,)).fetchone()
    if row is None:
        return "File not found", 404
    return send_from_directory(
        str(UPLOAD_FOLDER),
        row["filename"],
        as_attachment=True,
        download_name=row["original_name"],
    )


@app.route("/attachments/<int:att_id>/delete", methods=["POST"])
@login_required
def delete_attachment(att_id):
    db       = get_db()
    row      = db.execute("SELECT * FROM attachments WHERE id=?", (att_id,)).fetchone()
    if row is None:
        return "File not found", 404
    ticket_id = row["ticket_id"]
    # Delete from disk
    file_path = UPLOAD_FOLDER / row["filename"]
    if file_path.exists():
        file_path.unlink()
    db.execute("DELETE FROM attachments WHERE id=?", (att_id,))
    db.commit()
    flash("Attachment deleted.", "info")
    return redirect(url_for("ticket_detail", ticket_id=ticket_id))


# ── ENTRY POINT ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
