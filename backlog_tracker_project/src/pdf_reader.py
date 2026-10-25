"""Best-effort parser for native text university result PDFs with GR grade columns."""
import re

import pdfplumber

HALL_TICKET = re.compile(r"\b\d{2}[A-Z0-9]{7,12}\b", re.IGNORECASE)
GRADE = re.compile(r"^(?:O|A\+?|B\+?|C|D|E|F|AB|ABSENT|S|P|U|[0-9]+)$", re.IGNORECASE)
SGPA = re.compile(r"^(?:SGPA|SGPA\s*[:=])$", re.IGNORECASE)


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_result_pdf(pdf_path):
    """Read tables with hall ticket and GR headers; unsupported/scanned files return []."""
    found = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if not table:
                    continue
                header_index = next((i for i, row in enumerate(table[:5]) if any(
                    "HTNO" in _clean(cell).upper() or "HALL TICKET" in _clean(cell).upper() for cell in (row or []))), None)
                if header_index is None:
                    continue
                headers = [_clean(cell) for cell in table[header_index]]
                ticket_col = next((i for i, cell in enumerate(headers) if "HTNO" in cell.upper() or "HALL TICKET" in cell.upper()), 0)
                grade_cols = [i for i, cell in enumerate(headers) if re.search(r"\bGR\b", cell.upper())]
                if not grade_cols:
                    grade_cols = [i for i, cell in enumerate(headers) if i != ticket_col and "GRADE" in cell.upper()]
                sgpa_col = next((i for i, cell in enumerate(headers) if "SGPA" in cell.upper()), None)
                for row in table[header_index + 1:]:
                    if not row or ticket_col >= len(row):
                        continue
                    cells = [_clean(cell) for cell in row]
                    ticket_match = HALL_TICKET.search(cells[ticket_col])
                    if not ticket_match:
                        continue
                    ticket = ticket_match.group(0).upper()
                    grades = []
                    for col in grade_cols:
                        if col >= len(cells):
                            continue
                        grade = cells[col].upper().split()[0] if cells[col] else ""
                        if not GRADE.fullmatch(grade):
                            continue
                        # Derive identifiers from the header, never from a student's mark cells,
                        # so every row maps to the same subject record.
                        header_subject = headers[col - 1].upper() if col > 0 else ""
                        subject_code = re.sub(r"[^A-Z0-9_-]", "", header_subject)
                        if not subject_code or subject_code in {"SUBJECT", "CODE", "MARKS", "GRADE", "GR"}:
                            subject_code = f"SUB{col + 1:02d}"
                        subject_name = headers[col - 1] if col > 0 and headers[col - 1] else subject_code
                        grades.append({"subject_code": subject_code, "subject_name": subject_name, "grade": grade})
                    sgpa = None
                    if sgpa_col is not None and sgpa_col < len(cells):
                        match = re.search(r"\d+(?:\.\d+)?", cells[sgpa_col])
                        sgpa = float(match.group()) if match else None
                    if grades:
                        found[ticket] = {"hall_ticket": ticket, "student_name": "", "sgpa": sgpa, "grades": grades}
    return list(found.values())

