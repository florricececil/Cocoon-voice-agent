# Cocoon Booking & Intake — v3 (2026-09-18)

> Supersedes `cocoon_booking_v2.md` for `book_tattoo_appointment`. v2 retained as fallback per versioning rule.

## Goal
Collect tattoo intake including placement, validate hours/policy, get explicit lock-in, fire one `book_tattoo_appointment` → `CREATE_TATTOO_BOOKING` webhook (Sheets + Calendar + WhatsApp).

Tool contract (`book_tattoo_appointment`):
- URL: `POST https://garnet-unsmooth-floral.ngrok-free.dev/webhook/booking`
- Required: `caller_name, caller_phone, placement, design_description, ink_colors, start_time (ISO-8601), size_category (Flash|Small|Medium|Large)`
- Implementation: `implementation/cocoon_voice_server.py` (`validate_booking`) + `implementation/send_tattoo_booking.py`

## Required Inputs
- `caller_name` (required), `caller_phone` (required, WhatsApp-capable), `caller_email` (optional, backward-compat)
- `design_description` (required, short), `placement` (required, e.g. Forearm, Bicep, Ankle)
- `size_category` (required enum Flash|Small|Medium|Large; `size_cm` accepted as backward-compat override) → price from KB
- `ink_colors` (required free-text; policy black/red only)
- `is_house_call` (bool, default false, backward-compat), `start_time/end_time` ISO-8601 in operating hours, `notes`/`call_summary`

## Script (one question per turn, 1–2 sentences)
1. Name: "Awesome! May I get your full name?"
2. Contact: "What is your best phone or WhatsApp number?"
3. Design/size/ink: "What design do you have in mind, roughly what size in centimeters will it be, and is it black or red ink?"
4. Placement: "Gotcha — where on the body should this go, like forearm, bicep, or ankle?"
5. Location: "Will this session be at the studio, or are you requesting a house call?" If house call: "Gotcha — house calls carry an extra travel and setup fee."
6. Time: "What day and time work best for you?" Must be Mon–Fri 16:00–23:00 or Sat–Sun 08:00–23:00 Africa/Johannesburg. Outside → "Makes sense — we're open [hours]. Would [nearest valid slot] work instead?"
7. Confirmation (mandatory, include placement + size): "Perfect! I have [Name] for [Date/Time] for a [Size] [Design] on the [Placement]. Should I lock this booking in?"
8. Only on explicit yes → run tool. No/correction → "Gotcha — updating that.", fix, re-confirm.

## Tool
`implementation/send_tattoo_booking.py` — args `--name --phone --design --placement --size-cm/--size-category --ink --house-call/--studio --start [--end] [--email] [--notes]` or `--json-file`/stdin. Expected: `{"status":"ok",...}` exit 0.
Server: `POST /webhook/booking` with `{"caller_name","caller_phone","placement","design_description","ink_colors","start_time","size_category"}` → validates → queues Integrately relay.
Then: validate ok → persist `call_state.json` (include `placement`) → speak "You're locked in for [Date/Time]. You'll get a WhatsApp confirmation shortly." → `alert_user.py success`.

Payload (never read aloud):
```json
{"action":"CREATE_TATTOO_BOOKING","studio_name":"The Cocoon","agent_name":"Wish","caller":{...},"tattoo_details":{"design_description":"...","placement":"Forearm","size_category":"Small","ink_colors":"...","is_house_call":false,"estimated_price_range":"..."},"booking_details":{...},"targets":{"google_calendar":true,"google_sheets":true,"whatsapp_message":true}}
```

## Fallbacks
- Missing placement: ask once — "Where on the body should I place this booking?" Never book without placement (tool returns 422).
- Bad phone: re-ask once with format hint. Vague time: propose concrete in-hours slot, get yes.
- Non-black/red ink: gently hold policy, offer black/red reinterpretation; tool flags `policy_warning` but still books consultation if caller agrees.
- Bad size_category (not Flash|Small|Medium|Large): re-ask with 4 options, one at a time.
- Past date / end≤start / outside hours: re-collect, never book.
- Tool fail: same-payload retry 3x → `alert_user.py waiting` → "Definitely — let me have our team follow up directly to lock this in."
- Duplicates (same name+phone+time): don't double-book; hand to team via WhatsApp check.
- No confirmation spoken without `status=ok`.

## Version History
- v3 (2026-09-18): add required `placement` to match `book_tattoo_appointment` contract (caller_name, caller_phone, placement, design_description, ink_colors, start_time, size_category). v2 retained as fallback.
- v2 (2026-09-17): Cocoon intake + CREATE_TATTOO_BOOKING + hours enforcement. v1 booking retained as fallback.
