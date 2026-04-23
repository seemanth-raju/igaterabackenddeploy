"""Access log service: query, sync, manage, and export AccessEvent records."""

import io
import logging
import unicodedata
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.api.services.logs.events import get_event_meta
from database.models import (
    AccessEvent,
    Device,
    DeviceUserMapping,
    Tenant,
    TenantGroup,
)

log = logging.getLogger(__name__)

EXPORT_FIELDS: list[tuple[str, str]] = [
    ("Event ID", "event_id"),
    ("Event Time", "event_time"),
    ("Device ID", "device_id"),
    ("Tenant ID", "tenant_id"),
    ("Tenant Name", "tenant_name"),
    ("Group", "group"),
    ("Event Type", "event_type"),
    ("Access Granted", "access_granted"),
    ("Auth Used", "auth_used"),
    ("Direction", "direction"),
    ("COSEC Event ID", "cosec_event_id"),
    ("Device Detail", "detail_1"),
    ("Notes", "notes"),
]


def list_events(
    db: Session,
    company_id: str | None = None,
    device_id: int | None = None,
    tenant_id: int | None = None,
    event_type: str | None = None,
    access_granted: bool | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    group_id: int | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[AccessEvent]:
    q = db.query(AccessEvent)
    if company_id:
        from uuid import UUID

        q = q.filter(AccessEvent.company_id == UUID(company_id))
    if device_id is not None:
        q = q.filter(AccessEvent.device_id == device_id)
    if tenant_id is not None:
        q = q.filter(AccessEvent.tenant_id == tenant_id)
    if event_type:
        q = q.filter(AccessEvent.event_type == event_type)
    if access_granted is not None:
        q = q.filter(AccessEvent.access_granted == access_granted)
    if from_time:
        q = q.filter(AccessEvent.event_time >= from_time)
    if to_time:
        q = q.filter(AccessEvent.event_time <= to_time)
    if group_id is not None:
        q = q.join(Tenant, Tenant.tenant_id == AccessEvent.tenant_id)
        q = q.filter(Tenant.group_id == group_id)
        q = q.distinct()
    return q.order_by(AccessEvent.event_time.desc()).offset(skip).limit(limit).all()


def get_event(event_id: int, db: Session) -> AccessEvent:
    event = db.query(AccessEvent).filter(AccessEvent.event_id == event_id).first()
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return event


def update_event(event_id: int, data: dict, db: Session) -> AccessEvent:
    event = get_event(event_id, db)
    for field in ("notes", "direction", "auth_used"):
        if field in data and data[field] is not None:
            setattr(event, field, data[field])
    db.commit()
    db.refresh(event)
    return event


def delete_event(event_id: int, db: Session) -> None:
    event = get_event(event_id, db)
    db.delete(event)
    db.commit()


def sync_logs_from_device(device_id: int, db: Session) -> dict:
    """Pull events from a direct-mode device and store new ones in AccessEvent."""

    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device or not device.ip_address:
        return {
            "device_id": device_id,
            "fetched": 0,
            "inserted": 0,
            "skipped": 0,
            "_new_events": [],
            "_company_id": None,
        }

    if device.communication_mode == "push":
        log.debug("Skipping direct log sync for push-mode device %d", device_id)
        return {
            "device_id": device_id,
            "fetched": 0,
            "inserted": 0,
            "skipped": 0,
            "_new_events": [],
            "_company_id": str(device.company_id) if device.company_id else None,
        }

    from app.services.matrix import MatrixDeviceClient

    client = MatrixDeviceClient(
        device_ip=device.ip_address,
        username=device.api_username or "admin",
        encrypted_password=device.api_password_encrypted or "",
        use_https=device.use_https,
    )

    cursor = (device.config or {}).get("log_cursor", {})
    rollover = cursor.get("rollover_count", 0)
    seq = cursor.get("seq_number", 1)

    raw_events = client.fetch_events(rollover_count=rollover, seq_number=seq, no_of_events=100)

    inserted = 0
    skipped = 0
    new_events = []
    last_seq = seq
    last_rollover = rollover

    for raw in raw_events:
        evt_id = raw.get("cosec_event_id", 0)
        meta = get_event_meta(evt_id)
        detail_1 = raw.get("detail_1", "")

        mapping = (
            db.query(DeviceUserMapping)
            .filter(
                DeviceUserMapping.device_id == device_id,
                DeviceUserMapping.matrix_user_id == detail_1,
            )
            .first()
        ) if detail_1 else None
        tenant_id = mapping.tenant_id if mapping else None

        event = AccessEvent(
            company_id=device.company_id,
            device_id=device_id,
            tenant_id=tenant_id,
            event_type=meta.event_type,
            event_time=raw["event_time"],
            access_granted=meta.access_granted,
            auth_used=meta.auth_used,
            cosec_event_id=evt_id,
            device_seq_number=raw.get("seq_number"),
            device_rollover_count=raw.get("rollover_count"),
            raw_data={
                "detail_1": detail_1,
                "detail_2": raw.get("detail_2", ""),
                "detail_3": raw.get("detail_3", ""),
                "detail_4": raw.get("detail_4", ""),
                "detail_5": raw.get("detail_5", ""),
            },
        )
        try:
            db.add(event)
            db.flush()
            inserted += 1
            last_seq = max(last_seq, raw.get("seq_number", seq))
            last_rollover = raw.get("rollover_count", rollover)
            if meta.access_granted or meta.event_type == "access_denied":
                new_events.append(
                    {
                        "type": "access_event",
                        "event_id": event.event_id,
                        "device_id": device_id,
                        "tenant_id": tenant_id,
                        "event_type": meta.event_type,
                        "event_time": event.event_time.isoformat(),
                        "access_granted": meta.access_granted,
                        "cosec_event_id": evt_id,
                    }
                )
        except Exception:
            db.rollback()
            skipped += 1
            log.debug("Skipped duplicate event seq=%s device=%d", raw.get("seq_number"), device_id)

    if inserted > 0:
        cfg = dict(device.config or {})
        cfg["log_cursor"] = {"rollover_count": last_rollover, "seq_number": last_seq + 1}
        device.config = cfg
        db.commit()
        log.info(
            "Synced device %d: inserted=%d skipped=%d next_seq=%d",
            device_id,
            inserted,
            skipped,
            last_seq + 1,
        )
    else:
        db.rollback()

    return {
        "device_id": device_id,
        "fetched": len(raw_events),
        "inserted": inserted,
        "skipped": skipped,
        "_new_events": new_events,
        "_company_id": str(device.company_id) if device.company_id else None,
    }


def reset_cursor(device_id: int, db: Session) -> dict:
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    cfg = dict(device.config or {})
    cfg["log_cursor"] = {"rollover_count": 0, "seq_number": 1}
    device.config = cfg
    db.commit()
    return {"device_id": device_id, "message": "Cursor reset — next sync will start from seq=1"}


def build_event_export_rows(db: Session, events: list[AccessEvent]) -> list[dict[str, str]]:
    tenant_ids = sorted({event.tenant_id for event in events if event.tenant_id is not None})
    tenant_name_map: dict[int, str] = {}
    tenant_group_map: dict[int, str] = {}

    if tenant_ids:
        tenant_name_map = {
            tenant_id: full_name
            for tenant_id, full_name in db.query(Tenant.tenant_id, Tenant.full_name)
            .filter(Tenant.tenant_id.in_(tenant_ids))
            .all()
        }

        group_rows = (
            db.query(Tenant.tenant_id, TenantGroup.name)
            .join(TenantGroup, TenantGroup.group_id == Tenant.group_id)
            .filter(Tenant.tenant_id.in_(tenant_ids), Tenant.group_id.is_not(None))
            .all()
        )
        tenant_group_map = {tenant_id: group_name for tenant_id, group_name in group_rows}

    rows: list[dict[str, str]] = []
    for event in events:
        raw = event.raw_data or {}
        tenant_name = tenant_name_map.get(event.tenant_id or -1, "")
        group = tenant_group_map.get(event.tenant_id or -1, "")
        rows.append(
            {
                "event_id": str(event.event_id),
                "event_time": event.event_time.isoformat() if event.event_time else "",
                "device_id": str(event.device_id or ""),
                "tenant_id": str(event.tenant_id or ""),
                "tenant_name": tenant_name,
                "group": group,
                "event_type": event.event_type or "",
                "access_granted": "Yes" if event.access_granted else "No",
                "auth_used": event.auth_used or "",
                "direction": event.direction or "",
                "cosec_event_id": str(event.cosec_event_id or ""),
                "detail_1": str(raw.get("detail_1", "")),
                "notes": event.notes or "",
            }
        )
    return rows


def export_events_xlsx(rows: list[dict[str, str]]) -> bytes:
    try:
        import openpyxl
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="openpyxl not installed") from exc

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Access Logs"
    ws.append([label for label, _ in EXPORT_FIELDS])
    for row in rows:
        ws.append([row.get(key, "") for _, key in EXPORT_FIELDS])

    for column in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in column) + 2
        ws.column_dimensions[column[0].column_letter].width = min(max_len, 40)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_events_docx(rows: list[dict[str, str]]) -> bytes:
    generated_at = datetime.now(timezone.utc).isoformat()
    paragraphs = [
        "Access Logs Export",
        f"Generated At (UTC): {generated_at}",
        f"Event Count: {len(rows)}",
        "",
    ]
    for index, row in enumerate(rows, start=1):
        paragraphs.append(f"Event {index}")
        for label, key in EXPORT_FIELDS:
            paragraphs.append(f"{label}: {row.get(key, '')}")
        paragraphs.append("")

    document_xml = _build_docx_document_xml(paragraphs)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _docx_content_types_xml())
        zf.writestr("_rels/.rels", _docx_root_rels_xml())
        zf.writestr("docProps/core.xml", _docx_core_xml(generated_at))
        zf.writestr("docProps/app.xml", _docx_app_xml())
        zf.writestr("word/document.xml", document_xml)
    return output.getvalue()


