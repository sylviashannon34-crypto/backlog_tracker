"""Backlog Tracker web application."""
import os
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, send_file, url_for

from src.database import initialize_database, get_connection
from src.services import (
    add_supplementary_result,
    dashboard_data,
    export_data,
    import_regular_pdf,
    import_supplementary_pdf,
    search_student,
)

ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = ROOT / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
DB_PATH = Path(os.environ.get("DATABASE_PATH", ROOT / "instance" / "backlog_tracker.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "local-development-key-change-me")
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "25")) * 1024 * 1024

initialize_database(DB_PATH)


@app.context_processor
def inject_navigation_counts():
    data = dashboard_data(DB_PATH)
    return {"nav_backlog_count": data["students_with_backlogs"]}


@app.get("/")
def dashboard():
    return render_template("dashboard.html", page="dashboard", data=dashboard_data(DB_PATH))


@app.get("/students")
def students():
    query = request.args.get("q", "").strip()
    student = search_student(DB_PATH, query) if query else None
    return render_template("students.html", page="students", query=query, student=student)


@app.route("/imports", methods=["GET", "POST"])
def imports():
    result = None
    if request.method == "POST":
        kind = request.form.get("kind", "regular")
        semester_name = request.form.get("semester_name", "I Year I Semester")[:100]
        scheme = request.form.get("academic_scheme", "AR25")[:50]
        file = request.files.get("result_pdf")
        if not file or not file.filename:
            flash("Choose a PDF file to upload.", "error")
        elif not file.filename.lower().endswith(".pdf"):
            flash("Only PDF files are accepted on this page.", "error")
        else:
            safe_name = Path(file.filename).name
            saved = UPLOAD_DIR / safe_name
            file.save(saved)
            try:
                if kind == "supplementary":
                    result = import_supplementary_pdf(DB_PATH, saved, semester_name, scheme)
                else:
                    result = import_regular_pdf(DB_PATH, saved, semester_name, scheme)
                flash(f"Import complete: {result['created']} new records, {result['updated']} updated, {result['skipped']} skipped.", "success")
            except (ValueError, RuntimeError) as exc:
                flash(str(exc), "error")
            finally:
                saved.unlink(missing_ok=True)
    return render_template("imports.html", page="imports", result=result)


@app.route("/supplementary", methods=["GET", "POST"])
def supplementary():
    if request.method == "POST":
        try:
            add_supplementary_result(
                DB_PATH,
                hall_ticket=request.form.get("hall_ticket", ""),
                subject_code=request.form.get("subject_code", ""),
                grade=request.form.get("grade", ""),
                semester_name=request.form.get("semester_name", "I Year I Semester"),
                academic_scheme=request.form.get("academic_scheme", "AR25"),
            )
            flash("Supplementary attempt saved. The original regular grade is preserved.", "success")
        except (ValueError, RuntimeError) as exc:
            flash(str(exc), "error")
        return redirect(url_for("supplementary"))
    with get_connection(DB_PATH) as connection:
        subjects = connection.execute("SELECT subject_code, subject_name FROM subjects ORDER BY subject_code").fetchall()
    return render_template("supplementary.html", page="supplementary", subjects=subjects)


@app.get("/reports")
def reports():
    return render_template("reports.html", page="reports", data=dashboard_data(DB_PATH))


@app.get("/reports/<report_type>.<file_type>")
def download_report(report_type, file_type):
    if report_type not in {"students", "backlogs", "history"} or file_type not in {"csv", "xlsx"}:
        return "Report not found", 404
    try:
        output = export_data(DB_PATH, report_type, file_type)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("reports"))
    return send_file(output, as_attachment=True, download_name=f"backlog_{report_type}.{file_type}",
                     mimetype="text/csv" if file_type == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.errorhandler(413)
def file_too_large(_error):
    flash("The file is larger than the configured upload limit.", "error")
    return redirect(url_for("imports"))


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
