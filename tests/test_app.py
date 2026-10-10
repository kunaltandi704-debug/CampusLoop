import io
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import os

import app as application


class CampusLoopAccountingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_database = application.DATABASE
        self.original_upload_dir = application.UPLOAD_DIR
        application.DATABASE = Path(self.tempdir.name) / "test-campusloop.db"
        application.UPLOAD_DIR = Path(self.tempdir.name) / "uploads"
        application.UPLOAD_DIR.mkdir()
        self.demo_mode = patch.dict(os.environ, {"CAMPUSLOOP_DEMO_MODE": "1", "CAMPUSLOOP_ADMIN_EMAIL": "", "CAMPUSLOOP_ADMIN_PASSWORD": ""})
        self.demo_mode.start()
        application.initialize_database()
        application.app.config.update(TESTING=True)
        self.client = application.app.test_client()
        connection = application.connect_db()
        self.student_id = connection.execute("SELECT id FROM users WHERE email='student@campusloop.demo'").fetchone()["id"]
        self.admin_id = connection.execute("SELECT id FROM users WHERE email='admin@campusloop.demo'").fetchone()["id"]
        connection.close()
        self.login_as(self.student_id)

    def tearDown(self):
        application.DATABASE = self.original_database
        application.UPLOAD_DIR = self.original_upload_dir
        self.demo_mode.stop()
        self.tempdir.cleanup()

    def login_as(self, user_id):
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
            session["csrf_token"] = "test-csrf-token"

    def balance(self, user_id=None):
        connection = application.connect_db()
        row = connection.execute(
            "SELECT balance FROM users WHERE id=?", (user_id or self.student_id,)
        ).fetchone()
        connection.close()
        return row["balance"]

    def add_student(self, name):
        connection = application.connect_db()
        cursor = connection.execute(
            "INSERT INTO users(name,email,password_hash,role,balance,created_at) VALUES(?,?,?,'student',0,?)",
            (name, f"{name.lower().replace(' ','.')}@example.test", "test-hash", application.utc_now()),
        )
        connection.close()
        return cursor.lastrowid

    def seed_attendance(self, week_start, held, present, student_ids=None, finalized=True):
        student_ids = student_ids or [self.student_id]
        connection = application.connect_db()
        connection.execute("BEGIN IMMEDIATE")
        course = connection.execute("INSERT INTO courses(name) VALUES('Attendance Test Course')").lastrowid
        section = connection.execute(
            "INSERT INTO course_sections(course_id,name) VALUES(?,'A')", (course,)
        ).lastrowid
        subject = connection.execute(
            "INSERT INTO subjects(section_id,name) VALUES(?,'Attendance Test Subject')", (section,)
        ).lastrowid
        class_id = connection.execute(
            "INSERT INTO scheduled_classes(section_id,subject_id,name) VALUES(?,?,'Attendance Test Class')",
            (section, subject),
        ).lastrowid
        for student_id in student_ids:
            connection.execute(
                "INSERT INTO student_enrollments(section_id,student_id,created_at) VALUES(?,?,?)",
                (section, student_id, application.utc_now()),
            )
        week_date = date.fromisoformat(week_start)
        local_start = datetime.combine(week_date, time(10), application.college_zone())
        session_ids = []
        for index in range(held):
            start = (local_start + timedelta(minutes=index)).astimezone(timezone.utc).isoformat()
            end = (local_start + timedelta(minutes=index + 50)).astimezone(timezone.utc).isoformat()
            session_id = connection.execute(
                "INSERT INTO class_sessions(class_id,starts_at,ends_at,finalized,created_by,created_at) VALUES(?,?,?,?,?,?)",
                (class_id, start, end, int(finalized), self.admin_id, application.utc_now()),
            ).lastrowid
            session_ids.append(session_id)
            for student_id in student_ids:
                status = "Present" if index < present else "Absent"
                connection.execute(
                    "INSERT INTO attendance_records(session_id,student_id,status,recorded_by,recorded_at) VALUES(?,?,?,?,?)",
                    (session_id, student_id, status, self.admin_id, application.utc_now()),
                )
        connection.commit()
        connection.close()
        return {"class_id": class_id, "section_id": section, "session_ids": session_ids}

    def previous_completed_week(self):
        today = datetime.now(application.college_zone()).date()
        monday = today - timedelta(days=today.weekday()) - timedelta(days=7)
        return monday.isoformat()

    def test_reward_redemption_debits_ledger_once(self):
        connection = application.connect_db()
        reward_id = connection.execute("SELECT id FROM rewards WHERE name='Demo smoothie'").fetchone()["id"]
        before_count = connection.execute("SELECT COUNT(*) FROM ledger WHERE user_id=?", (self.student_id,)).fetchone()[0]
        connection.close()

        response = self.client.post(
            f"/api/rewards/{reward_id}/redeem",
            json={"idempotency_key": "smoothie-once"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.balance(), 250)

        duplicate = self.client.post(
            f"/api/rewards/{reward_id}/redeem",
            json={"idempotency_key": "smoothie-once"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(duplicate.status_code, 409)
        connection = application.connect_db()
        after_count = connection.execute("SELECT COUNT(*) FROM ledger WHERE user_id=?", (self.student_id,)).fetchone()[0]
        entry = connection.execute(
            "SELECT amount,entry_type,reason FROM ledger WHERE user_id=? AND idempotency_key='smoothie-once'",
            (self.student_id,),
        ).fetchone()
        connection.close()
        self.assertEqual(after_count, before_count + 1)
        self.assertEqual((entry["amount"], entry["entry_type"]), (100, "debit"))
        self.assertIn("Demo smoothie", entry["reason"])

    def test_insufficient_balance_does_not_create_debit(self):
        connection = application.connect_db()
        connection.execute("BEGIN IMMEDIATE")
        application.ledger_change(
            connection, self.student_id, 340, "debit", "Test balance adjustment",
            "test_balance", "insufficient-balance-setup",
        )
        connection.commit()
        reward_id = connection.execute("SELECT id FROM rewards WHERE name='Demo smoothie'").fetchone()["id"]
        entries = connection.execute("SELECT COUNT(*) FROM ledger WHERE user_id=?", (self.student_id,)).fetchone()[0]
        connection.close()

        response = self.client.post(
            f"/api/rewards/{reward_id}/redeem",
            json={"idempotency_key": "too-expensive"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("Insufficient", response.get_json()["error"])
        self.assertEqual(self.balance(), 10)
        connection = application.connect_db()
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM ledger WHERE user_id=?", (self.student_id,)).fetchone()[0], entries)
        connection.close()

    def test_pending_order_cancellation_refunds_once(self):
        connection = application.connect_db()
        item_id = connection.execute("SELECT id FROM menu_items WHERE name='Masala chai'").fetchone()["id"]
        connection.close()
        placed = self.client.post(
            "/api/orders",
            json={"idempotency_key": "chai-order-1", "items": [{"item_id": item_id, "quantity": 2}]},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(placed.status_code, 201)
        order_id = placed.get_json()["id"]
        self.assertEqual(self.balance(), 260)

        cancelled = self.client.post(
            f"/api/orders/{order_id}/cancel", headers={"X-CSRF-Token": "test-csrf-token"}
        )
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(self.balance(), 350)
        again = self.client.post(
            f"/api/orders/{order_id}/cancel", headers={"X-CSRF-Token": "test-csrf-token"}
        )
        self.assertEqual(again.status_code, 409)
        self.assertEqual(self.balance(), 350)
        connection = application.connect_db()
        refunds = connection.execute(
            "SELECT COUNT(*) FROM ledger WHERE source_type='order_refund' AND source_id=?", (order_id,)
        ).fetchone()[0]
        connection.close()
        self.assertEqual(refunds, 1)

    def test_students_only_see_their_own_orders(self):
        connection = application.connect_db()
        other_id = connection.execute(
            "INSERT INTO users(name,email,password_hash,role,balance,created_at) VALUES('Other Student','other@example.test','x','student',0,?)",
            (application.utc_now(),),
        ).lastrowid
        item_id = connection.execute("SELECT id FROM menu_items LIMIT 1").fetchone()["id"]
        connection.execute(
            "INSERT INTO orders(id,user_id,token_cost,status,idempotency_key,created_at) VALUES('private-order',? ,1,'Pending','private','2026-01-01T00:00:00+00:00')",
            (other_id,),
        )
        connection.execute(
            "INSERT INTO order_items(order_id,item_name,quantity,unit_token_price) VALUES('private-order','Private item',1,1)"
        )
        connection.close()
        response = self.client.get("/api/orders")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("private-order", str(response.get_json()))

    def test_activity_reward_is_credited_once_after_admin_approval(self):
        connection = application.connect_db()
        activity_id = connection.execute("SELECT id FROM activities LIMIT 1").fetchone()["id"]
        reward = connection.execute("SELECT reward_tokens FROM activities WHERE id=?", (activity_id,)).fetchone()[0]
        connection.close()
        request_response = self.client.post(
            f"/api/activities/{activity_id}/participate",
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(request_response.status_code, 201)
        self.login_as(self.admin_id)
        connection = application.connect_db()
        participation_id = connection.execute("SELECT id FROM activity_participations WHERE user_id=?", (self.student_id,)).fetchone()["id"]
        connection.close()

        approval = self.client.patch(
            f"/api/admin/participations/{participation_id}",
            json={"status": "Approved"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(approval.status_code, 200)
        self.assertEqual(self.balance(), 350 + reward)
        duplicate = self.client.patch(
            f"/api/admin/participations/{participation_id}",
            json={"status": "Approved"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(self.balance(), 350 + reward)

    def test_artwork_award_is_credited_once_only_after_approval(self):
        submitted = self.client.post(
            "/api/submissions",
            data={
                "title": "Spring Fest",
                "description": "A bright event poster concept.",
                "category": "Event Poster",
                "image": (io.BytesIO(b"\x89PNG\r\n\x1a\nDemo image bytes"), "poster.png"),
            },
            headers={"X-CSRF-Token": "test-csrf-token"},
            content_type="multipart/form-data",
        )
        self.assertEqual(submitted.status_code, 201)
        submission_id = submitted.get_json()["id"]
        self.assertEqual(self.balance(), 350)
        self.login_as(self.admin_id)
        connection = application.connect_db()
        connection.execute("UPDATE settings SET value='65' WHERE key='contribution_reward'")
        connection.close()

        approval = self.client.patch(
            f"/api/admin/submissions/{submission_id}",
            json={"status": "Approved"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(approval.status_code, 200)
        self.assertEqual(approval.get_json()["reward_tokens"], 65)
        self.assertEqual(self.balance(), 415)
        duplicate = self.client.patch(
            f"/api/admin/submissions/{submission_id}",
            json={"status": "Approved"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(self.balance(), 415)

    def test_non_admin_cannot_review_submissions_or_change_prices(self):
        response = self.client.patch(
            "/api/admin/settings/contribution-reward",
            json={"reward_tokens": 1000},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(response.status_code, 403)

    def test_submission_upload_rejects_mismatched_image_contents(self):
        response = self.client.post(
            "/api/submissions",
            data={
                "title": "Not an image",
                "description": "A bad upload",
                "category": "Event Poster",
                "image": (io.BytesIO(b"not a png"), "poster.png"),
            },
            headers={"X-CSRF-Token": "test-csrf-token"},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("contents", response.get_json()["error"])

    def test_assistant_reports_missing_key_without_fallback(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "", "GEMINI_API_KEY": ""}):
            response = self.client.post(
                "/api/assistant",
                json={"message": "What rewards can I afford?"},
                headers={"X-CSRF-Token": "test-csrf-token"},
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn("GOOGLE_API_KEY", response.get_json()["error"])
        self.assertEqual(application.MODEL_NAME, "gemma-4-26b-a4b-it")

    def test_demo_credentials_are_not_seeded_by_default(self):
        original_database = application.DATABASE
        application.DATABASE = Path(self.tempdir.name) / "no-demo-users.db"
        try:
            with patch.dict(os.environ, {"CAMPUSLOOP_DEMO_MODE": "0", "CAMPUSLOOP_ADMIN_EMAIL": "", "CAMPUSLOOP_ADMIN_PASSWORD": ""}):
                application.initialize_database()
            connection = application.connect_db()
            users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            demos = connection.execute(
                "SELECT COUNT(*) FROM users WHERE email LIKE '%@campusloop.demo'"
            ).fetchone()[0]
            connection.close()
            self.assertEqual(users, 0)
            self.assertEqual(demos, 0)
        finally:
            application.DATABASE = original_database

    def test_attendance_tier_thresholds(self):
        expected = [
            (69.99, 0),
            (70, 200),
            (79.99, 200),
            (80, 300),
            (89.99, 300),
            (90, 500),
            (100, 500),
        ]
        for percentage, tokens in expected:
            with self.subTest(percentage=percentage):
                self.assertEqual(application.attendance_reward_tier(percentage), tokens)
                self.assertEqual(application.reward_value_paise(tokens), tokens * 10)

    def test_weekly_bonus_uses_finalized_database_attendance_once(self):
        week_start = self.previous_completed_week()
        self.seed_attendance(week_start, held=10, present=8)
        self.login_as(self.admin_id)
        request_headers = {"X-CSRF-Token": "test-csrf-token"}
        first = self.client.post(
            "/api/admin/attendance/process-week",
            json={"week_start": week_start},
            headers=request_headers,
        )
        self.assertEqual(first.status_code, 200, first.get_json())
        self.assertEqual(first.get_json()["issued"], [
            {"student_id": self.student_id, "percentage": 80.0, "reward_tokens": 300}
        ])
        self.assertEqual(self.balance(), 650)

        retry = self.client.post(
            "/api/admin/attendance/process-week",
            json={"week_start": week_start},
            headers=request_headers,
        )
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.get_json()["issued"], [])
        self.assertEqual(retry.get_json()["skipped_student_ids"], [self.student_id])
        self.assertEqual(self.balance(), 650)
        connection = application.connect_db()
        bonus_rows = connection.execute(
            "SELECT id,amount,reason,source_type,source_id,created_at FROM ledger WHERE user_id=? AND source_type='weekly_attendance_bonus'",
            (self.student_id,),
        ).fetchall()
        self.assertEqual(len(bonus_rows), 1)
        self.assertEqual(bonus_rows[0]["amount"], 300)
        self.assertEqual(bonus_rows[0]["source_id"], f"{self.student_id}:{week_start}")
        self.assertIn("Weekly Attendance Bonus — 80% — +300 tokens", bonus_rows[0]["reason"])
        self.assertTrue(bonus_rows[0]["created_at"])
        connection.close()

    def test_unfinalized_week_is_not_eligible_for_issue(self):
        week_start = self.previous_completed_week()
        self.seed_attendance(week_start, held=4, present=4, finalized=False)
        self.login_as(self.admin_id)
        response = self.client.post(
            "/api/admin/attendance/process-week",
            json={"week_start": week_start},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["issued"], [])
        self.assertEqual(response.get_json()["skipped_student_ids"], [self.student_id])
        self.assertEqual(self.balance(), 350)

    def test_student_attendance_is_private_and_cannot_be_edited(self):
        other_id = self.add_student("Student B")
        week_start = self.previous_completed_week()
        seeded = self.seed_attendance(week_start, held=2, present=1, student_ids=[self.student_id, other_id])
        attendance_id = self.client.get("/api/attendance/me").get_json()["class_records"][0]["attendance_id"]
        self.assertNotEqual(attendance_id, None)
        self.assertNotIn("Student B", str(self.client.get("/api/attendance/me").get_json()))
        forbidden = self.client.patch(
            f"/api/teacher/attendance/{attendance_id}",
            json={"status": "Absent", "reason": "Student self-edit attempt"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(forbidden.status_code, 403)
        unsupported = self.client.post(
            "/api/ledger",
            json={"entry_type": "credit", "amount": 50000},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(unsupported.status_code, 405)
        self.assertEqual(self.balance(), 350)
        self.login_as(other_id)
        records = self.client.get("/api/attendance/me").get_json()["class_records"]
        self.assertTrue(records)
        self.assertTrue(all(record["attendance_id"] != attendance_id for record in records))

    def test_authorized_attendance_correction_is_audited_and_reward_adjustment_is_explicit(self):
        week_start = self.previous_completed_week()
        seeded = self.seed_attendance(week_start, held=10, present=8)
        self.login_as(self.admin_id)
        headers = {"X-CSRF-Token": "test-csrf-token"}
        issued = self.client.post(
            "/api/admin/attendance/process-week",
            json={"week_start": week_start},
            headers=headers,
        )
        self.assertEqual(issued.status_code, 200)
        connection = application.connect_db()
        attendance_id = connection.execute(
            "SELECT id FROM attendance_records WHERE session_id=? AND student_id=? AND status='Present' "
            "ORDER BY id LIMIT 1",
            (seeded["session_ids"][0], self.student_id),
        ).fetchone()["id"]
        connection.close()
        corrected = self.client.patch(
            f"/api/teacher/attendance/{attendance_id}",
            json={"status": "Absent", "reason": "Verified instructor correction"},
            headers=headers,
        )
        self.assertEqual(corrected.status_code, 200)
        self.assertTrue(corrected.get_json()["audit_logged"])
        adjusted = self.client.post(
            f"/api/admin/attendance/rewards/{self.student_id}/{week_start}/adjust",
            json={"reason": "Corrected attendance record", "idempotency_key": "correction-1"},
            headers=headers,
        )
        self.assertEqual(adjusted.status_code, 200, adjusted.get_json())
        self.assertEqual(adjusted.get_json()["delta_tokens"], -100)
        self.assertEqual(self.balance(), 550)
        retry = self.client.post(
            f"/api/admin/attendance/rewards/{self.student_id}/{week_start}/adjust",
            json={"reason": "Corrected attendance record", "idempotency_key": "correction-1"},
            headers=headers,
        )
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.get_json()["duplicate"])
        self.assertEqual(self.balance(), 550)
        connection = application.connect_db()
        self.assertEqual(connection.execute(
            "SELECT COUNT(*) FROM attendance_corrections WHERE attendance_id=? AND reason='Verified instructor correction'",
            (attendance_id,),
        ).fetchone()[0], 1)
        self.assertEqual(connection.execute(
            "SELECT COUNT(*) FROM attendance_reward_adjustments WHERE student_id=? AND week_start=?",
            (self.student_id, week_start),
        ).fetchone()[0], 1)
        connection.close()

    def test_teacher_requires_assignment_and_finalization_requires_every_student(self):
        other_id = self.add_student("Teacher Candidate")
        seeded = self.seed_attendance(self.previous_completed_week(), held=1, present=1, student_ids=[self.student_id])
        self.login_as(other_id)
        denied = self.client.post(
            f"/api/teacher/sessions/{seeded['session_ids'][0]}/finalize",
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(denied.status_code, 403)
        self.login_as(self.admin_id)
        enrollment = self.client.post(
            "/api/admin/enrollments",
            json={"section_id": seeded["section_id"], "student_id": other_id},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(enrollment.status_code, 201)
        assignment = self.client.post(
            "/api/admin/teacher-assignments",
            json={"class_id": seeded["class_id"], "teacher_id": other_id},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(assignment.status_code, 201)
        connection = application.connect_db()
        connection.execute("UPDATE class_sessions SET finalized=0 WHERE id=?", (seeded["session_ids"][0],))
        connection.close()
        incomplete = self.client.post(
            f"/api/teacher/sessions/{seeded['session_ids'][0]}/finalize",
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(incomplete.status_code, 400, incomplete.get_json())
        self.assertIn("every enrolled student", incomplete.get_json()["error"])
        self.login_as(other_id)
        recorded = self.client.post(
            f"/api/teacher/sessions/{seeded['session_ids'][0]}/attendance",
            json={"records": [{"student_id": other_id, "status": "Absent"}]},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(recorded.status_code, 200)
        duplicate = self.client.post(
            f"/api/teacher/sessions/{seeded['session_ids'][0]}/attendance",
            json={"records": [{"student_id": other_id, "status": "Absent"}]},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(duplicate.status_code, 409)
        finalized = self.client.post(
            f"/api/teacher/sessions/{seeded['session_ids'][0]}/finalize",
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(finalized.status_code, 200)

    def test_migration_preserves_users_and_reconciles_legacy_cached_balance(self):
        legacy_path = Path(self.tempdir.name) / "legacy.db"
        connection = sqlite3.connect(legacy_path)
        connection.executescript("""
            CREATE TABLE users(id INTEGER PRIMARY KEY,name TEXT NOT NULL,email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,role TEXT NOT NULL,balance INTEGER NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE ledger(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,entry_type TEXT NOT NULL,
                amount INTEGER NOT NULL,reason TEXT NOT NULL,source_type TEXT NOT NULL,source_id TEXT NOT NULL,
                idempotency_key TEXT,created_at TEXT NOT NULL);
            CREATE TABLE rewards(id INTEGER PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL,
                token_price INTEGER NOT NULL,rupee_value INTEGER NOT NULL,active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            INSERT INTO users VALUES(42,'Legacy Student','legacy@example.test','hash','student',500,'2025-01-01T00:00:00+00:00');
            INSERT INTO ledger VALUES(7,42,'credit',120,'Legacy credit','legacy','credit-7',NULL,'2025-01-02T00:00:00+00:00');
            INSERT INTO rewards VALUES(77,'Legacy smoothie','Kept during migration',100,999,1);
        """)
        connection.close()
        original_database = application.DATABASE
        application.DATABASE = legacy_path
        try:
            with patch.dict(os.environ, {"CAMPUSLOOP_DEMO_MODE": "0", "CAMPUSLOOP_ADMIN_EMAIL": "", "CAMPUSLOOP_ADMIN_PASSWORD": ""}):
                application.initialize_database()
            migrated = application.connect_db()
            user = migrated.execute("SELECT id,name,balance FROM users WHERE id=42").fetchone()
            ledger_balance = application.balance_from_ledger(migrated, 42)
            reconciliation = migrated.execute(
                "SELECT amount,entry_type,reason,created_at FROM ledger "
                "WHERE source_type='legacy_balance_reconciliation' AND source_id='legacy-balance-user-42'"
            ).fetchone()
            reward = migrated.execute("SELECT id,name,token_price FROM rewards WHERE id=77").fetchone()
            columns = {row["name"] for row in migrated.execute("PRAGMA table_info(rewards)")}
            migrated.close()
            self.assertEqual((user["name"], user["balance"], ledger_balance), ("Legacy Student", 500, 500))
            self.assertEqual((reconciliation["amount"], reconciliation["entry_type"]), (380, "credit"))
            self.assertTrue(reconciliation["created_at"])
            self.assertEqual((reward["id"], reward["token_price"]), (77, 100))
            self.assertNotIn("rupee_value", columns)
        finally:
            application.DATABASE = original_database

    def test_dashboard_rewards_and_menu_share_fixed_conversion(self):
        dashboard_response = self.client.get("/api/dashboard").get_json()
        self.assertEqual(dashboard_response["user"]["balance"], 350)
        self.assertEqual(dashboard_response["balance_value_paise"], 3500)
        rewards = self.client.get("/api/rewards").get_json()
        smoothie = next(item for item in rewards if item["name"] == "Demo smoothie")
        self.assertEqual((smoothie["token_price"], smoothie["reward_value_paise"]), (100, 1000))
        menu = self.client.get("/api/menu").get_json()
        chai = next(item for item in menu if item["name"] == "Masala chai")
        self.assertEqual(chai["token_value_paise"], chai["token_price"] * 10)


if __name__ == "__main__":
    unittest.main()
