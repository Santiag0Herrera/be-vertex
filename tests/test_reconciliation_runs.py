import asyncio

import pytest
from fastapi import HTTPException

from app.services.ReconciliationRunService import ReconciliationRunService


def test_run_reports_real_counts_once_the_background_job_finishes():
    release = asyncio.Event()
    job_result = {"checked": 13, "conciliated": 13, "still_pending": 0}

    async def runner(entity_id):
        await release.wait()
        return job_result

    async def scenario():
        service = ReconciliationRunService(runner)
        started = service.start(entity_id=7)

        assert started["state"] == "running"
        assert started["result"] is None
        assert service.get(7)["state"] == "running"

        release.set()
        await service._task

        run = service.get(7)
        assert run["run_id"] == started["run_id"]
        assert run["state"] == "completed"
        assert run["result"]["conciliated"] == 13
        assert run["finished_at"] is not None

    asyncio.run(scenario())


def test_second_start_while_running_is_rejected():
    release = asyncio.Event()

    async def runner(entity_id):
        await release.wait()
        return {}

    async def scenario():
        service = ReconciliationRunService(runner)
        service.start(entity_id=1)
        with pytest.raises(HTTPException) as exc_info:
            service.start(entity_id=2)
        assert exc_info.value.status_code == 409
        release.set()
        await service._task
        service.start(entity_id=2)
        await service._task

    asyncio.run(scenario())


def test_job_errors_are_kept_as_failed_runs():
    async def http_failure(entity_id):
        raise HTTPException(status_code=422, detail="No Interbanking account")

    async def crash(entity_id):
        raise RuntimeError("boom")

    async def scenario():
        service = ReconciliationRunService(http_failure)
        service.start(entity_id=1)
        await service._task
        run = service.get(1)
        assert run["state"] == "failed"
        assert run["error"] == {"status_code": 422, "detail": "No Interbanking account"}

        service = ReconciliationRunService(crash)
        service.start(entity_id=1)
        await service._task
        assert service.get(1)["error"]["status_code"] == 500

    asyncio.run(scenario())


def test_entities_without_runs_are_idle():
    service = ReconciliationRunService(lambda entity_id: None)
    assert service.get(99)["state"] == "idle"
