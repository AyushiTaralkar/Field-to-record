
from datetime import datetime

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.database import init_db, save_record, get_record
from app.audit import init_audit_table, log_event
from app.structure import structure_record


app = FastAPI(title="Field-to-Record")
templates = Jinja2Templates(directory="templates")


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
