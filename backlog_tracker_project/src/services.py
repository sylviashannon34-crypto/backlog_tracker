"""Business rules for importing, tracking, searching, and exporting results."""
from collections import Counter
from pathlib import Path
import re
import tempfile

import pandas as pd
import pdfplumber

from src.database import get_connection
from src.pdf_reader import parse_result_pdf

BACKLOG_GRADES = {"F", "AB", "ABSENT"}


def status_for(grade):
    return "BACKLOG" if str(grade).strip().upper() in BACKLOG_GRADES else "CLEAR"


def _semester_id(connection, semester_name, academic_scheme):
    connection.execute("INSERT OR IGNORE INTO semesters(semester_name, academic_scheme) VALUES (?, ?)",
                       (semester_name, academic_scheme))
    return connection.execute("SELECT semester_id FROM semesters WHERE semester_name=? AND academic_scheme=?",
                              (semester_name, academic_scheme)).fetchone()[0]


def _subject_id(connection, subject_code, subject_name):
    connection.execute("INSERT OR IGNORE INTO subjects(subject_code, subject_name) VALUES (?, ?)",
                       (subject_code, subject_name or subject_code))
    connection.execute("UPDATE subjects SET subject_name=? WHERE subject_code=? AND (subject_name='' OR subject_name=subject_code)",
                       (subject_name or subject_code, subject_code))
    return connection.execute("SELECT subject_id FROM subjects WHERE subject_code=?", (subject_code,)).fetchone()[0]


def _student_id(connection, hall_ticket, student_name=""):
    connection.execute("INSERT OR IGNORE INTO students(hall_ticket, student_name) VALUES (?, ?)",
                       (hall_ticket.upper(), student_name))
    if student_name:
        connection.execute("UPDATE students SET student_name=? WHERE hall_ticket=? AND student_name=''",
                           (student_name, hall_ticket.upper()))
    return connection.execute("SELECT student_id FROM students WHERE hall_ticket=?", (hall_ticket.upper(),)).fetchone()[0]


def _recalculate_student(connection, student_id, semester_id):
    rows = connection.execute("""
        SELECT regular.subject_id,
               (SELECT r.backlog_status FROM results r
                WHERE r.student_id=regular.student_id AND r.subject_id=regular.subject_id
                  AND r.semester_id=regular.semester_id AND r.attempt_type='Supplementary'
                ORDER BY r.result_id DESC LIMIT 1) AS latest_supp_status
        FROM results regular
        WHERE regular.student_id=? AND regular.semester_id=? AND regular.attempt_type='Regular'
          AND regular.backlog_status='BACKLOG'
    """, (student_id, semester_id)).fetchall()
    active = sum(1 for row in rows if row["latest_supp_status"] != "CLEAR")
    connection.execute("""INSERT INTO semester_results(student_id, semester_id, sgpa) VALUES (?, ?, NULL)
        ON CONFLICT(student_id, semester_id) DO NOTHING""", (student_id, semester_id))
    return active


def import_regular_pdf(database_path, pdf_path, semester_name, academic_scheme):
    records = parse_result_pdf(pdf_path)
    if not records:
        raise ValueError("No student records were found. Confirm the PDF is a text-based university result with grade columns marked GR.")
    created = updated = skipped = 0
    with get_connection(database_path) as connection:
        semester_id = _semester_id(connection, semester_name, academic_scheme)
        for record in records:
            hall_ticket = record.get("hall_ticket", "").strip().upper()
            if not hall_ticket or not record.get("grades"):
                skipped += 1
                continue
            existed = connection.execute("SELECT 1 FROM students WHERE hall_ticket=?", (hall_ticket,)).fetchone()
            student_id = _student_id(connection, hall_ticket, record.get("student_name", ""))
            if existed:
                updated += 1
            else:
                created += 1
            sgpa = record.get("sgpa")
            connection.execute("""INSERT INTO semester_results(student_id, semester_id, sgpa) VALUES (?, ?, ?)
                ON CONFLICT(student_id, semester_id) DO UPDATE SET sgpa=excluded.sgpa""", (student_id, semester_id, sgpa))
            for item in record["grades"]:
                subject_id = _subject_id(connection, item["subject_code"], item.get("subject_name", ""))
                connection.execute("""DELETE FROM results WHERE student_id=? AND subject_id=? AND semester_id=? AND attempt_type='Regular'""",
                                   (student_id, subject_id, semester_id))
                grade = item["grade"].upper()
                connection.execute("""INSERT INTO results(student_id, subject_id, semester_id, attempt_type, grade, backlog_status)
                    VALUES (?, ?, ?, 'Regular', ?, ?)""", (student_id, subject_id, semester_id, grade, status_for(grade)))
        connection.commit()
    return {"created": created, "updated": updated, "skipped": skipped, "processed": created + updated}


def add_supplementary_result(database_path, hall_ticket, subject_code, grade, semester_name="I Year I Semester", academic_scheme="AR25"):
    hall_ticket = hall_ticket.strip().upper()
    subject_code = subject_code.strip().upper()
    grade = grade.strip().upper()
    if not hall_ticket or not subject_code or not grade:
        raise ValueError("Hall ticket, subject code, and grade are required.")
    with get_connection(database_path) as connection:
        student = connection.execute("SELECT student_id FROM students WHERE hall_ticket=?", (hall_ticket,)).fetchone()
        subject = connection.execute("SELECT subject_id FROM subjects WHERE subject_code=?", (subject_code,)).fetchone()
        semester = connection.execute("SELECT semester_id FROM semesters WHERE semester_name=? AND academic_scheme=?",
                                      (semester_name, academic_scheme)).fetchone()
        if not student:
            raise ValueError(f"Student {hall_ticket} was not found. Import regular results first.")
        if not subject or not semester:
            raise ValueError("Subject or semester was not found. Import regular results first.")
        regular = connection.execute("""SELECT backlog_status FROM results WHERE student_id=? AND subject_id=? AND semester_id=? AND attempt_type='Regular'""",
                                     (student[0], subject[0], semester[0])).fetchone()
        if not regular or regular[0] != "BACKLOG":
            raise ValueError("Supplementary attempts can be added only for a regular backlog subject.")
        connection.execute("""INSERT INTO results(student_id, subject_id, semester_id, attempt_type, grade, backlog_status)
            VALUES (?, ?, ?, 'Supplementary', ?, ?)""", (student[0], subject[0], semester[0], grade, status_for(grade)))
        _recalculate_student(connection, student[0], semester[0])
        connection.commit()


def import_supplementary_pdf(database_path, pdf_path, semester_name, academic_scheme):
    records = parse_result_pdf(pdf_path)
    if not records:
        raise ValueError("No student records were found. Confirm the PDF uses a supported text-based result layout.")
    imported = skipped = 0
    for record in records:
        for item in record.get("grades", []):
            try:
                add_supplementary_result(database_path, record["hall_ticket"], item["subject_code"], item["grade"], semester_name, academic_scheme)
                imported += 1
            except ValueError:
                skipped += 1
    return {"created": imported, "updated": 0, "skipped": skipped, "processed": imported}


def dashboard_data(database_path):
    with get_connection(database_path) as connection:
        semester_rows = connection.execute("""SELECT semester_id, semester_name, academic_scheme FROM semesters ORDER BY semester_id DESC""").fetchall()
        totals = Counter()
        distribution = Counter()
        subject_counts = Counter()
        for semester in semester_rows:
            student_rows = connection.execute("""SELECT s.student_id,
                SUM(CASE WHEN r.attempt_type='Regular' AND r.backlog_status='BACKLOG' AND
                    COALESCE((SELECT latest.backlog_status FROM results latest WHERE latest.student_id=r.student_id
                    AND latest.subject_id=r.subject_id AND latest.semester_id=r.semester_id
                    AND latest.attempt_type='Supplementary' ORDER BY latest.result_id DESC LIMIT 1),'BACKLOG')='BACKLOG'
                    THEN 1 ELSE 0 END) AS active
                FROM students s JOIN results r ON r.student_id=s.student_id AND r.semester_id=?
                GROUP BY s.student_id""", (semester["semester_id"],)).fetchall()
            for row in student_rows:
                active = row["active"] or 0
                totals["students"] += 1
                totals["with"] += active > 0
                totals["without"] += active == 0
                distribution["4+" if active >= 4 else str(active)] += 1
            subject_rows = connection.execute("""SELECT sub.subject_code, sub.subject_name,
                COUNT(DISTINCT r.student_id) AS backlog_count
                FROM results r JOIN subjects sub ON sub.subject_id=r.subject_id
                WHERE r.semester_id=? AND r.attempt_type='Regular' AND r.backlog_status='BACKLOG'
                AND COALESCE((SELECT latest.backlog_status FROM results latest WHERE latest.student_id=r.student_id
                    AND latest.subject_id=r.subject_id AND latest.semester_id=r.semester_id
                    AND latest.attempt_type='Supplementary' ORDER BY latest.result_id DESC LIMIT 1),'BACKLOG')='BACKLOG'
                GROUP BY sub.subject_id ORDER BY backlog_count DESC""", (semester["semester_id"],)).fetchall()
            subject_counts.update({f"{r['subject_code']} · {r['subject_name']}": r["backlog_count"] for r in subject_rows})
        return {"total_students": totals["students"], "students_with_backlogs": totals["with"],
                "students_without_backlogs": totals["without"], "subject_count": len(subject_counts),
                "distribution": {key: distribution.get(key, 0) for key in ["0", "1", "2", "3", "4+"]},
                "subjects": [{"name": key, "count": value} for key, value in subject_counts.most_common()],
                "semesters": [dict(row) for row in semester_rows]}


