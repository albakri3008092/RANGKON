import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import quote, urlsplit

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import services
from .config import settings
from .db import SessionLocal, get_db, init_db
from .models import Event, Invitation, Member
from .whatsapp import build_provider, valid_signature

log = logging.getLogger("rangkon")
BASE = Path(__file__).parent

provider = build_provider(settings)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if settings.admin_password == "admin":
        log.warning("RANGKON_ADMIN_PASSWORD belum ditetapkan; guna kata laluan lalai 'admin'")
    log.info("WhatsApp provider: %s", provider.name)
    yield


app = FastAPI(title="Rangkon", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, max_age=60 * 60 * 12)


@app.middleware("http")
async def same_origin_posts(request: Request, call_next):
    if request.method == "POST" and not request.url.path.startswith("/webhook/"):
        site = request.headers.get("sec-fetch-site")
        if site:
            if site == "cross-site":
                return PlainTextResponse("Permintaan luar ditolak", status_code=403)
            return await call_next(request)
        origin = request.headers.get("origin") or request.headers.get("referer")
        allowed = {
            request.headers.get("host"),
            request.headers.get("x-forwarded-host"),
            urlsplit(settings.public_base_url).netloc,
        }
        if origin and urlsplit(origin).netloc not in allowed:
            return PlainTextResponse("Permintaan luar ditolak", status_code=403)
    return await call_next(request)


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.globals["units"] = settings.units
templates.env.filters["dt"] = services.format_dt

Db = Annotated[Session, Depends(get_db)]


class NotLoggedIn(Exception):
    pass


@app.exception_handler(NotLoggedIn)
def _not_logged_in(request: Request, _exc: NotLoggedIn):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Perlu log masuk"}, status_code=401)
    return RedirectResponse(f"/login?next={request.url.path}", status_code=303)


def require_admin(request: Request) -> None:
    if not request.session.get("admin"):
        raise NotLoggedIn()


Admin = Depends(require_admin)


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session["flash"] = {"message": message, "kind": kind}


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    ctx["flash"] = request.session.pop("flash", None)
    ctx["provider"] = provider.name
    return templates.TemplateResponse(request, name, ctx)


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def get_event(db: Session, event_id: int) -> Event:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(404, "Panggilan tidak dijumpai")
    return event


# --- auth --------------------------------------------------------------------


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/events"):
    return render(request, "login.html", next=next)


@app.post("/login")
def login(request: Request, password: Annotated[str, Form()], next: Annotated[str, Form()] = "/"):
    if secrets.compare_digest(password, settings.admin_password):
        request.session["admin"] = True
        return redirect(next if next.startswith("/") and not next.startswith("//") else "/")
    flash(request, "Kata laluan salah", "error")
    return redirect("/login")


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/login")


@app.get("/", dependencies=[Admin])
def home():
    return redirect("/events")


# --- members -----------------------------------------------------------------


@app.get("/members", response_class=HTMLResponse, dependencies=[Admin])
def members_page(request: Request, db: Db, unit: str = "", q: str = ""):
    stmt = select(Member).order_by(Member.unit, Member.name)
    if unit:
        stmt = stmt.where(Member.unit == unit)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            Member.name.ilike(like) | Member.phone.like(like) | Member.service_no.ilike(like)
        )
    counts = dict(db.execute(select(Member.unit, func.count()).group_by(Member.unit)).all())
    return render(
        request,
        "members.html",
        members=sorted(
            db.scalars(stmt).all(),
            key=lambda m: (services.unit_sort_key(m.unit), m.name.lower()),
        ),
        unit=unit,
        q=q,
        counts=counts,
    )


@app.post("/members", dependencies=[Admin])
def add_member(
    request: Request,
    db: Db,
    name: Annotated[str, Form()],
    phone: Annotated[str, Form()],
    unit: Annotated[str, Form()],
    rank: Annotated[str, Form()] = "",
    service_no: Annotated[str, Form()] = "",
):
    normalized = services.normalize_phone(phone)
    if unit not in settings.units:
        flash(request, "Unit tidak sah", "error")
    elif not normalized:
        flash(request, f"Nombor telefon tidak sah: {phone}", "error")
    elif db.scalar(select(Member).where(Member.phone == normalized)):
        flash(request, f"Nombor {normalized} sudah didaftarkan", "error")
    else:
        db.add(
            Member(
                name=name.strip(),
                phone=normalized,
                unit=unit,
                rank=rank.strip(),
                service_no=service_no.strip(),
                created_at=services.now(),
            )
        )
        db.commit()
        flash(request, f"{name} ditambah ke {unit}")
    return redirect(f"/members?unit={unit}")


