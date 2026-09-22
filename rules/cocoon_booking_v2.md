# Cocoon Booking & Intake — v2 (2026-09-17)

## Goal
Collect tattoo intake, validate hours/policy, get explicit lock-in, fire one `CREATE_TATTOO_BOOKING` webhook (Sheets + Calendar + WhatsApp).

## Required Inputs
- `name` (required), `phone_number` (required, WhatsApp-capable), `email` (optional)
- `design_description` (required, short), `size_cm` → `size_category` (Flash/Small/Medium/Large), `ink_colors` (black/red only per policy)
- `is_house_call` (bool, default false), `start_time/end_time` ISO-8601 in operating hours, `notes`

## Script (one question per turn, 1–2 sentences)
1. Name: "Awesome! May I get your full name?"
2. Contact: "What is your best phone or WhatsApp number?"
3. Design/size/ink: "What design do you have in mind, roughly what size in centimeters will it be, and is it black or red ink?"
4. Location: "Will this session be at the studio, or are you requesting a house call?" If house call: "Gotcha — house calls carry an extra travel and setup fee."
5. Time: "What day and time work best for you?" Must be Mon–Fri 16:00–23:00 or Sat–Sun 08:00–23:00 Africa/Johannesburg. Outside → "Makes sense — we're open [hours]. Would [nearest valid slot] work instead?"
6. Confirmation (mandatory): "Perfect! I have [Name] for [Date/Time] for a [Size/Design] session. Should I lock this booking in?"
7. Only on explicit yes → run tool. No/correction → "Gotcha — updating that.", fix, re-confirm.

## Tool
`implementation/send_tattoo_booking.py` — args `--name --phone --design --size-cm/--size-category --ink --house-call/--studio --start [--end] [--email] [--notes]` or `--json-file`/stdin. Expected: `{"status":"ok",...}` exit 0.
Then: validate ok → persist `call_state.json` → speak "You're locked in for [Date/Time]. You'll get a WhatsApp confirmation shortly." → `alert_user.py success`.

Payload (never read aloud):
```json
{"action":"CREATE_TATTOO_BOOKING","studio_name":"The Cocoon","agent_name":"Wish","caller":{...},"tattoo_details":{"design_description":"...","size_category":"...","ink_colors":"...","is_house_call":false,"estimated_price_range":"..."},"booking_details":{...},"targets":{"google_calendar":true,"google_sheets":true,"whatsapp_message":true}}
```

## Fallbacks
- Bad phone: re-ask once with format hint. Vague time: propose concrete in-hours slot, get yes.
- Non-black/red ink: gently hold policy, offer black/red reinterpretation; tool flags `policy_warning` but still books consultation if caller agrees.
- Past date / end≤start / outside hours: re-collect, never book.
- Tool fail: same-payload retry 3x → `alert_user.py waiting` → "Definitely — let me have our team follow up directly to lock this in."
- Duplicates (same name+phone+time): don't double-book; hand to team via WhatsApp check.
- No confirmation spoken without `status=ok`.

## Version History
- v2 (2026-09-17): Cocoon intake + CREATE_TATTOO_BOOKING + hours enforcement. v1 booking retained as fallback.
