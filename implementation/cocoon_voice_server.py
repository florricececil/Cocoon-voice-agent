"""RBI Implementation — cocoon_voice_server.py (v1.1)
FastAPI relay for Wish @ The Cocoon. Reuses send_tattoo_booking validation.

RBI mapping:
- Rules: rules/cocoon_*_v2.md + cocoon_studio_kb_v1.md (persona, hours, pricing, ink policy)
- Brain: PersonaPlex / caller agent (not here) — collects slots, POSTs here only after explicit confirmation
- Implementation (this file): validate -> build CREATE_TATTOO_BOOKING -> POST Integrately (3x retry)

Tool contract (book_tattoo_appointment):
  POST /webhook/booking
  Required: caller_name, caller_phone, placement, design_description,
            ink_colors, start_time (ISO-8601), size_category (Flash|Small|Medium|Large)
  Optional (backward-compat): caller_email, size_cm, is_house_call,
            end_time, call_summary, estimated_price_range

Endpoints:
  GET  /                    health (no secrets)
  GET  /config              safe studio config (no secrets)
  POST /webhook/booking     validate + queue relay; returns queued ok, relay runs in background

Secrets (never hardcoded): INTEGRATELY_WEBHOOK_URL, STUDIO_NAME, AGENT_NAME, TIMEZONE.
Local: .env | Colab: runtime secrets / os.environ.

Run locally (no tunnel):  python implementation/cocoon_voice_server.py --no-serve --dry-run-test
Serve locally:            python implementation/cocoon_voice_server.py
Colab T4: see colab run notes at bottom (ngrok optional, PersonaPlex separate cell).
"""
import argparse
import json
import os
import sys
from datetime import timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
sys.path.insert(0, str(Path(__file__).resolve().parent))

WISH_SYSTEM_PROMPT = (
    "You are Wish, a relaxed, professional, knowledgeable receptionist for The Cocoon tattoo studio. "
    "Welcoming, straightforward, clear, artistic. Keep spoken replies to 1-2 sentences. "
    "Backchannel naturally (gotcha, makes sense, definitely). "
    "House: WhatsApp/Phone 068 106 7566, email th3kocoon@gmail.com. "
    "Black and red ink ONLY — gently decline full-colour requests. "
    "Hours Africa/Johannesburg: Mon-Fri 16:00-23:00, Sat-Sun 08:00-23:00. Never book outside hours. "
    "Pricing base (final depends on detail/placement/house-call surcharge): Flash 0-5cm from R200; "
    "Small 6-10cm from R380; Medium 11-15cm from R500; Large 15cm+ from R600+ (consultation). "
    "Intake order: name, phone/WhatsApp, design+placement+size+ink, studio vs house call (+fee), date/time, "
    "explicit lock-in confirmation. Never speak JSON or confirm without tool success."
)