@app.post("/members/import", dependencies=[Admin])
async def import_members(
    request: Request, db: Db, file: UploadFile, unit: Annotated[str, Form()] = ""
):
    raw = await file.read()
    if (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        try:
            content = services.xlsx_to_csv(raw)
        except Exception:
            flash(request, "Fail Excel tidak dapat dibaca", "error")
            return redirect("/members")
    else:
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            content = raw.decode("latin-1")
    result = services.import_members_csv(db, content, unit or None)
    if result["skipped"] < 0:
        flash(request, "CSV mesti ada lajur 'nama' dan 'telefon'", "error")
    else:
        flash(
            request,
            f"Import selesai: {result['added']} baru, {result['updated']} dikemas kini, "
            f"{result['skipped']} dilangkau",
        )
    return redirect("/members")


@app.post("/members/{member_id}", dependencies=[Admin])
def update_member(
    request: Request,
    member_id: int,
    db: Db,
    name: Annotated[str, Form()],
    phone: Annotated[str, Form()],
    unit: Annotated[str, Form()],
    rank: Annotated[str, Form()] = "",
    service_no: Annotated[str, Form()] = "",
):
    member = db.get(Member, member_id)
    if member is None:
        raise HTTPException(404)
    normalized = services.normalize_phone(phone)
    clash = normalized and db.scalar(
        select(Member).where(Member.phone == normalized, Member.id != member_id)
    )
    if unit not in settings.units:
        flash(request, "Unit tidak sah", "error")
    elif not normalized:
        flash(request, f"Nombor telefon tidak sah: {phone}", "error")
    elif clash:
        flash(request, f"Nombor {normalized} sudah digunakan oleh {clash.name}", "error")
    else:
        member.name = name.strip()
        member.phone = normalized
        member.unit = unit
        member.rank = rank.strip()
        member.service_no = service_no.strip()
        db.commit()
        flash(request, f"{member.name} dikemas kini")
    return redirect(f"/members?unit={unit}")


@app.post("/members/{member_id}/toggle", dependencies=[Admin])
def toggle_member(member_id: int, db: Db):
    member = db.get(Member, member_id)
    if member:
        member.active = not member.active
        db.commit()
    return redirect("/members")


@app.post("/members/{member_id}/delete", dependencies=[Admin])
def delete_member(request: Request, member_id: int, db: Db):
    member = db.get(Member, member_id)
    if member and member.invitations:
        member.active = False
        db.commit()
        flash(request, f"{member.name} ada rekod panggilan; dinyahaktifkan (rekod dikekalkan)")
    elif member:
        db.delete(member)
        db.commit()
        flash(request, f"{member.name} dipadam")
    return redirect("/members")


# --- events ------------------------------------------------------------------


@app.get("/events", response_class=HTMLResponse, dependencies=[Admin])
def events_page(request: Request, db: Db):
    events = db.scalars(select(Event).order_by(Event.starts_at.desc())).all()
    summaries = {e.id: services.event_dashboard(db, e)["overall"] for e in events}
    return render(
        request,
        "events.html",
        events=events,
        summaries=summaries,
        default_message=services.DEFAULT_MESSAGE,
    )


@app.post("/events", dependencies=[Admin])
def create_event(
    request: Request,
    db: Db,
    title: Annotated[str, Form()],
    location: Annotated[str, Form()],
    starts_at: Annotated[str, Form()],
    message: Annotated[str, Form()],
):
    try:
        when = datetime.fromisoformat(starts_at)
    except ValueError:
        flash(request, "Tarikh/masa tidak sah", "error")
        return redirect("/events")
    event = Event(
        title=title.strip(),
        location=location.strip(),
        starts_at=when,
        message=message.strip() or services.DEFAULT_MESSAGE,
        created_at=services.now(),
    )
    db.add(event)
    db.commit()
    return redirect(f"/events/{event.id}")


@app.get("/events/{event_id}", response_class=HTMLResponse, dependencies=[Admin])
def event_page(request: Request, event_id: int, db: Db):
    event = get_event(db, event_id)
    member_counts = dict(
        db.execute(
            select(Member.unit, func.count()).where(Member.active.is_(True)).group_by(Member.unit)
        ).all()
    )
    sample = services.render_message(
        event.message,
        {
            "nama": "Kpl Ali bin Abu",
            "tajuk": event.title,
            "lokasi": event.location,
            "masa": services.format_dt(event.starts_at),
            "pautan": f"{settings.public_base_url}/c/contoh",
            "unit": settings.units[0] if settings.units else "",
        },
    )
    share_text = services.group_message(event)
    return render(
        request,
        "event.html",
        event=event,
        member_counts=member_counts,
        sample=sample,
        share_text=share_text,
        share_url="https://wa.me/?text=" + quote(share_text),
        open_share=request.query_params.get("kongsi") == "1",
    )


@app.post("/events/{event_id}/share", dependencies=[Admin])
def share_event(
    request: Request,
    event_id: int,
    db: Db,
    target_units: Annotated[list[str], Form()] = [],  # noqa: B006
):
    event = get_event(db, event_id)
    chosen = [u for u in target_units if u in settings.units]
    if not chosen:
        flash(request, "Pilih sekurang-kurangnya satu unit", "error")
        return redirect(f"/events/{event_id}")
    ids = services.create_invitations(db, event, chosen, status="group")
    flash(
        request,
        f"{len(ids)} ahli {', '.join(chosen)} dimasukkan ke senarai panggilan. "
        "Salin mesej dan tampal ke grup WhatsApp.",
    )
    return redirect(f"/events/{event_id}?kongsi=1")


@app.post("/events/{event_id}/send", dependencies=[Admin])
def send_event(
    request: Request,
    event_id: int,
    db: Db,
    background: BackgroundTasks,
    target_units: Annotated[list[str], Form()] = [],  # noqa: B006
):
    event = get_event(db, event_id)
    chosen = [u for u in target_units if u in settings.units]
    if not chosen:
        flash(request, "Pilih sekurang-kurangnya satu unit", "error")
        return redirect(f"/events/{event_id}")
    ids = services.create_invitations(db, event, chosen)
    if ids:
        background.add_task(services.deliver, SessionLocal, ids, provider)
        flash(request, f"{len(ids)} mesej WhatsApp sedang dihantar ke {', '.join(chosen)}")
    else:
        flash(request, "Tiada ahli baru untuk dihantar (semua sudah dipanggil)", "error")
    return redirect(f"/events/{event_id}")


@app.post("/events/{event_id}/resend-failed", dependencies=[Admin])
def resend_failed(request: Request, event_id: int, db: Db, background: BackgroundTasks):
    get_event(db, event_id)
    ids = list(
        db.scalars(
            select(Invitation.id).where(
                Invitation.event_id == event_id, Invitation.status == "failed"
            )
        )
    )
    if ids:
        background.add_task(services.deliver, SessionLocal, ids, provider)
    flash(request, f"Hantar semula {len(ids)} mesej yang gagal")
    return redirect(f"/events/{event_id}")


@app.post("/events/{event_id}/delete", dependencies=[Admin])
def delete_event(request: Request, event_id: int, db: Db):
    event = get_event(db, event_id)
    db.delete(event)
    db.commit()
    flash(request, f"Panggilan '{event.title}' dipadam")
    return redirect("/events")


@app.get("/events/{event_id}/export.csv", dependencies=[Admin])
def export_event(event_id: int, db: Db):
    event = get_event(db, event_id)
    data = services.export_csv(services.event_dashboard(db, event))
    return PlainTextResponse(
        "\ufeff" + data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="rangkon-{event_id}.csv"'},
    )


@app.get("/api/events/{event_id}/dashboard", dependencies=[Admin])
def api_dashboard(event_id: int, db: Db):
    return services.event_dashboard(db, get_event(db, event_id))


def _get_invitation(db: Session, inv_id: int) -> Invitation:
    inv = db.get(Invitation, inv_id)
    if inv is None:
        raise HTTPException(404)
    return inv


@app.post("/api/invitations/{inv_id}/attend", dependencies=[Admin])
def api_toggle_attend(inv_id: int, db: Db):
    inv = _get_invitation(db, inv_id)
    if inv.attended_at:
        inv.attended_at = None
        inv.checkin_method = None
    else:
        services.mark_attended(inv, "admin")
    db.commit()
    return {"attended": inv.attended_at is not None}


@app.post("/api/invitations/{inv_id}/rsvp", dependencies=[Admin])
def api_set_rsvp(inv_id: int, db: Db, answer: Annotated[str, Form()]):
    inv = _get_invitation(db, inv_id)
    if answer == "clear":
        inv.rsvp = inv.rsvp_at = inv.rsvp_via = None
    elif answer in ("accepted", "declined"):
        services.set_rsvp(inv, answer, "admin")
    else:
        raise HTTPException(400, "Jawapan tidak sah")
    db.commit()
    return {"rsvp": inv.rsvp}


@app.post("/api/invitations/{inv_id}/simulate", dependencies=[Admin])
def api_simulate(inv_id: int, db: Db, action: Annotated[str, Form()]):
    """Mimics WhatsApp webhook events when running without a real WhatsApp account."""
    if provider.name != "simulate":
        raise HTTPException(400, "Hanya tersedia dalam mod simulasi")
    inv = _get_invitation(db, inv_id)
    if not inv.wa_message_id:
        raise HTTPException(400, "Mesej belum dihantar")
    at = services.now()
    if action in ("delivered", "read"):
        services.apply_status(inv, action, at)
    elif action in ("TERIMA", "TOLAK"):
        services.record_reply(inv, action, at)
    else:
        raise HTTPException(400, "Tindakan tidak sah")
    db.commit()
    return {"ok": True}


# --- kiosk (on-site check-in by staff) ---------------------------------------


@app.get("/events/{event_id}/kiosk", response_class=HTMLResponse, dependencies=[Admin])
def kiosk_page(request: Request, event_id: int, db: Db):
    return render(request, "kiosk.html", event=get_event(db, event_id), result=None)


@app.post("/events/{event_id}/kiosk", response_class=HTMLResponse, dependencies=[Admin])
def kiosk_checkin(request: Request, event_id: int, db: Db, phone: Annotated[str, Form()]):
    event = get_event(db, event_id)
    normalized = services.normalize_phone(phone)
    inv = None
    if normalized:
        inv = db.scalar(
            select(Invitation)
            .join(Member)
            .where(
                Invitation.event_id == event_id,
                (Invitation.phone == normalized) | (Member.phone == normalized),
            )
        )
    if inv is None:
        result = {"ok": False, "message": f"Tiada panggilan untuk nombor {phone}"}
    elif services.mark_attended(inv, "kiosk"):
        db.commit()
        result = {"ok": True, "message": f"Hadir: {inv.member.rank} {inv.member.name}".strip()}
    else:
        result = {
            "ok": True,
            "message": f"{inv.member.name} sudah direkod hadir "
            f"({services.format_dt(inv.attended_at)})",
        }
    return render(request, "kiosk.html", event=event, result=result)


# --- public pages (link inside the WhatsApp message) -------------------------


def _by_token(db: Session, token: str) -> Invitation:
    inv = db.scalar(select(Invitation).where(Invitation.token == token))
    if inv is None:
        raise HTTPException(404, "Pautan tidak sah")
    return inv


def _public(request: Request, inv: Invitation, note: str | None = None) -> HTMLResponse:
    return render(
        request,
        "public.html",
        inv=inv,
        event=inv.event,
        member=inv.member,
        note=note,
        checkin_open=services.checkin_window_open(inv.event),
    )


@app.get("/c/{token}", response_class=HTMLResponse)
def public_page(request: Request, token: str, db: Db):
    return _public(request, _by_token(db, token))


@app.post("/c/{token}/rsvp", response_class=HTMLResponse)
def public_rsvp(request: Request, token: str, db: Db, answer: Annotated[str, Form()]):
    inv = _by_token(db, token)
    if answer not in ("accepted", "declined"):
        raise HTTPException(400)
    services.set_rsvp(inv, answer, "link")
    db.commit()
    note = "Terima kasih, panggilan DITERIMA." if answer == "accepted" else "Jawapan TOLAK direkod."
    return _public(request, inv, note)


@app.post("/c/{token}/checkin", response_class=HTMLResponse)
def public_checkin(request: Request, token: str, db: Db):
    inv = _by_token(db, token)
    if not services.checkin_window_open(inv.event):
        return _public(request, inv, "Pengesahan kehadiran belum dibuka.")
    if inv.rsvp is None:
        services.set_rsvp(inv, "accepted", "link")
    services.mark_attended(inv, "link")
    db.commit()
    return _public(request, inv, "Kehadiran anda telah direkod.")


def _by_code(db: Session, code: str) -> Event:
    event = db.scalar(select(Event).where(Event.public_code == code))
    if event is None:
        raise HTTPException(404, "Pautan tidak sah")
    return event


@app.get("/p/{code}", response_class=HTMLResponse)
def group_page(request: Request, code: str, db: Db):
    return render(request, "group.html", event=_by_code(db, code), error=None, ident="")


@app.post("/p/{code}", response_class=HTMLResponse)
def group_identify(request: Request, code: str, db: Db, ident: Annotated[str, Form()]):
    event = _by_code(db, code)
    inv = services.find_invitation(db, event, ident)
    if inv is None:
        error = "Nombor ini tiada dalam senarai panggilan. Semak semula atau hubungi pegawai unit."
        return render(request, "group.html", event=event, error=error, ident=ident)
    return redirect(f"/c/{inv.token}")


# --- WhatsApp Cloud API webhook ----------------------------------------------


@app.get("/webhook/whatsapp")
def webhook_verify(request: Request):
    q = request.query_params
    if (
        q.get("hub.mode") == "subscribe"
        and settings.whatsapp_verify_token
        and secrets.compare_digest(q.get("hub.verify_token", ""), settings.whatsapp_verify_token)
    ):
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403)


@app.post("/webhook/whatsapp")
async def webhook_receive(request: Request, db: Db):
    body = await request.body()
    must_sign = settings.whatsapp_app_secret or settings.whatsapp_provider == "cloud"
    if must_sign and not valid_signature(
        settings.whatsapp_app_secret, body, request.headers.get("X-Hub-Signature-256")
    ):
        raise HTTPException(403, "Tandatangan tidak sah")
    return services.handle_webhook(db, await request.json())
