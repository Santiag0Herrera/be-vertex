"""Runs the reconciliation job in the background and remembers its outcome.

Reconciling can take minutes (one Interbanking request per account and date
range, split per day when the answer hits the result limit, with retries).
Running it inside the HTTP request meant a proxy or browser timeout could cut
the response while the job kept conciliating transactions, and the frontend
then reported that nothing had been conciliated. The job now runs as a
background task and the frontend polls its state until it has the real result.

State lives in the API process memory, like the in-process lock it replaces;
the job's PostgreSQL advisory lock still serializes runs across workers.
"""

import asyncio
import datetime
import logging
import uuid
from typing import Awaitable, Callable, Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
IDLE = "idle"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class ReconciliationRunService:
    def __init__(self, runner: Callable[..., Awaitable[dict]]):
        self._runner = runner
        self._runs: dict[int, dict] = {}
        self._task: Optional[asyncio.Task] = None

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, entity_id: int) -> dict:
        if self.is_running():
            raise HTTPException(
                status_code=409,
                detail="The reconciliation job is already running",
            )

        run = {
            "run_id": uuid.uuid4().hex,
            "state": RUNNING,
            "started_at": _now(),
            "finished_at": None,
            "result": None,
            "error": None,
        }
        self._runs[entity_id] = run
        self._task = asyncio.create_task(self._execute(entity_id, run))
        return dict(run)

    def get(self, entity_id: int) -> dict:
        run = self._runs.get(entity_id)
        if run is None:
            return {
                "run_id": None,
                "state": IDLE,
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
            }
        return dict(run)

    async def _execute(self, entity_id: int, run: dict) -> None:
        try:
            result = await self._runner(entity_id=entity_id)
            run["result"] = result
            run["state"] = COMPLETED
        except HTTPException as exc:
            run["error"] = {"status_code": exc.status_code, "detail": exc.detail}
            run["state"] = FAILED
        except Exception:
            logger.exception(
                "[ERROR] reconciliation_run_failed entity_id=%s run_id=%s",
                entity_id,
                run["run_id"],
            )
            run["error"] = {
                "status_code": 500,
                "detail": "The reconciliation job failed unexpectedly.",
            }
            run["state"] = FAILED
        finally:
            run["finished_at"] = _now()
