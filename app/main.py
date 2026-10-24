
from datetime import datetime
import logging
import os
import tempfile
from io import BytesIO
from xml.sax.saxutils import escape

from fastapi import (
    FastAPI,
    Form,
    Request,
    UploadFile,
    File,
    HTTPException,
)
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.database import (
    init_db,
    save_record,
    get_record,
    list_records,
)
from app.audit import init_audit_table, log_event
from app.structure import structure_record
from app.speech import transcribe_audio


app = FastAPI(title="Field-to-Record")
templates = Jinja2Templates(directory="templates")


# -------------------- Helpers --------------------

def display_value(value):
    """Convert stored values and NER entities into readable text."""
    if value is None or value == "":
        return "Not recorded"

    if isinstance(value, dict):
        for key in ("text", "value", "name", "medication_name"):
            item = value.get(key)
            if item is not None and item != "":
                return display_value(item)
        return "Not recorded"

    if isinstance(value, list):
        parts = []
        for item in value:
            rendered = display_value(item)
            if rendered != "Not recorded" and rendered not in parts:
                parts.append(rendered)
        return ", ".join(parts) if parts else "Not recorded"

    return str(value)


def format_timestamp(value):
    """Format stored ISO timestamps for people reading the record."""
    if not value:
        return "Not recorded"

    try:
        timestamp = datetime.fromisoformat(str(value))
        return timestamp.strftime("%d %b %Y, %I:%M:%S %p IST")
    except (ValueError, TypeError):
        return str(value)


def safe_text(value):
    """Escape text before placing it inside a ReportLab paragraph."""
    return escape(display_value(value))


def add_pdf_paragraph(story, text, style):
    story.append(Paragraph(safe_text(text), style))


# -------------------- History --------------------

@app.get("/records", response_class=HTMLResponse)
def previous_records(request: Request):
    records = list_records()
    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={"records": records},
    )


@app.get("/records/{record_id}", response_class=HTMLResponse)
def view_previous_record(request: Request, record_id: str):
    record = get_record(record_id)

    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")

    return templates.TemplateResponse(
        request=request,
        name="record_detail.html",
        context={"record": record},
    )


# -------------------- Speech-to-Text --------------------

@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    content_type = (file.content_type or "").lower()

    if not content_type.startswith("audio/"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format: {content_type or 'unknown'}",
        )

    temp_path = None

    try:
        suffix = os.path.splitext(file.filename or "")[1] or ".webm"

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
        ) as temp:
            temp_path = temp.name
            content = await file.read()
            temp.write(content)

        if not content:
            raise HTTPException(
                status_code=400,
                detail="The audio recording is empty.",
            )

        transcript = transcribe_audio(temp_path)
        return {"transcript": transcript}

    except HTTPException:
        raise
    except Exception:
        logging.exception("Transcription failed")
        raise HTTPException(
            status_code=500,
            detail="Transcription failed. Check the server terminal for details.",
        )
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        await file.close()


# -------------------- Startup --------------------

@app.on_event("startup")
def startup():
    init_db()
    init_audit_table()


# -------------------- Home --------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"error": None, "note": ""},
    )


# -------------------- Extract Record --------------------

@app.post("/extract", response_class=HTMLResponse)
def extract_note(request: Request, note: str = Form(...)):
    note = note.strip()

    if not note:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error": "Please enter a responder note.",
                "note": note,
            },
            status_code=400,
        )

    try:
        record = structure_record(note)
        record["status"] = "draft"
        record["reviewed_at"] = None
        record["finalized_at"] = None
        record["exported_at"] = None

        save_record(record)

        log_event(
            record["record_id"],
            "record_created",
            {"status": "draft", "source": "web_interface"},
        )

        return templates.TemplateResponse(
            request=request,
            name="review.html",
            context={"record": record, "error": None},
        )

    except Exception:
        logging.exception("Failed to extract responder note")
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error": (
                    "The note could not be processed. "
                    "Check the server terminal for details."
                ),
                "note": note,
            },
            status_code=500,
        )


# -------------------- Human Review --------------------

@app.post("/review/{record_id}", response_class=HTMLResponse)
async def review_record(request: Request, record_id: str):
    record = get_record(record_id)

    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")

    if record.get("status") != "draft":
        return templates.TemplateResponse(
            request=request,
            name="review.html",
            context={
                "record": record,
                "error": "This record is no longer a draft.",
            },
            status_code=400,
        )

    form = await request.form()

    if form.get("confirmed") != "yes":
        return templates.TemplateResponse(
            request=request,
            name="review.html",
            context={
                "record": record,
                "error": "Please confirm that you reviewed the fields.",
            },
            status_code=400,
        )

    medications = record.get("medications", [])

    for index, medication in enumerate(medications):
        name = str(form.get(f"name_{index}", "")).strip()

        if not name:
            return templates.TemplateResponse(
                request=request,
                name="review.html",
                context={
                    "record": record,
                    "error": f"Medication {index + 1} needs a name.",
                },
                status_code=400,
            )

        # Keep the field name consistent with the PDF generator.
        medication["medication_name"] = name

        attributes = medication.setdefault("attributes", {})

        for field_name, attr_type in (
            ("strength", "STRENGTH"),
            ("route", "ROUTE"),
        ):
            value = str(form.get(f"{field_name}_{index}", "")).strip()

            if value:
                items = attributes.setdefault(attr_type, [])

                if items and isinstance(items[0], dict):
                    items[0]["text"] = value
                else:
                    items[:] = [{
                        "text": value,
                        "score": None,
                        "start": None,
                        "end": None,
                    }]
            else:
                attributes.pop(attr_type, None)

    reviewed_at = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    record["status"] = "reviewed"
    record["reviewed_at"] = reviewed_at

    save_record(record)

    log_event(
        record_id,
        "record_reviewed",
        {
            "status": "reviewed",
            "reviewed_at": reviewed_at,
        },
    )

    return templates.TemplateResponse(
        request=request,
        name="review.html",
        context={"record": record, "error": None},
    )


