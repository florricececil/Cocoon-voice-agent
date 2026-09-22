# Appointment Booking & Data Collection — v1 (2026-09-16)

## Goal

Collect validated slots, get explicit confirmation, then execute one `CREATE_BOOKING_AND_LOG` webhook (Calendar + Sheets + WhatsApp).

## Required Inputs

- `name` (full name, required)
- `phone_number` (mobile/WhatsApp, required — normalize to digits with `+` prefix where possible)
- `email` (optional — for calendar invite; accept "skip"/"no email")
- `start_time` + `end_time` (required for BOOKING; ISO-8601 with timezone; default duration 30 min if only start given)
- `notes` (short call summary)
- `business_id` (from `.env` `BUSINESS_NAME`)

## Script (one slot at a time, 1–2 sentences per turn)

1. Name: "Great! May I have your full name?"
2. Phone: "And what is the best mobile or WhatsApp number to reach you at?"
3. Email: "And your email address for the calendar invite?" (accept skip gracefully: "Got it — we'll use WhatsApp then.")
4. Time: "What date and time work best for you?" Normalize to ISO-8601; echo back in caller-friendly form with timezone.
5. Confirmation (mandatory, verbatim pattern): "Perfect. I have [Name] for [Date/Time] at [Phone Number]. Should I confirm this booking?"
6. Only on explicit "yes" → invoke tool. On "no"/correction → fix slot, re-confirm.

FOLLOWUP variant (no date): collect name + phone + what the follow-up is about → confirm: "Just to confirm — [Name] at [Phone], you'd like us to [follow-up note]. Should I pass that on?" → same webhook with `notes` filled and `start_time` = now if no date.

## Scripts / Tools to Invoke

| Step | Tool | Inputs | Expected Output |
| ---- | ---- | ------ | --------------- |
| 1 | `implementation/send_booking_webhook.py` | `--name --phone --email --start --end --notes` (or `--json-file`) | `{"status":"ok","booking_id":...}` exit 0 |
| 2 | `python implementation/alert_user.py success` | `--message "Booking <id> for <name>"` | exit 0 |

Webhook payload shape (do NOT read aloud):
```json
{
  "action": "CREATE_BOOKING_AND_LOG",
  "business_id": "{{BUSINESS_NAME}}",
  "caller": {"name": "...", "phone_number": "...", "email": "...", "whatsapp_enabled": true},
  "booking_details": {"start_time": "ISO-8601", "end_time": "ISO-8601", "event_title": "Call with {{NAME}}", "notes": "..."},
  "targets": {"google_calendar": true, "google_sheets": true, "whatsapp_message": true}
}
```

Brain must: validate slots before invoking → run script → validate `status=ok` + `booking_id`/echo → persist to `.tmp/call_state.json` → speak result briefly: "You're confirmed for [Date/Time]. You'll also get a WhatsApp confirmation." → alert success.

## Expected Outcomes

- One webhook call creates Calendar event + Sheet row + WhatsApp trigger.
- Caller hears a short confirmation, never JSON.

## Edge Cases & Fallback Logic

- Missing/invalid phone: ask once more with example format. Normalize spaces/dashes. Fail after 2 tries → offer WhatsApp-only follow-up.
- Vague time ("tomorrow morning"): propose concrete slot: "Would 10:30 AM tomorrow work?" Get explicit yes before proceeding.
- Past date / end ≤ start: "Got it — that time has passed / looks off. What date and time work best for you?" Re-collect.
- Caller correction mid-flow: "Got it — updating that." Fix, re-confirm full summary.
- Tool non-zero exit / timeout: retry max 3x with same idempotency payload → then `python implementation/alert_user.py waiting` → say: "Absolutely — let me have our team follow up with you directly to confirm."
- Duplicate booking suspicion (same name+phone+time): do not double-book; say "It looks like we may already have you down — let me have our team double-check and confirm by WhatsApp."
- Never speak a confirmation without `status=ok` from the tool.

## Version History

- v1 (2026-09-16): from Master Directive Phases 3–4.
