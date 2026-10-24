
from datetime import datetime
import os
import tempfile

from fastapi import FastAPI, Form, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.database import init_db, save_record, get_record, list_records
from app.audit import init_audit_table, log_event
from app.structure import structure_record
from app.speech import transcribe_audio

from io import BytesIO

from fastapi.responses import StreamingResponse
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

app = FastAPI(title="Field-to-Record")
templates = Jinja2Templates(directory="templates")

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




@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    allowed_types = {
        "audio/webm",
        "audio/wav",
        "audio/x-wav",
        "audio/mpeg",
        "audio/mp4",
        "audio/ogg",
    }

    content_type = (file.content_type or "").lower()

    if not content_type.startswith("audio/"):
      raise HTTPException(
        status_code=400,
        detail=f"Unsupported audio format: {content_type or 'unknown'}"
    )
    temp_path = None

    try:
        suffix = ".webm"
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix
        ) as temp:
            temp_path = temp.name
            content = await file.read()
            temp.write(content)

        if not content:
            raise HTTPException(
                status_code=400,
                detail="The audio recording is empty."
            )

        transcript = transcribe_audio(temp_path)
        return {"transcript": transcript}

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Transcription failed: {exc}"
        )
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        await file.close()


@app.on_event("startup")
def startup():
    init_db()
    init_audit_table()


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"error": None, "note": ""},
    )


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
        # Print the actual exception in the server terminal for debugging.
        import logging
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


@app.post("/review/{record_id}", response_class=HTMLResponse)
async def review_record(request: Request, record_id: str):
    record = get_record(record_id)

    if record is None:
        return HTMLResponse("Record not found.", status_code=404)

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

        medication["medication_name"] = name
        attributes = medication.setdefault("attributes", {})

        for field_name, attr_type in (
            ("strength", "STRENGTH"),
            ("route", "ROUTE"),
        ):
            value = str(form.get(f"{field_name}_{index}", "")).strip()

            if value:
                items = attributes.setdefault(attr_type, [])

                if items:
                    # Update the first displayed value.
                    items[0]["text"] = value
                else:
                    items.append({
                        "text": value,
                        "score": None,
                        "start": None,
                        "end": None,
                    })
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

from xml.sax.saxutils import escape


def safe_text(value):
    """Escape text before placing it inside a PDF paragraph."""
    if value is None or value == "":
        return "Not stated"
    return escape(str(value))


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

    story.append(Paragraph("Field-to-Record", styles["Title"]))
    story.append(Paragraph("Clinical Record", styles["Heading2"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Record Information", styles["Heading2"]))

    info = [
        ["Record ID", safe_text(record.get("id") or record.get("record_id") or record_id)],
        ["Status", safe_text(record.get("status"))],
        ["Created", safe_text(record.get("created_at"))],
        ["Reviewed", safe_text(record.get("reviewed_at"))],
        ["Finalized", safe_text(record.get("finalized_at"))],
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

    story.append(Paragraph("Original Responder Note", styles["Heading2"]))
    story.append(Paragraph(
        safe_text(record.get("original_note")),
        styles["BodyText"],
    ))
    story.append(Spacer(1, 14))

    story.append(Paragraph("Medications", styles["Heading2"]))

    medications = record.get("medications") or []

    if medications:
        for med in medications:
            story.append(Paragraph(
                safe_text(med.get("name", "Medication")),
                styles["Heading3"],
            ))

            story.append(Paragraph(
                f"Event time: {safe_text(med.get('event_time'))}",
                styles["BodyText"],
            ))

            attributes = med.get("attributes") or {}

            if isinstance(attributes, dict):
                for key, value in attributes.items():
                    story.append(Paragraph(
                        f"{safe_text(key)}: {safe_text(value)}",
                        styles["BodyText"],
                    ))
            elif isinstance(attributes, list):
                for attribute in attributes:
                    if isinstance(attribute, dict):
                        key = attribute.get("type", attribute.get("label", "Attribute"))
                        value = attribute.get("value", "")
                        story.append(Paragraph(
                            f"{safe_text(key)}: {safe_text(value)}",
                            styles["BodyText"],
                        ))
                    else:
                        story.append(Paragraph(
                            safe_text(attribute), styles["BodyText"]
                        ))

            story.append(Spacer(1, 8))
    else:
        story.append(Paragraph("No medications recorded.", styles["BodyText"]))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Procedures", styles["Heading2"]))

    procedures = record.get("procedures") or []

    if procedures:
        for procedure in procedures:
            if isinstance(procedure, dict):
                name = procedure.get("name", procedure.get("text", "Procedure"))
                story.append(Paragraph(safe_text(name), styles["BodyText"]))
            else:
                story.append(Paragraph(safe_text(procedure), styles["BodyText"]))
    else:
        story.append(Paragraph("No procedures recorded.", styles["BodyText"]))

    story.append(Spacer(1, 18))
    story.append(Paragraph(
        "Generated by Field-to-Record. This document reflects the saved "
        "record and is not an independent clinical validation.",
        styles["Italic"],
    ))

    pdf.build(story)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="clinical_record_{record_id}.pdf"'
        },
    )
