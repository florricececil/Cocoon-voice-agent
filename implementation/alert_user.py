"""RBI Notification Protocol — alert_user.py
Deterministic escalation / off-call alert tool.

Usage (per AGENTS.md):
    python implementation/alert_user.py success
    python implementation/alert_user.py waiting
    python implementation/alert_user.py success --message "Transfer failed: line busy"
    echo '{"status":"waiting","message":"Need human"}' | python implementation/alert_user.py --json

Contract (Implementation layer):
- Inputs via CLI args or structured JSON payload (stdin / --json-file)
- Loads secrets from .env (never hardcode)
- Outputs JSON via stdout
- Exit 0 on success, 1+ on categorized failure
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
TMP_DIR = BASE_DIR / ".tmp"
ALERT_LOG = TMP_DIR / "alert_log.jsonl"


def load_env(path: Path) -> None:
    """Minimal .env loader. Prefers python-dotenv if installed, else manual parse."""
    if not path.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(dotenv_path=path)
        return
    except ImportError:
        pass
    # Fallback: simple KEY=VALUE parse, no interpolation
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="RBI user alert / escalation tool")
    p.add_argument(
        "status",
        nargs="?",
        choices=["success", "waiting"],
        help="success = post-call summary / VIP notice; waiting = BlockedOnUser, needs human",
    )
    p.add_argument("--message", default="", help="Human-readable alert detail")
    p.add_argument("--blocked-on-user", action="store_true", help="Set BlockedOnUser=True")
    p.add_argument("--json", dest="json_payload", default="", help="Inline JSON payload string")
    p.add_argument("--json-file", default="", help="Path to JSON payload file")
    p.add_argument("--channel", default="stdout", help="Notification channel (stdout only in v1)")
    return p.parse_args(argv)


def load_payload(args) -> dict:
    payload: dict = {}
    # 1. JSON file
    if args.json_file:
        try:
            with open(args.json_file, encoding="utf-8") as f:
                payload.update(json.load(f))
        except Exception as e:
            print(json.dumps({"status": "error", "error": f"invalid --json-file: {e}"}))
            sys.exit(2)
    # 2. Inline JSON
    if args.json_payload:
        try:
            payload.update(json.loads(args.json_payload))
        except Exception as e:
            print(json.dumps({"status": "error", "error": f"invalid --json: {e}"}))
            sys.exit(2)
    # 3. Stdin JSON (only if piped, don't block on TTY)
    if not sys.stdin.isatty():
        try:
            raw = sys.stdin.read().strip()
            if raw:
                payload.update(json.loads(raw))
        except Exception as e:
            print(json.dumps({"status": "error", "error": f"invalid stdin JSON: {e}"}))
            sys.exit(2)
    # 4. CLI overrides
    if args.status:
        payload["status"] = args.status
    if args.message:
        payload["message"] = args.message
    if args.blocked_on_user:
        payload["blocked_on_user"] = True
    if args.channel:
        payload["channel"] = args.channel
    return payload


def main(argv=None) -> int:
    args = parse_args(argv)
    load_env(ENV_PATH)
    payload = load_payload(args)

    status = payload.get("status")
    if status not in ("success", "waiting"):
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": "missing/invalid status: expected 'success' or 'waiting'",
                    "usage": "python implementation/alert_user.py [success|waiting] [--message TEXT]",
                }
            )
        )
        return 2

    blocked_on_user = bool(payload.get("blocked_on_user", status == "waiting"))
    message = str(payload.get("message", "")).strip()
    if status == "waiting" and not message:
        message = "Human receptionist intervention needed."
    if status == "success" and not message:
        message = "Post-call summary logged."

    # Per AGENTS.md: always call this before human transfer when BlockedOnUser=True.
    # v1 is deterministic + side-effect free except local log; wire real
    # telephony/Slack/SMS here using .env secrets in v2.
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "alert": status,
        "blocked_on_user": blocked_on_user,
        "message": message,
        "channel": payload.get("channel", "stdout"),
    }
    try:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        with ALERT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        print(json.dumps({"status": "error", "error": f"failed to write alert log: {e}"}))
        return 3

    # Validate output schema before emitting (fail loudly)
    assert record["alert"] in ("success", "waiting")
    assert isinstance(record["ts"], str)

    print(json.dumps({"status": "ok", **record}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
