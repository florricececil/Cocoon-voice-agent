# Greeting & Intent Recognition — v1 (2026-09-16)

## Goal

Open the call warmly and classify intent into (A) FAQ, (B) Booking, or (C) Follow-up/WhatsApp in the fewest turns.

## Required Inputs

- `business_name` from `.env`
- Caller utterance (first 1–2 turns)

## Script (say exactly, 1–2 sentences)

1. Greeting: "Thanks for calling [Business Name]! How can I help you today?"
2. Listen. Backchannel naturally ("sure", "got it") while caller speaks. Do not interrupt.
3. Classify:
   - FAQ keywords (hours, price, location, services, policy) → `intent=FAQ` → go to `rules/faq_handling_v1.md`
   - Book/schedule/call/appointment/reschedule → `intent=BOOKING` → go to `rules/appointment_booking_v1.md`
   - Call me back / WhatsApp me / send info / follow-up → `intent=FOLLOWUP` → go to `rules/appointment_booking_v1.md` (follow-up path: collect name+phone, log note, no date required)
   - Unclear → ask once: "Got it — are you looking for a quick answer, or would you like to schedule a call with our team?"

## Scripts / Tools to Invoke

None in this phase. Only update `.tmp/call_state.json` (`intent`, `turn`, `updated_at`).

## Expected Outcomes

- `intent` set to `FAQ | BOOKING | FOLLOWUP`.
- Caller feels heard within 5 seconds of answering.

## Edge Cases & Fallback Logic

- Silence / ASR empty: "Are you still there? How can I help you today?" (max 2x, then `alert_user.py waiting`).
- Angry caller: stay calm, "Absolutely — I'm here to help. What's going on?" Do not mirror frustration.
- Multiple intents at once: handle FAQ first (≤2 sentences), then offer booking.
- Wrong business / spam: be polite, close, log note.

## Version History

- v1 (2026-09-16): from Master Directive Phase 1.