def load_env(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(dotenv_path=path)
        return
    except ImportError:
        pass
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()

try:
    from send_tattoo_booking import (  # reuse RBI validation: hours, pricing, ink, phone
        check_hours,
        normalize_phone,
        parse_dt,
        size_from_cm,
    )
except Exception as e:
    print(json.dumps({"status": "error", "error": f"cannot import send_tattoo_booking helpers: {e}"}))
    raise

STUDIO_CONFIG = {
    "name": os.getenv("STUDIO_NAME", "The Cocoon").strip() or "The Cocoon",
    "agent_name": os.getenv("AGENT_NAME", "Wish").strip() or "Wish",
    "email": os.getenv("STUDIO_EMAIL", "th3kocoon@gmail.com").strip() or "th3kocoon@gmail.com",
    "phone": os.getenv("STUDIO_PHONE", "068 106 7566").strip() or "068 106 7566",
    "hours": "Mon-Fri: 16:00-23:00, Sat-Sun: 08:00-23:00 (Africa/Johannesburg)",
    "colors": "Black and Red ink ONLY",
    "pricing": {
        "Flash (0-5cm)": "from R200",
        "Small (6-10cm)": "from R380",
        "Medium (11-15cm)": "from R500",
        "Large (15cm+)": "from R600+ (Consultation required)",
    },
}


def validate_booking(data: dict) -> tuple[dict, str]:
    """Validate raw booking dict. Returns (payload, policy_warning). Raises ValueError on failure."""
    import re

    def need(key: str) -> str:
        v = str(data.get(key, "") or "").strip()
        if not v:
            raise ValueError(f"missing required field: {key}")
        return v

    name = need("caller_name")
    phone = normalize_phone(need("caller_phone"))
    email = str(data.get("caller_email", "") or "").strip()
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise ValueError(f"invalid email '{email}'")
    design = need("design_description")
    placement = need("placement")
    size_cat = str(data.get("size_category", "") or "").strip().capitalize()
    size_cm = data.get("size_cm")
    if size_cm is not None:
        size_cat, price = size_from_cm(float(size_cm))
    elif size_cat in ("Flash", "Small", "Medium", "Large"):
        price = next(p for _, c, p in [(5, "Flash", "from R200"), (10, "Small", "from R380"), (15, "Medium", "from R500"), (float("inf"), "Large", "from R600+ (consultation required)")] if c == size_cat)
    else:
        raise ValueError("missing size: size_cm or size_category Flash|Small|Medium|Large")
    ink = need("ink_colors").strip()
    parts = {t for t in re.split(r"[/,+& ]+", ink.lower()) if t and t != "and"}
    warning = "" if parts.issubset({"black", "red"}) else f"studio works in black/red only; requested '{ink}' needs reinterpretation"
    start = parse_dt(need("start_time"))
    end_raw = str(data.get("end_time", "") or "").strip()
    from datetime import timedelta as _td

    end = parse_dt(end_raw) if end_raw else start + _td(minutes=60)
    if end <= start:
        raise ValueError("end_time must be after start_time")
    from datetime import datetime as _dt, timezone as _tz

    if start < _dt.now(_tz.utc) - _td(minutes=1):
        raise ValueError("start_time is in the past")
    herr = check_hours(start, end)
    if herr:
        raise ValueError(herr)
    is_hc = bool(data.get("is_house_call", False))
    notes = str(data.get("call_summary", "") or "").strip()
    if is_hc and "house call" not in notes.lower():
        notes = (notes + " | House call requested (+travel/setup surcharge).").strip(" |")
    payload = {
        "action": "CREATE_TATTOO_BOOKING",
        "studio_name": STUDIO_CONFIG["name"],
        "agent_name": STUDIO_CONFIG["agent_name"],
        "caller": {"name": name, "phone_number": phone, "email": email, "whatsapp_enabled": True},
        "tattoo_details": {
            "design_description": design,
            "placement": placement,
            "size_category": size_cat,
            "ink_colors": ink.lower(),
            "is_house_call": is_hc,
            "estimated_price_range": price,
        },
        "booking_details": {
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "event_title": f"Tattoo Booking: {name} ({size_cat})",
            "notes": notes,
        },
        "targets": {"google_calendar": True, "google_sheets": True, "whatsapp_message": True},
    }
    if warning:
        payload["policy_warning"] = warning
    return payload, warning


def post_to_integrately(payload: dict, timeout: int = 15) -> dict:
    """POST payload with 3x retry. Returns result dict, raises RuntimeError after 3 failures."""
    import time
    import urllib.request
    import urllib.error

    webhook = os.getenv("INTEGRATELY_WEBHOOK_URL", "").strip()
    if not webhook:
        return {"status": "ok", "dry_run": True, "payload": payload}
    try:
        import requests  # type: ignore

        last = ""
        for attempt in range(1, 4):
            try:
                r = requests.post(webhook, json=payload, timeout=timeout)
                if 200 <= r.status_code < 300:
                    return {"status": "ok", "attempt": attempt, "http_status": r.status_code, "response": r.text[:4000]}
                last = f"HTTP {r.status_code}: {r.text[:1000]}"
            except Exception as e:
                last = f"{type(e).__name__}: {e}"
            time.sleep(attempt)
        raise RuntimeError(f"webhook failed after 3 attempts: {last}")
    except ImportError:
        body = json.dumps(payload).encode()
        last = ""
        for attempt in range(1, 4):
            try:
                req = urllib.request.Request(webhook, data=body, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    rb = resp.read().decode("utf-8", "replace")[:4000]
                    if 200 <= resp.status < 300:
                        return {"status": "ok", "attempt": attempt, "http_status": resp.status, "response": rb}
                    last = f"HTTP {resp.status}: {rb}"
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:1000]}"
            except Exception as e:
                last = f"{type(e).__name__}: {e}"
            time.sleep(attempt)
        raise RuntimeError(f"webhook failed after 3 attempts: {last}")


