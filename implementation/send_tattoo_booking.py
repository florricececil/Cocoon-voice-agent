"""RBI Implementation — send_tattoo_booking.py (v1 Cocoon)
One responsibility: send CREATE_TATTOO_BOOKING to Integrately webhook.

Contract:
- Inputs via CLI args or structured JSON (inline / file / stdin)
- Secrets from .env (INTEGRATELY_WEBHOOK_URL, STUDIO_NAME, AGENT_NAME, TIMEZONE)
- stdout JSON, exit 0 on success, 1+ on categorized failure
- Validates own outputs, fails loudly, retries max 3x on transport errors.

Pricing (base, from cocoon_studio_kb_v1.md):
  Flash 0-5cm -> from R200 | Small 6-10cm -> from R380
  Medium 11-15cm -> from R500 | Large 15cm+ -> from R600+ (consultation)
Hours (Africa/Johannesburg): Mon-Fri 16:00-23:00, Sat-Sun 08:00-23:00.

Examples:
  python implementation/send_tattoo_booking.py --name "Jane" --phone "0681067566" --design "rose" --placement "Forearm" --size-cm 8 --ink black --studio --start "2026-09-20T10:00:00+02:00" --dry-run
  python implementation/send_tattoo_booking.py --json-file payload.json --dry-run
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-().]{5,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SIZE_BANDS = [  # (max_cm, category, price_label)
    (5, "Flash", "from R200"),
    (10, "Small", "from R380"),
    (15, "Medium", "from R500"),
    (float("inf"), "Large", "from R600+ (consultation required)"),
]
ALLOWED_INKS = {"black", "red"}


def load_env(path: Path) -> None:
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


def fail(msg: str, code: int = 2, extra: dict | None = None):
    out = {"status": "error", "error": msg}
    if extra:
        out.update(extra)
    print(json.dumps(out))
    sys.exit(code)


def studio_tz():
    name = os.getenv("TIMEZONE", "Africa/Johannesburg").strip() or "Africa/Johannesburg"
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        return timezone(timedelta(hours=2))  # SAST fallback


def parse_dt(s: str) -> datetime:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        fail(f"invalid datetime '{s}': expected ISO-8601 e.g. 2026-09-20T10:00:00+02:00", 2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=studio_tz())
    return dt


def check_hours(start: datetime, end: datetime) -> str:
    """Return '' if inside Cocoon hours, else human-readable reason."""
    tz = studio_tz()
    s, e = start.astimezone(tz), end.astimezone(tz)
    if s.date() != e.date():
        return "booking must start and end on the same day"
    wd = s.weekday()  # 0=Mon
    open_h = 16 if wd < 5 else 8
    if not (open_h <= s.hour + s.minute / 60 < 23 and 0 < e.hour + e.minute / 60 <= 23 and e > s):
        days = "Mon–Fri 16:00–23:00" if wd < 5 else "Sat–Sun 08:00–23:00"
        return f"outside operating hours ({days} Africa/Johannesburg)"
    return ""


def normalize_phone(raw: str) -> str:
    p = raw.strip()
    if not PHONE_RE.match(p):
        fail(f"invalid phone_number '{raw}': expected mobile/WhatsApp e.g. 0681067566 or +27681067566", 2)
    return re.sub(r"[^\d+]", "", p)


def size_from_cm(cm: float) -> tuple[str, str]:
    for max_cm, cat, price in SIZE_BANDS:
        if cm <= max_cm:
            return cat, price
    return "Large", "from R600+ (consultation required)"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Send CREATE_TATTOO_BOOKING webhook")
    p.add_argument("--name", default="")
    p.add_argument("--phone", default="")
    p.add_argument("--email", default="")
    p.add_argument("--design", default="", help="Tattoo design description (required)")
    p.add_argument("--placement", default="", help="Body placement, e.g. Forearm/Bicep/Ankle (required)")
    p.add_argument("--size-cm", type=float, default=None, help="Approx size in cm")
    p.add_argument("--size-category", default="", help="Flash|Small|Medium|Large (derived from --size-cm if omitted)")
    p.add_argument("--ink", default="", help="Ink colours, e.g. 'black' or 'black/red' (required)")
    p.add_argument("--house-call", action="store_true", help="House call requested")
    p.add_argument("--studio", action="store_true", help="Studio session (default)")
    p.add_argument("--start", default="")
    p.add_argument("--end", default="", help="Default start+60min for tattoo sessions")
    p.add_argument("--notes", default="")
    p.add_argument("--json", dest="json_inline", default="")
    p.add_argument("--json-file", default="")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--timeout", type=int, default=15)
    return p.parse_args(argv)


def load_payload(args) -> dict:
    data: dict = {}
    if args.json_file:
        try:
            data.update(json.loads(Path(args.json_file).read_text(encoding="utf-8")))
        except Exception as e:
            fail(f"invalid --json-file: {e}", 2)
    if args.json_inline:
        try:
            data.update(json.loads(args.json_inline))
        except Exception as e:
            fail(f"invalid --json: {e}", 2)
    if not sys.stdin.isatty():
        try:
            raw = sys.stdin.read().strip()
            if raw:
                data.update(json.loads(raw))
        except Exception as e:
            fail(f"invalid stdin JSON: {e}", 2)
    caller = data.get("caller", {}) if isinstance(data.get("caller"), dict) else {}
    tat = data.get("tattoo_details", {}) if isinstance(data.get("tattoo_details"), dict) else {}
    booking = data.get("booking_details", {}) if isinstance(data.get("booking_details"), dict) else {}
    is_hc = args.house_call or bool(data.get("is_house_call", tat.get("is_house_call", False)))
    if not args.house_call and not args.studio and isinstance(tat.get("is_house_call"), bool):
        is_hc = tat["is_house_call"]
    return {
        "name": args.name or data.get("name") or data.get("caller_name") or caller.get("name", "") or caller.get("caller_name", ""),
        "phone": args.phone or data.get("phone") or data.get("phone_number") or data.get("caller_phone") or caller.get("phone_number", "") or caller.get("caller_phone", ""),
        "email": args.email or data.get("email") or data.get("caller_email") or caller.get("email", "") or caller.get("caller_email", ""),
        "design": args.design or data.get("design") or data.get("design_description") or tat.get("design_description", ""),
        "placement": args.placement or data.get("placement") or tat.get("placement", ""),
        "size_cm": args.size_cm if args.size_cm is not None else data.get("size_cm", tat.get("size_cm")),
        "size_category": args.size_category or data.get("size_category") or tat.get("size_category", ""),
        "ink": args.ink or data.get("ink") or data.get("ink_colors") or tat.get("ink_colors", ""),
        "is_house_call": is_hc,
        "start": args.start or data.get("start") or data.get("start_time") or booking.get("start_time", ""),
        "end": args.end or data.get("end") or data.get("end_time") or booking.get("end_time", ""),
        "notes": args.notes or data.get("notes") or booking.get("notes", "") or data.get("call_summary", ""),
    }


def main(argv=None) -> int:
    args = parse_args(argv)
    load_env(ENV_PATH)
    d = load_payload(args)

    name = str(d["name"]).strip()
    if not name:
        fail("missing required field: name", 2)
    phone = normalize_phone(str(d["phone"]).strip()) if str(d["phone"]).strip() else fail("missing required field: phone", 2)  # type: ignore
    email = str(d["email"]).strip()
    if email and not EMAIL_RE.match(email):
        fail(f"invalid email '{email}'", 2)
    design = str(d["design"]).strip()
    if not design:
        fail("missing required field: design (design_description)", 2)
    placement = str(d.get("placement", "")).strip()
    if not placement:
        fail("missing required field: placement (e.g. Forearm, Bicep, Ankle)", 2)

    # Size -> category + price
    size_cm = d["size_cm"]
    size_cat = str(d["size_category"]).strip().capitalize()
    price = ""
    if size_cm is not None:
        try:
            cm = float(size_cm)
        except Exception:
            fail(f"invalid size_cm '{size_cm}': expected number (cm)", 2)
        if cm <= 0 or cm > 200:
            fail(f"invalid size_cm '{cm}': expected 0–200 cm", 2)
        size_cat, price = size_from_cm(cm)
    elif size_cat in ("Flash", "Small", "Medium", "Large"):
        price = next(p for _, c, p in SIZE_BANDS if c == size_cat)
    else:
        fail("missing size: pass --size-cm (cm) or --size-category Flash|Small|Medium|Large", 2)

    # Ink policy: black/red only — warn, don't hard-block (consultation can reinterpret)
    ink_raw = str(d["ink"]).strip().lower()
    if not ink_raw:
        fail("missing required field: ink (black and/or red)", 2)
    ink_parts = {t.strip() for t in re.split(r"[/,+& ]+", ink_raw) if t.strip() and t.strip() != "and"}
    policy_warning = ""
    if not ink_parts.issubset(ALLOWED_INKS):
        policy_warning = f"studio works in black/red only; requested '{d['ink']}' needs artist reinterpretation"

    start_raw = str(d["start"]).strip()
    if not start_raw:
        fail("missing required field: start (ISO-8601)", 2)
    start_dt = parse_dt(start_raw)
    end_dt = parse_dt(str(d["end"]).strip()) if str(d["end"]).strip() else start_dt + timedelta(minutes=60)
    if end_dt <= start_dt:
        fail("invalid window: end_time must be after start_time", 2)
    if start_dt < datetime.now(timezone.utc) - timedelta(minutes=1):
        fail("invalid start_time: booking is in the past", 2)
    hours_err = check_hours(start_dt, end_dt)
    if hours_err:
        fail(f"{hours_err}", 2, {"hint": "Mon–Fri 16:00–23:00, Sat–Sun 08:00–23:00 Africa/Johannesburg"})

    studio = os.getenv("STUDIO_NAME", "The Cocoon").strip() or "The Cocoon"
    agent = os.getenv("AGENT_NAME", "Wish").strip() or "Wish"
    is_hc = bool(d["is_house_call"])
    notes = str(d["notes"]).strip()
    if is_hc and "house call" not in notes.lower():
        notes = (notes + " | House call requested (+travel/setup surcharge).").strip(" |")

    payload = {
        "action": "CREATE_TATTOO_BOOKING",
        "studio_name": studio,
        "agent_name": agent,
        "caller": {"name": name, "phone_number": phone, "email": email, "whatsapp_enabled": True},
        "tattoo_details": {
            "design_description": design,
            "placement": placement,
            "size_category": size_cat,
            "ink_colors": ink_raw,
            "is_house_call": is_hc,
            "estimated_price_range": price,
        },
        "booking_details": {
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "event_title": f"Tattoo Booking: {name} ({size_cat})",
            "notes": notes,
        },
        "targets": {"google_calendar": True, "google_sheets": True, "whatsapp_message": True},
    }
    if policy_warning:
        payload["policy_warning"] = policy_warning  # internal flag for Integrately/Sheets; never spoken verbatim

    assert payload["action"] == "CREATE_TATTOO_BOOKING"
    assert payload["tattoo_details"]["size_category"] in ("Flash", "Small", "Medium", "Large")

    webhook = os.getenv("INTEGRATELY_WEBHOOK_URL", "").strip()
    if args.dry_run or not webhook:
        print(json.dumps({"status": "ok", "dry_run": True, "payload": payload}))
        return 0

    body = json.dumps(payload).encode("utf-8")
    last_err = ""
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(webhook, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=args.timeout) as resp:
                rb = resp.read().decode("utf-8", "replace")[:4000]
                if 200 <= resp.status < 300:
                    print(json.dumps({"status": "ok", "attempt": attempt, "http_status": resp.status, "response": rb, "payload": payload}))
                    return 0
                last_err = f"HTTP {resp.status}: {rb}"
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:1000]}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        time.sleep(attempt)
    fail("webhook delivery failed after 3 attempts", 3, {"detail": last_err, "payload": payload})
    return 3


if __name__ == "__main__":
    sys.exit(main())