# -------------------- PDF Export --------------------

@app.get("/records/{record_id}/pdf")
def export_record_pdf(record_id: str):
    record = get_record(record_id)

    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")

    if record.get("status") not in ("reviewed", "finalized"):
        raise HTTPException(
            status_code=400,
            detail="Only reviewed or finalized records can be exported.",
        )

    buffer = BytesIO()

    pdf = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    story = []

    add_pdf_paragraph(story, "Field-to-Record", styles["Title"])
    add_pdf_paragraph(story, "Clinical Record", styles["Heading2"])
    story.append(Spacer(1, 12))

    add_pdf_paragraph(story, "Record Information", styles["Heading2"])

    info = [
        [
            "Record ID",
            display_value(record.get("record_id") or record_id),
        ],
        ["Status", display_value(record.get("status"))],
        [
            "Created",
            format_timestamp(
                record.get("record_created_at")
                or record.get("created_at")
            ),
        ],
        ["Reviewed", format_timestamp(record.get("reviewed_at"))],
        ["Finalized", format_timestamp(record.get("finalized_at"))],
    ]

    table = Table(info, colWidths=[4 * cm, 12 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 7),
    ]))

    story.append(table)
    story.append(Spacer(1, 14))

    add_pdf_paragraph(story, "Original Responder Note", styles["Heading2"])
    add_pdf_paragraph(
        story,
        record.get("original_note") or record.get("note"),
        styles["BodyText"],
    )
    story.append(Spacer(1, 14))

    # Medications
    add_pdf_paragraph(story, "Medications", styles["Heading2"])
    medications = record.get("medications") or []

    if medications:
        for med in medications:
            if not isinstance(med, dict):
                add_pdf_paragraph(story, med, styles["Heading3"])
                continue

            name = (
                med.get("medication_name")
                or med.get("name")
                or med.get("drug")
                or med.get("medication")
                or med.get("text")
                or "Medication name not extracted"
            )

            add_pdf_paragraph(story, name, styles["Heading3"])
            add_pdf_paragraph(
                story,
                f"Event time: {display_value(med.get('event_time'))}",
                styles["BodyText"],
            )

            attributes = med.get("attributes") or {}

            if isinstance(attributes, dict):
                for key, value in attributes.items():
                    label = str(key).replace("_", " ").title()
                    add_pdf_paragraph(
                        story,
                        f"{label}: {display_value(value)}",
                        styles["BodyText"],
                    )

            elif isinstance(attributes, list):
                for attribute in attributes:
                    if isinstance(attribute, dict):
                        key = (
                            attribute.get("type")
                            or attribute.get("label")
                            or attribute.get("name")
                            or "Attribute"
                        )
                        value = (
                            attribute.get("value")
                            if attribute.get("value") is not None
                            else attribute.get("text")
                        )
                        label = str(key).replace("_", " ").title()
                        add_pdf_paragraph(
                            story,
                            f"{label}: {display_value(value)}",
                            styles["BodyText"],
                        )
                    else:
                        add_pdf_paragraph(
                            story,
                            attribute,
                            styles["BodyText"],
                        )

            story.append(Spacer(1, 8))
    else:
        add_pdf_paragraph(
            story,
            "No medications recorded.",
            styles["BodyText"],
        )

    # Procedures
    story.append(Spacer(1, 8))
    add_pdf_paragraph(story, "Procedures", styles["Heading2"])

    procedures = record.get("procedures") or []

    if procedures:
        for procedure in procedures:
            if isinstance(procedure, dict):
                name = (
                    procedure.get("name")
                    or procedure.get("text")
                    or "Procedure"
                )
            else:
                name = procedure

            add_pdf_paragraph(story, name, styles["BodyText"])
    else:
        add_pdf_paragraph(
            story,
            "No procedures recorded.",
            styles["BodyText"],
        )

    story.append(Spacer(1, 18))
    add_pdf_paragraph(
        story,
        "Generated by Field-to-Record. This document reflects the saved "
        "record and is not an independent clinical validation.",
        styles["Italic"],
    )

    pdf.build(story)
    buffer.seek(0)

    filename = f"clinical_record_{record_id}.pdf"

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )
