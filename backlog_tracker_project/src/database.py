"""SQLite database setup and connection helpers."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS students (
    student_id INTEGER PRIMARY KEY,
    hall_ticket TEXT NOT NULL UNIQUE COLLATE NOCASE,
    student_name TEXT NOT NULL DEFAULT '',
    department TEXT NOT NULL DEFAULT 'Computer Science and Engineering',
    section TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS semesters (
    semester_id INTEGER PRIMARY KEY,
    semester_name TEXT NOT NULL,
    academic_scheme TEXT NOT NULL,
    exam_type TEXT NOT NULL DEFAULT 'Regular',
    UNIQUE(semester_name, academic_scheme)
);
CREATE TABLE IF NOT EXISTS subjects (
    subject_id INTEGER PRIMARY KEY,
    subject_code TEXT NOT NULL UNIQUE COLLATE NOCASE,
    subject_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS semester_results (
    semester_result_id INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    semester_id INTEGER NOT NULL REFERENCES semesters(semester_id) ON DELETE CASCADE,
    sgpa REAL,
    UNIQUE(student_id, semester_id)
);
CREATE TABLE IF NOT EXISTS results (
    result_id INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(subject_id) ON DELETE CASCADE,
    semester_id INTEGER NOT NULL REFERENCES semesters(semester_id) ON DELETE CASCADE,
    attempt_type TEXT NOT NULL CHECK(attempt_type IN ('Regular', 'Supplementary')),
    grade TEXT NOT NULL,
    backlog_status TEXT NOT NULL CHECK(backlog_status IN ('BACKLOG', 'CLEAR')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_results_student ON results(student_id, semester_id);
CREATE INDEX IF NOT EXISTS idx_results_subject ON results(subject_id, semester_id);
"""


@contextmanager
def get_connection(database_path):
    connection = sqlite3.connect(str(database_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
    finally:
        connection.close()


def initialize_database(database_path):
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    with get_connection(database_path) as connection:
        connection.executescript(SCHEMA)
        connection.commit()
