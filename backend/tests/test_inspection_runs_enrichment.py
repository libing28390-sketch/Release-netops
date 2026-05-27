import uuid
from datetime import datetime
from database import get_db_connection
from services.inspection_service import get_inspection_runs, get_inspection_run_detail

def test_get_inspection_runs_resolves_schedule_and_job_names(isolated_db):
    conn = get_db_connection()
    try:
        # 1. Test case: inspection runs linked to inspection_schedules
        schedule_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO inspection_schedules (id, name, cron_expr, scope_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (schedule_id, "每日例行巡检", "0 0 * * *", "all", "2026-05-27T00:00:00", "2026-05-27T00:00:00")
        )

        run_id_1 = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO inspection_runs (id, schedule_id, trigger_type, scope_type, started_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id_1, schedule_id, "scheduled", "all", "2026-05-27T10:00:00", "scheduler")
        )

        # 2. Test case: inspection runs linked to scheduled_jobs (created_by = 'scheduler:{job_id}')
        job_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO scheduled_jobs (id, name, job_type, action_type, device_scope, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, "思科设备日常巡检", "cron", "inspection", "all", "2026-05-27T00:00:00", "2026-05-27T00:00:00")
        )

        run_id_2 = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO inspection_runs (id, schedule_id, trigger_type, scope_type, started_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id_2, None, "scheduled", "all", "2026-05-27T11:00:00", f"scheduler:{job_id}")
        )

        # 3. Test case: inspection run with no schedule or job (manual run)
        run_id_3 = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO inspection_runs (id, schedule_id, trigger_type, scope_type, started_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id_3, None, "manual", "all", "2026-05-27T12:00:00", "admin")
        )

        conn.commit()
    finally:
        conn.close()

    # Call get_inspection_runs API
    result = get_inspection_runs(limit=10, offset=0)
    items = {item["id"]: item for item in result["items"]}

    # Verify schedule_name/name resolution for inspection_schedules
    assert run_id_1 in items
    assert items[run_id_1]["schedule_name"] == "每日例行巡检"
    assert items[run_id_1]["name"] == "每日例行巡检"

    # Verify schedule_name/name resolution for scheduled_jobs
    assert run_id_2 in items
    assert items[run_id_2]["schedule_name"] == "思科设备日常巡检"
    assert items[run_id_2]["name"] == "思科设备日常巡检"

    # Verify manual run does not have schedule_name or name resolved (should be missing or None)
    assert run_id_3 in items
    assert "schedule_name" not in items[run_id_3]
    assert "name" not in items[run_id_3]

    # Verify get_inspection_run_detail resolves the names correctly as well
    detail_1 = get_inspection_run_detail(run_id_1)
    assert detail_1 is not None
    assert detail_1["schedule_name"] == "每日例行巡检"
    assert detail_1["name"] == "每日例行巡检"

    detail_2 = get_inspection_run_detail(run_id_2)
    assert detail_2 is not None
    assert detail_2["schedule_name"] == "思科设备日常巡检"
    assert detail_2["name"] == "思科设备日常巡检"

    detail_3 = get_inspection_run_detail(run_id_3)
    assert detail_3 is not None
    assert "schedule_name" not in detail_3
    assert "name" not in detail_3
