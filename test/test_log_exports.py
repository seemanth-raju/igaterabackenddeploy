from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.services.logs.service import export_events, export_events_docx, export_events_pdf, export_events_xlsx


SAMPLE_ROWS = [
    {
        "event_id": "101",
        "event_time": "2026-04-06T10:30:00+00:00",
        "device_id": "7",
        "tenant_id": "42",
        "tenant_name": "Jane Doe",
        "group": "HR",
        "event_type": "access_granted",
        "access_granted": "Yes",
        "auth_used": "card",
        "direction": "IN",
        "cosec_event_id": "49",
        "detail_1": "42",
        "notes": "Morning entry",
    }
]


def test_export_events_xlsx_contains_headers_and_data():
    payload = export_events_xlsx(SAMPLE_ROWS)
    workbook = openpyxl.load_workbook(io.BytesIO(payload))
    worksheet = workbook.active

    assert worksheet.title == "Access Logs"
    assert worksheet["A1"].value == "Event ID"
    assert worksheet["E2"].value == "Jane Doe"


def test_export_events_docx_generates_openxml_package():
    payload = export_events_docx(SAMPLE_ROWS)

    with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
        names = set(archive.namelist())
        document_xml = archive.read("word/document.xml").decode("utf-8")

    assert "[Content_Types].xml" in names
    assert "_rels/.rels" in names
    assert "word/document.xml" in names
    assert "Access Logs Export" in document_xml
    assert "Jane Doe" in document_xml


def test_export_events_pdf_has_pdf_header():
    payload = export_events_pdf(SAMPLE_ROWS)
    assert payload.startswith(b"%PDF-1.4")
    assert b"Access Logs Export" in payload


def test_export_events_dispatches_by_format():
    _, media_type, filename = export_events(SAMPLE_ROWS, "xlsx")
    assert media_type.endswith("sheet")
    assert filename == "access_logs.xlsx"
