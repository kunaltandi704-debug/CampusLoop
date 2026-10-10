---
name: campusloop
description: Build, maintain, test, and safely demo the CampusLoop Flask and SQLite campus engagement application.
---

# CampusLoop project skill

## Project conventions

- Preserve the Flask application in `app.py`, the vanilla JavaScript client in `static/app.js`, shared styles in `static/styles.css`, and the SQLite schema initialized by `initialize_database()`.
- Keep student records private by filtering queries with the authenticated user's ID. Protect every admin operation with `@admin_required`.
- Perform token, order, refund, activity-participation, and contribution-approval writes inside a database transaction. Record every wallet change in `ledger`; never accept a client-supplied balance or token amount for a debit/credit.
- Treat the ledger as authoritative. Keep the legacy `users.balance` field synchronized only as a compatibility cache; balance reads must sum ledger entries. Compute rupee equivalents as tokens × ₹0.10; never store independently editable rupee prices.
- Use ledger idempotency keys or guarded status transitions for exactly-once mutations. Keep balances non-negative and show an explicit error when the operation cannot be completed.
- Keep demo/sample activities labeled as samples. Derive Upcoming/Ongoing/Completed from persisted start/end timestamps.
- Use `COLLEGE_TIMEZONE` for weekly attendance boundaries: Monday midnight through the next Monday midnight, local time. Attendance percentage and reward tier come only from persisted class sessions and roll calls for the student's enrolled sections. Do not issue rewards until the week has ended and every session is finalized.
- Keep attendance unique per student/session. Only admins or assigned teachers may record, finalize, or correct attendance; corrections need a reason and an audit row. Never let students edit attendance or percentages.
- Issue no more than one highest qualifying tier per student/week, atomically with its ledger entry. Corrections after issuance require the authorized adjustment workflow and an appended ledger/audit record; never alter original history.
- Validate uploaded image extensions, file signatures, request size, and owner/admin access. Store random server-generated filenames; never trust a supplied path.
- Update the directly related tests and README when changing application behavior.

## Mandatory AI model

- Generative AI must use only the exact model ID `gemma-4-26b-a4b-it` through the existing Google GenAI Python SDK integration in `app.py`.
- Read `GOOGLE_API_KEY` or `GEMINI_API_KEY` only from the server environment / `.env`. Never expose the API key in JavaScript, HTML, logs, or committed files.
- Do not add another model, fallback model, or AI path that invents balances, ledger rows, rewards, activities, or orders.
- Construct the smallest relevant verified context from SQLite for each authenticated student's question. Keep orders and other private records restricted to their owner.
- The assistant may explain/recommend but must never redeem tokens, approve contributions, or update orders. Backend routes remain authoritative.
- Return a clear error for missing credentials, empty responses, or API failures; log server-side provider failures without logging keys or private prompts.

## Security and configuration

- `.env` and SQLite database files are local-only and ignored by Git. Use `.env.example` for non-secret configuration names and documentation.
- Seeded demo credentials require explicit `CAMPUSLOOP_DEMO_MODE=1`; never enable that mode for a public deployment. Bootstrap a real admin with deployment secrets instead.
- Use password hashes, CSRF protection for API mutations, role checks, input validation, and parameterized SQLite queries.
- Keep token accounting and refund changes atomic. Do not modify `users.balance` from a client-facing route except through the ledger transaction helper.
- Do not commit uploads, credentials, student data, or local database contents.

## Testing

- Run `python -m unittest discover -s tests -v` after changes to transactions, ownership, uploads, or admin behavior.
- Add regression tests for token amount, resulting balance, ledger row/reason, duplicate requests, insufficient balance, and invalid state transitions.
- Test attendance thresholds at 69.99%, 70%, 79.99%, 80%, 89.99%, 90%, and 100%; also test finalization, duplicate processing, ownership, corrections, and adjustment idempotency.
- When changing the UI, check both student and admin surfaces, mobile-friendly navigation, empty states, and API failure messages.
- For assistant changes, verify the model ID remains `gemma-4-26b-a4b-it`, no private cross-student records enter context, and missing/unavailable API errors do not trigger a fallback.
