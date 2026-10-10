# CampusLoop

**Make campus count.** CampusLoop is a hackathon-ready campus rewards and engagement app where students participate in campus activities, share event and canteen artwork, earn campus tokens, and spend them on refreshments.

## The campus problem

Campus opportunities, student creativity, and everyday canteen visits often live in separate places. Students can miss events, creative contributions are difficult to recognize consistently, and there is no transparent link between participation and a small everyday reward.

## The solution

CampusLoop connects an admin-managed activity calendar, reviewable student contributions, a transparent token ledger, canteen rewards and orders, and a private, verified-data assistant in one responsive application. It is a demo foundation: sample activities are explicitly labeled as examples, not verified events from a real college.

## Features

- Student registration and login, personalized dashboard, recent activity, and full token ledger.
- Atomic token credits/debits, non-negative balances, idempotent redemption/order requests, and admin-configurable reward/menu prices.
- A demo smoothie reward priced at **100 tokens** with **₹10 reward value**. Conversion reference: **100 tokens = ₹10 reward value**; reward prices are configured independently by an admin.
- One authoritative integer-token ledger for credits, debits, refunds, poster rewards, and weekly attendance bonuses. Rupee values derive from tokens at **₹0.10 per token**; they are not independently editable or stored as another wallet unit. A startup migration reconciles legacy cached balances into one-time ledger entries while preserving users and token prices.
- Canteen cart, persisted order lines and timestamps, student order history, staff status transitions (Pending → Preparing → Ready → Completed), and one-time refunds for eligible Pending cancellations.
- Admin-managed workshops, competitions, fests, volunteering, and other activities; date-derived Upcoming/Ongoing/Completed states; search, category filters, list and month calendar views, and edit/delete controls.
- Student participation requests, admin review, and one-time credit of an activity's configured token reward.
- Course, section, subject, student enrollment, assigned teacher, scheduled class session, and Present/Absent records with duplicate protection. Teachers can record/finalize roll calls; authorized corrections keep an auditable reason.
- Weekly attendance uses Monday 00:00 through next Monday 00:00 in `COLLEGE_TIMEZONE` (default `Asia/Kolkata`). Percentages use a student's enrolled and recorded class sessions. Only completed weeks with every session finalized can be processed: below 70% = 0; 70–<80% = 200; 80–<90% = 300; 90–100% = 500 tokens. One highest tier per student/week. Later attendance corrections require a separate admin adjustment; original ledger rows are never rewritten.
- Student attendance dashboard/history and teacher/admin attendance tools for setup, entry, eligibility, issuing, and adjustments.
- Poster/banner/canteen artwork uploads with extension and file-signature checks, 5 MB request limit, random filenames, private student/admin image access, review workflow, and exactly-once approval rewards.
- A responsive Gemma 4 assistant that receives only the current student's relevant verified records. It cannot mutate app state. There is no model fallback.
- Student and admin demo accounts, seeded canteen data, and clearly marked sample activities.

## AI model and data boundaries

Generative AI calls use **only `gemma-4-26b-a4b-it`** through the Google GenAI SDK and the server-side `GOOGLE_API_KEY` setting. No API key is sent to the browser. A missing key or unavailable API returns an explicit error; CampusLoop does not switch to another model.

The backend builds question-specific context: verified balance, reward prices, and (when relevant) the student's transactions; upcoming/ongoing activity rows; or only that signed-in student's orders. The model is instructed not to invent facts or perform account actions. Order history and account state always come from SQLite, never from generated chat text. As with any generative system, model output should be treated as assistance, not as an authorization or financial record.

## Architecture

- **Web:** Flask-rendered app shell with responsive HTML/CSS and a small browser JavaScript client.
- **Application/API:** Flask routes for authentication, student actions, admin operations, and the assistant.
- **Persistence:** SQLite with foreign keys, a normalized order/item model, contribution and participation review records, and a transaction ledger. Financially sensitive workflows use `BEGIN IMMEDIATE` and commit/rollback boundaries.
- **Attendance:** `COLLEGE_TIMEZONE` defines weekly boundaries. Session roll calls are unique per student/session; finalization requires a mark for every enrolled student. Weekly reward records and ledger credits commit atomically with a unique student/week constraint.
- **Identity/security:** Werkzeug password hashes, role checks on admin endpoints, session cookies (HTTP-only, SameSite=Lax), CSRF token checks on mutations, ownership filters for private records, and server-side file validation.
- **AI:** Google GenAI Python SDK using the fixed model ID `gemma-4-26b-a4b-it`.

