# Rule Template (copy per workflow, never delete old versions — version as v1, v2)

> Write each Rule as if training a capable human receptionist who has never operated this front desk before.

## Goal

What does correct handling look like? (e.g. book appointment, route call, log intake)

## Required Inputs

- Caller details:
- Intent / context:
- Slots to collect before acting:

## Scripts / Tools to Invoke

| Step | Tool (`implementation/`) | Inputs | Expected Output |
| ---- | ------------------------ | ------ | --------------- |
| 1 | | | |
| 2 | | | |

Brain must: read this Rule → validate caller inputs → run tool → validate JSON output → speak result → persist to `.tmp/call_state.json`.

## Expected Outcomes

- Success looks like:
- Transfer / booked slot / logged note:

## Edge Cases & Fallback Logic

- Missing info →
- Tool failure (retry max 3x, then `python implementation/alert_user.py waiting`) →
- Angry caller / unreachable line / VIP →

## Version History

- v1 (YYYY-MM-DD): initial version
