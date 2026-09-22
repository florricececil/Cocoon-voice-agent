# FAQ Handling — v1 (2026-09-16)

## Goal

Answer routine business questions directly from the Business Knowledge Base, then offer a booking.

## Required Inputs

- Caller question
- Business Knowledge Base entry (if no KB file yet, say so honestly — never invent hours/prices/policies)

> TODO owner: add `rules/business_kb_v1.md` with real hours, location, services, pricing. Until then Brain must use fallback phrasing below.

## Script

1. Answer in ≤2 sentences, conversational. No preamble dumps.
2. Follow-up (always): "Does that answer your question, or would you like to schedule a quick call with our team?"
3. If caller says yes to call → set `intent=BOOKING`, go to `rules/appointment_booking_v1.md`.
4. If resolved → close warmly: "Perfect — thanks for calling [Business Name]!" Then `alert_user.py success`.

## Scripts / Tools to Invoke

None for answering. Only `alert_user.py success` on clean FAQ resolution (for post-call summary logging).

## Expected Outcomes

- Caller gets a short correct answer + clear next step.
- No hallucinated facts. No booking created from FAQ alone.

## Edge Cases & Fallback Logic

- Missing KB answer: "Sure — I don't want to guess on that, but I can have our team confirm by WhatsApp or a quick call. Which works best for you?"
- Caller correction: "Got it — thanks for clarifying." Re-answer once.
- Out-of-scope / legal / medical / pricing guarantees: do not speculate. Offer follow-up path.
- Repeated FAQ loop (>2 rounds): offer human handover via `alert_user.py waiting`.

## Version History

- v1 (2026-09-16): from Master Directive Phase 2.
