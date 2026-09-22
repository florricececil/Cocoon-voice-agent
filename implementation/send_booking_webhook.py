"""RBI Implementation — send_booking_webhook.py (v1)
One responsibility: send CREATE_BOOKING_AND_LOG to Integrately webhook.

Contract:
- Inputs via CLI args or structured JSON (inline / file / stdin)
- Secrets from .env (INTEGRATELY_WEBHOOK_URL, BUSINESS_NAME, TIMEZONE)
- stdout JSON, exit 0 on success, 1+ on categorized failure
- Validates own outputs, fails loudly, retries max 3x on transport errors.

Examples:
  python implementation/send_booking_webhook.py --name "Jane Doe" --phone "+15551234567" --start "2026-09-17T10:00:00+00:00" --dry-run
  python implementation/send_booking_webhook.py --json-file payload.json
  echo '{"name":"Jane","phone":"+1555...","start":"..."}' | python implementation/send_booking_webhook.py --dry-run
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


def parse_dt(s: str) -> datetime:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        fail(f"invalid datetime '{s}': expected ISO-8601 e.g. 2026-09-17T10:00:00+00:00", 2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def normalize_phone(raw: str) -> str:
    p = raw.strip()
    if not PHONE_RE.match(p):
        fail(f"invalid phone_number '{raw}': expected mobile/WhatsApp digits, e.g. +15551234567", 2)
    digits = re.sub(r"[^\d+]", "", p)
    return digits


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Send CREATE_BOOKING_AND_LOG webhook")
    p.add_argument("--name", default="", help="Caller full name (required)")
    p.add_argument("--phone", default="", help="Caller mobile/WhatsApp (required)")
    p.add_argument("--email", default="", help="Caller email (optional)")
    p.add_argument("--start", default="", help="Booking start ISO-8601 (required)")
    p.add_argument("--end", default="", help="Booking end ISO-8601 (default start+30min)")
    p.add_argument("--notes", default="", help="Call summary / follow-up note")
    p.add_argument("--business-id", default="", help="Business ID (default $BUSINESS_NAME)")
    p.add_argument("--event-title", default="", help="Calendar title (default 'Call with NAME')")
    p.add_argument("--no-whatsapp", action="store_true", help="Set whatsapp_enabled=false")
    p.add_argument("--json", dest="json_inline", default="", help="Inline JSON payload")
    p.add_argument("--json-file", default="", help="Path to JSON payload file")
    p.add_argument("--dry-run", action="store_true", help="Validate + print payload, no HTTP")
    p.add_argument("--timeout", type=int, default=15, help="HTTP timeout seconds")
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
    # Support both flat CLI names and nested directive shape
    caller = data.get("caller", {}) if isinstance(data.get("caller"), dict) else {}
    booking = data.get("booking_details", {}) if isinstance(data.get("booking_details"), dict) else {}
    merged = {
        "name": args.name or data.get("name") or caller.get("name", ""),
        "phone": args.phone or data.get("phone") or data.get("phone_number") or caller.get("phone_number", ""),
        "email": args.email or data.get("email") or caller.get("email", ""),
        "start": args.start or data.get("start") or data.get("start_time") or booking.get("start_time", ""),
        "end": args.end or data.get("end") or data.get("end_time") or booking.get("end_time", ""),
        "notes": args.notes or data.get("notes") or booking.get("notes", "") or data.get("call_summary", ""),
        "business_id": args.business_id or data.get("business_id") or data.get("businessId", ""),
        "event_title": args.event_title or data.get("event_title") or booking.get("event_title", ""),
        "whatsapp_enabled": (not args.no_whatsapp)
        if (args.no_whatsapp or "whatsapp_enabled" not in data and "whatsapp_enabled" not in caller)
        else bool(data.get("whatsapp_enabled", caller.get("whatsapp_enabled", True))),
    }
    return merged


def main(argv=None) -> int:
    args = parse_args(argv)
    load_env(ENV_PATH)
    d = load_payload(args)

    name = str(d["name"]).strip()
    if not name:
        fail("missing required field: name (caller full name)", 2)
    phone = normalize_phone(str(d["phone"]).strip()) if str(d["phone"]).strip() else fail("missing required field: phone", 2)  # type: ignore
    email = str(d["email"]).strip()
    if email and not EMAIL_RE.match(email):
        fail(f"invalid email '{email}'", 2)
    start_raw = str(d["start"]).strip()
    if not start_raw:
        fail("missing required field: start (ISO-8601 start_time)", 2)
    start_dt = parse_dt(start_raw)
    end_raw = str(d["end"]).strip()
    end_dt = parse_dt(end_raw) if end_raw else start_dt + timedelta(minutes=30)
    if end_dt <= start_dt:
        fail("invalid booking window: end_time must be after start_time", 2)
    if start_dt < datetime.now(timezone.utc) - timedelta(minutes=1):
        fail("invalid start_time: booking is in the past", 2)

    business_id = str(d["business_id"]).strip() or os.getenv("BUSINESS_NAME", "").strip()
    if not business_id:
        fail("missing business_id: pass --business-id or set BUSINESS_NAME in .env", 2)
    event_title = str(d["event_title"]).strip() or f"Call with {name}"

    payload = {
        "action": "CREATE_BOOKING_AND_LOG",
        "business_id": business_id,
        "caller": {
            "name": name,
            "phone_number": phone,
            "email": email,
            "whatsapp_enabled": bool(d["whatsapp_enabled"]),
        },
        "booking_details": {
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "event_title": event_title,
            "notes": str(d["notes"]),
        },
        "targets": {"google_calendar": True, "google_sheets": True, "whatsapp_message": True},
    }

    # Self-validation before any I/O (fail loudly)
    assert payload["action"] == "CREATE_BOOKING_AND_LOG"
    assert payload["caller"]["name"] and payload["caller"]["phone_number"]
    assert payload["booking_details"]["start_time"] < payload["booking_details"]["end_time"]

    webhook = os.getenv("INTEGRATELY_WEBHOOK_URL", "").strip()
    if args.dry_run or not webhook:
        print(json.dumps({"status": "ok", "dry_run": True, "payload": payload}))
        return 0

    body = json.dumps(payload).encode("utf-8")
    last_err = ""
    for attempt in range(1, 4):  # retry budget: 3
        try:
            req = urllib.request.Request(webhook, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=args.timeout) as resp:
                resp_body = resp.read().decode("utf-8", "replace")[:4000]
                if 200 <= resp.status < 300:
                    print(json.dumps({"status": "ok", "attempt": attempt, "http_status": resp.status, "response": resp_body, "payload": payload}))
                    return 0
                last_err = f"HTTP {resp.status}: {resp_body}"
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:1000]}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        time.sleep(attempt)  # 1s, 2s backoff
    fail("webhook delivery failed after 3 attempts", 3, {"detail": last_err, "payload": payload})
    return 3


if __name__ == "__main__":
    sys.exit(main())
