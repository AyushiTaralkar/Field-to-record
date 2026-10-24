
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.database import init_db, save_record
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
        save_record(record)

        log_event(
            record["record_id"],
            "record_created",
            {"status": "draft", "source": "web_interface"},
        )

        return templates.TemplateResponse(
            request=request,
            name="review.html",
            context={"record": record},
        )

    except Exception:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error": "The note could not be processed. Please try again.",
                "note": note,
            },
            status_code=500,
        )
