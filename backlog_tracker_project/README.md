# Backlog Tracker

A local web application based on the Backlog Tracker PBL report. It provides an academic dashboard, hall-ticket search, regular and supplementary result imports, manual supplementary entry, attempt history, and CSV/Excel exports.

The implementation uses **Python + Flask** for the backend, **HTML/CSS** for the frontend, **SQLite** for storage, and `pdfplumber` / `pandas` for PDF processing and reports. The report describes a Streamlit prototype; this version uses standard HTML templates to provide the requested HTML frontend.

## Features

- Dashboard totals, backlog distribution, and subject-level backlog counts.
- Student lookup by hall ticket with SGPA, current backlog count, and every stored attempt.
- Regular result PDF upload with student, semester, subject, grade, and SGPA storage.
- Supplementary PDF upload and manual supplementary updates.
- Automatic active backlog calculation. `F`, `AB`, and `ABSENT` are backlog grades. A backlog clears when the latest supplementary grade is not one of those values.
- Student summary, active backlog, and complete attempt history exports as CSV or Excel.
- Responsive layout for desktop and mobile browser sizes.

## Requirements

- Python 3.10 or newer
- Pip

## Run locally

Open a terminal in this project folder and run:

```bash
python -m venv .venv
```

Activate the virtual environment:

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Install dependencies and start the app:

```bash
python -m pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000> in a browser. The SQLite database is created in `instance/backlog_tracker.db` on first run.

Optional configuration can be copied from `.env.example` into your shell environment. `FLASK_SECRET_KEY` should be changed before exposing the app outside a local development environment. `DATABASE_PATH` changes the SQLite file location and `MAX_UPLOAD_MB` changes the upload limit.

## Import format and parser notes

The report describes university result PDFs whose grade columns are labelled `GR`. The parser supports text-based PDFs with extractable tables containing a hall-ticket column and grade columns labelled `GR` (or `GRADE`). It does not perform OCR on scanned images. PDF layouts vary between universities, so check the import result and dashboard after the first import. For scanned or differently structured result files, convert the data to a standard text/table format or adapt `src/pdf_reader.py` to that result layout.

Subject codes are read from the table cell immediately before each grade column where possible. When the source table does not contain a code in that position, the parser assigns a generated `SUBxx` code; inspect and correct `src/pdf_reader.py` for the actual result format before relying on those subject labels.

Supplementary records are associated with the semester name and academic scheme entered on the upload/manual-update form. Upload regular results for that same semester first.

## Project structure

```text
backlog_tracker_project/
├── app.py
├── requirements.txt
├── src/
│   ├── database.py
│   ├── pdf_reader.py
│   └── services.py
├── templates/
│   ├── base.html
│   ├── dashboard.html
│   ├── imports.html
│   ├── reports.html
│   ├── students.html
│   └── supplementary.html
├── static/style.css
├── instance/                 # SQLite database, generated locally
└── uploads/                   # Temporary PDF uploads, removed after processing
```

## GitHub

This folder is structured as a normal source repository. The `.gitignore` excludes the local database, virtual environment, uploads, and Python cache files. To publish it, create an empty GitHub repository and run:

```bash
git init
git add .
git commit -m "Add Backlog Tracker web app"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/backlog-tracker-project.git
git push -u origin main
```

Do not commit student result PDFs or databases containing real student data.