def search_student(database_path, query):
    with get_connection(database_path) as connection:
        student = connection.execute("SELECT * FROM students WHERE hall_ticket=? COLLATE NOCASE", (query,)).fetchone()
        if not student:
            return None
        semester_results = connection.execute("""SELECT sem.semester_name, sem.academic_scheme, sr.sgpa, sem.semester_id
            FROM semester_results sr JOIN semesters sem ON sem.semester_id=sr.semester_id WHERE sr.student_id=?""", (student["student_id"],)).fetchall()
        semesters = []
        for sem in semester_results:
            results = connection.execute("""SELECT sub.subject_code, sub.subject_name, r.grade, r.attempt_type,
                r.backlog_status, r.created_at FROM results r JOIN subjects sub ON sub.subject_id=r.subject_id
                WHERE r.student_id=? AND r.semester_id=? ORDER BY sub.subject_code, r.result_id""",
                (student["student_id"], sem["semester_id"])).fetchall()
            active = 0
            latest_by_subject = {}
            for row in results:
                latest_by_subject.setdefault(row["subject_code"], {})[row["attempt_type"]] = row["backlog_status"]
            for attempts in latest_by_subject.values():
                if attempts.get("Regular") == "BACKLOG" and attempts.get("Supplementary") != "CLEAR":
                    active += 1
            semesters.append({"name": sem["semester_name"], "scheme": sem["academic_scheme"], "sgpa": sem["sgpa"],
                              "active_backlogs": active, "results": [dict(r) for r in results]})
        return {"hall_ticket": student["hall_ticket"], "student_name": student["student_name"],
                "department": student["department"], "section": student["section"], "semesters": semesters}


def export_data(database_path, report_type, file_type):
    with get_connection(database_path) as connection:
        if report_type == "history":
            query = """SELECT s.hall_ticket, s.student_name, sem.semester_name, sem.academic_scheme,
                sub.subject_code, sub.subject_name, r.attempt_type, r.grade, r.backlog_status, r.created_at
                FROM results r JOIN students s ON s.student_id=r.student_id JOIN subjects sub ON sub.subject_id=r.subject_id
                JOIN semesters sem ON sem.semester_id=r.semester_id ORDER BY s.hall_ticket, sem.semester_id, sub.subject_code, r.result_id"""
        elif report_type == "backlogs":
            query = """SELECT s.hall_ticket, s.student_name, sem.semester_name, sem.academic_scheme,
                sub.subject_code, sub.subject_name, r.grade AS regular_grade,
                COALESCE((SELECT latest.grade FROM results latest WHERE latest.student_id=r.student_id AND latest.subject_id=r.subject_id
                    AND latest.semester_id=r.semester_id AND latest.attempt_type='Supplementary' ORDER BY latest.result_id DESC LIMIT 1),'') AS latest_supplementary_grade
                FROM results r JOIN students s ON s.student_id=r.student_id JOIN subjects sub ON sub.subject_id=r.subject_id
                JOIN semesters sem ON sem.semester_id=r.semester_id
                WHERE r.attempt_type='Regular' AND r.backlog_status='BACKLOG'
                AND COALESCE((SELECT latest.backlog_status FROM results latest WHERE latest.student_id=r.student_id AND latest.subject_id=r.subject_id
                    AND latest.semester_id=r.semester_id AND latest.attempt_type='Supplementary' ORDER BY latest.result_id DESC LIMIT 1),'BACKLOG')='BACKLOG'
                ORDER BY s.hall_ticket, sub.subject_code"""
        else:
            query = """SELECT s.hall_ticket, s.student_name, sem.semester_name, sem.academic_scheme,
                sr.sgpa, COUNT(DISTINCT CASE WHEN r.attempt_type='Regular' AND r.backlog_status='BACKLOG' AND
                COALESCE((SELECT latest.backlog_status FROM results latest WHERE latest.student_id=r.student_id AND latest.subject_id=r.subject_id
                    AND latest.semester_id=r.semester_id AND latest.attempt_type='Supplementary' ORDER BY latest.result_id DESC LIMIT 1),'BACKLOG')='BACKLOG'
                THEN r.subject_id END) AS active_backlogs
                FROM students s JOIN semester_results sr ON sr.student_id=s.student_id JOIN semesters sem ON sem.semester_id=sr.semester_id
                LEFT JOIN results r ON r.student_id=s.student_id AND r.semester_id=sem.semester_id
                GROUP BY s.student_id, sem.semester_id ORDER BY s.hall_ticket"""
        frame = pd.read_sql_query(query, connection)
    if file_type == "csv":
        output = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        frame.to_csv(output.name, index=False)
    else:
        output = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        frame.to_excel(output.name, index=False, engine="openpyxl")
    return output.name