## Requirements

- Windows 10/11 and Python 3.10+ (tested with Python 3.12).
- A Google GenAI API key for the chat feature. Other application features run without a key.
- Network access to install Python packages; chat requires access to the configured Google GenAI API.

## Setup on Windows (PowerShell)

From the project folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env`: set `FLASK_SECRET_KEY` to a long random value, set `GOOGLE_API_KEY` to your own Google GenAI API key, and confirm `COLLEGE_TIMEZONE` (default `Asia/Kolkata`). Generate a secret if needed:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Put that output in `.env`; never paste API keys into source files or commit `.env`.

For a **local hackathon demo only**, change `CAMPUSLOOP_DEMO_MODE=0` to `CAMPUSLOOP_DEMO_MODE=1` before the first run to seed the documented demo accounts. Do not enable demo mode on a public deployment: the demo passwords are intentionally known. For a non-demo install, leave demo mode off and set both `CAMPUSLOOP_ADMIN_EMAIL` and a unique `CAMPUSLOOP_ADMIN_PASSWORD` (12+ characters) to bootstrap the first admin. If no bootstrap admin is configured, students can still register, but admin operations remain unavailable until an admin account is provisioned.

Start the application:

```powershell
python app.py
```

Open <http://127.0.0.1:5000>. The SQLite database is created as `campusloop.db` on first run. Uploads are stored in `static\uploads\` and ignored by Git. Set `COOKIE_SECURE=1` only when deployed behind HTTPS. For a real deployment, use a production WSGI server, HTTPS, a durable database/upload service, managed secrets, backups, and institution-approved identity and canteen processes.

## Demo walkthrough

1. Sign in as `student@campusloop.demo` with password `CampusLoop123!` (seeded starting balance: 350 tokens), or register a new student.
2. On Overview, verify the wallet and the **100 tokens = ₹10** base conversion.
3. Open Rewards & menu. Redeem the Demo smoothie for 100 tokens; confirm the new balance and ledger entry. Try an order such as two masala chai, then inspect My orders.
4. In a second browser/private window, sign in as `admin@campusloop.demo` with password `CampusLoop123!`. In Admin studio, move a Pending order to Preparing → Ready → Completed. For a refund demo, place a separate Pending order and cancel it as the student (or cancel it from the admin screen); verify the refund appears once.
5. In Attendance admin, create a course/section/subject/class, enroll a student, assign a teacher account, and schedule class sessions (times use `COLLEGE_TIMEZONE`). For the demo, the assigned teacher account may be a registered student login; assignment—not the student's own attendance role—authorizes the teacher desk.
6. Sign in using the assigned teacher account, open Teacher desk, mark every enrolled student Present/Absent, save, and finalize. Students cannot mark or edit attendance, including their own. Corrections require a reason and are audited.
7. In Attendance admin, choose a completed Monday-start week, review eligibility, and process it once. Students can see verified percentages, class records, and weekly reward history. After a correction, an admin can explicitly adjust the already-issued reward.
8. Back as student, browse Activities in list and month views. Submit a participation request. As admin, approve it and check the student's token ledger.
9. Submit a small PNG/JPG/WebP event poster or canteen banner as the student. As admin, set the contribution award and approve the submission. The student sees the award and review status.
10. As admin, add/edit an activity and update a reward or menu price. Confirm the student view reflects the new values.
11. Configure `GOOGLE_API_KEY`, open Gemma assistant as the student, and ask about affordable rewards, attendance tiers, upcoming activities, or the latest order. Without a key the UI shows an explicit setup/unavailable message; no other model is used.

Demo credentials are intentionally public and only seeded after explicitly enabling local demo mode. Never enable demo mode or use its credentials on a public deployment.

## Tests

Run the focused accounting and workflow suite:

```powershell
python -m unittest discover -s tests -v
```

The tests cover redemption and insufficient-balance accounting, refunds/idempotency, private orders and attendance, approval rewards, legacy balance migration, fixed conversion, every attendance tier boundary, finalized-week/retry requirements, attendance corrections, reward adjustments, role checks, and uploads.

## Hackathon deliverables

- `skills/campusloop/SKILL.md`: project-specific implementation, AI model, safety, and testing guidance.
- `presentation/CampusLoop_Presentation.pptx`: editable pitch/demo slides covering the problem, solution, journey, wallet, creative rewards, calendar, Gemma 4 architecture, demo, impact, and future scope.

## License

MIT. See [LICENSE](LICENSE).