def export_events_pdf(rows: list[dict[str, str]]) -> bytes:
    generated_at = datetime.now(timezone.utc).isoformat()
    lines = [
        "Access Logs Export",
        f"Generated At (UTC): {generated_at}",
        f"Event Count: {len(rows)}",
        "",
    ]
    for index, row in enumerate(rows, start=1):
        lines.append(f"Event {index}")
        for label, key in EXPORT_FIELDS:
            lines.append(f"{label}: {row.get(key, '')}")
        lines.append("")
    return _build_simple_pdf(lines)


def export_events(rows: list[dict[str, str]], export_format: str) -> tuple[bytes, str, str]:
    if export_format == "xlsx":
        return (
            export_events_xlsx(rows),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "access_logs.xlsx",
        )
    if export_format == "docx":
        return (
            export_events_docx(rows),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "access_logs.docx",
        )
    if export_format == "pdf":
        return export_events_pdf(rows), "application/pdf", "access_logs.pdf"
    raise HTTPException(status_code=400, detail="Unsupported export format")


def _docx_content_types_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""


def _docx_root_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""


def _docx_core_xml(generated_at: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Access Logs Export</dc:title>
  <dc:creator>Igatera Backend</dc:creator>
  <cp:lastModifiedBy>Igatera Backend</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{escape(generated_at)}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{escape(generated_at)}</dcterms:modified>
</cp:coreProperties>"""


def _docx_app_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Igatera Backend</Application>
</Properties>"""


def _build_docx_document_xml(paragraphs: list[str]) -> str:
    body_parts = []
    for paragraph in paragraphs:
        text = escape(paragraph)
        body_parts.append(
            '<w:p><w:r><w:t xml:space="preserve">'
            + text
            + "</w:t></w:r></w:p>"
        )
    body_parts.append(
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" '
        'w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body_parts)
        + "</w:body></w:document>"
    )


def _build_simple_pdf(lines: list[str]) -> bytes:
    normalized_lines = [_normalize_pdf_text(line) for line in lines]
    lines_per_page = 48
    pages = [
        normalized_lines[index:index + lines_per_page]
        for index in range(0, len(normalized_lines), lines_per_page)
    ] or [[]]

    objects: list[bytes] = []

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")

    page_refs = []
    for page_index in range(len(pages)):
        page_obj_num = 4 + page_index * 2
        page_refs.append(f"{page_obj_num} 0 R")
    objects.append(f"<< /Type /Pages /Count {len(pages)} /Kids [{' '.join(page_refs)}] >>".encode("ascii"))

    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for page in pages:
        content = _pdf_page_stream(page)
        content_obj_num = len(objects) + 2
        page_dict = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_obj_num} 0 R >>"
        ).encode("ascii")
        content_dict = b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream"
        objects.append(page_dict)
        objects.append(content_dict)

    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(f"{index} 0 obj\n".encode("ascii"))
        output.write(obj)
        output.write(b"\nendobj\n")

    xref_offset = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode("ascii"))

    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF"
    ).encode("ascii")
    output.write(trailer)
    return output.getvalue()


def _pdf_page_stream(lines: list[str]) -> bytes:
    commands = ["BT", "/F1 9 Tf", "36 756 Td"]
    for index, line in enumerate(lines):
        if index > 0:
            commands.append("0 -14 Td")
        commands.append(f"({_escape_pdf_text(line)}) Tj")
    commands.append("ET")
    return "\n".join(commands).encode("cp1252", errors="replace")


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _normalize_pdf_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("cp1252", errors="replace").decode("cp1252")
    return normalized