def create_app():
    from fastapi import BackgroundTasks, FastAPI
    from pydantic import BaseModel

    class BookingPayload(BaseModel):
        caller_name: str
        caller_phone: str
        caller_email: str = ""
        design_description: str
        placement: str
        size_category: str = ""
        size_cm: float | None = None
        ink_colors: str
        is_house_call: bool = False
        estimated_price_range: str = ""
        start_time: str
        end_time: str = ""
        call_summary: str = ""

    app = FastAPI(title="The Cocoon Voice Agent")

    @app.get("/")
    def health_check():
        return {"status": "Online", "agent": STUDIO_CONFIG["agent_name"], "studio": STUDIO_CONFIG["name"], "system_prompt_active": True}

    @app.get("/config")
    def safe_config():
        return {**STUDIO_CONFIG, "system_prompt": WISH_SYSTEM_PROMPT}

    @app.post("/webhook/booking")
    def trigger_booking(payload: BookingPayload, background_tasks: BackgroundTasks):
        raw = payload.model_dump()
        try:
            built, _ = validate_booking(raw)
        except ValueError as e:
            from fastapi.responses import JSONResponse

            return JSONResponse(status_code=422, content={"status": "error", "error": str(e)})
        background_tasks.add_task(post_to_integrately, built)
        return {"status": "Booking payload queued for Integrately", "event_title": built["booking_details"]["event_title"]}

    return app


def dry_run_test() -> int:
    sample = {
        "caller_name": "Dry Run",
        "caller_phone": "0681067566",
        "design_description": "rose",
        "placement": "Forearm",
        "size_cm": 8,
        "ink_colors": "black",
        "is_house_call": False,
        "start_time": "2026-09-20T10:00:00+02:00",
        "call_summary": "server self-test",
    }
    try:
        payload, warn = validate_booking(sample)
    except ValueError as e:
        print(json.dumps({"status": "error", "error": str(e)}))
        return 2
    print(json.dumps({"status": "ok", "dry_run": True, "policy_warning": warn, "payload": payload}, indent=2))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-serve", action="store_true", help="Validate only, do not start server")
    ap.add_argument("--dry-run-test", action="store_true", help="Print validated sample payload and exit")
    a = ap.parse_args()
    if a.dry_run_test or a.no_serve:
        sys.exit(dry_run_test())
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=a.port)


# --- Colab T4 run notes (do NOT run ngrok locally without a token) ---
# Cell 1 (deps + repo, fixed URL):
#   !pip install pyngrok fastapi "uvicorn[standard]" pydantic requests nest_asyncio
#   !git clone https://github.com/NVIDIA/PersonaPlex.git
#   # PersonaPlex model setup per its README (weights + audio deps) — separate cell, needs T4.
# Cell 2 (this server; set secrets first):
#   import os
#   os.environ["INTEGRATELY_WEBHOOK_URL"] = "<from Colab Secrets>"
#   os.environ["STUDIO_NAME"] = "The Cocoon"; os.environ["AGENT_NAME"] = "Wish"
#   os.environ["TIMEZONE"] = "Africa/Johannesburg"
#   # copy implementation/send_tattoo_booking.py + implementation/cocoon_voice_server.py to Colab, then:
#   from cocoon_voice_server import create_app, WISH_SYSTEM_PROMPT
#   # pass WISH_SYSTEM_PROMPT to PersonaPlex as the role prompt; expose app via ngrok:
#   from pyngrok import ngrok; import nest_asyncio; import uvicorn
#   ngrok.set_auth_token("<NGROK_AUTHTOKEN from Colab Secrets>")
#   nest_asyncio.apply(); print(ngrok.connect(8000))
#   uvicorn.run(create_app(), host="0.0.0.0", port=8000)
