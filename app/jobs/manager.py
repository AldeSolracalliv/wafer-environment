from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import logging
import uuid

from app.core.database import Database


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Job:
    id: str
    description: str
    status: JobStatus
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    assigned_agent: str | None = None
    result: str | None = None
    error: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    def __init__(self, database: Database, logger: logging.Logger):
        self.database, self.logger = database, logger

    @staticmethod
    def _from_row(row) -> Job:
        return Job(row["id"], row["description"], JobStatus(row["status"]), row["created_at"], row["started_at"], row["completed_at"], row["assigned_agent"], row["result"], row["error"])

    def create_job(self, description: str, assigned_agent: str | None = None) -> Job:
        job = Job(str(uuid.uuid4()), description, JobStatus.PENDING, _now(), assigned_agent=assigned_agent)
        self.database.execute("INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (job.id, job.description, job.status.value, job.created_at, None, None, assigned_agent, None, None))
        self.logger.info("job.created id=%s", job.id)
        return job

    def get_job(self, job_id: str) -> Job | None:
        row = self.database.connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._from_row(row) if row else None

    def list_jobs(self) -> list[Job]:
        return [self._from_row(row) for row in self.database.connection.execute("SELECT * FROM jobs ORDER BY created_at")]

    def _transition(self, job_id: str, expected: JobStatus, status: JobStatus, **fields) -> Job:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(f"Unknown job: {job_id}")
        if job.status is not expected:
            raise ValueError(f"Cannot transition job from {job.status.value} to {status.value}")
        assignments = ["status = ?"]
        values = [status.value]
        for key, value in fields.items():
            assignments.append(f"{key} = ?")
            values.append(value)
        values.append(job_id)
        self.database.execute(f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?", tuple(values))
        updated = self.get_job(job_id)
        self.logger.info("job.%s id=%s", status.value.lower(), job_id)
        return updated

    def start_job(self, job_id: str) -> Job:
        return self._transition(job_id, JobStatus.PENDING, JobStatus.RUNNING, started_at=_now())

    def complete_job(self, job_id: str, result: str | None = None) -> Job:
        return self._transition(job_id, JobStatus.RUNNING, JobStatus.COMPLETED, completed_at=_now(), result=result)

    def fail_job(self, job_id: str, error: str) -> Job:
        return self._transition(job_id, JobStatus.RUNNING, JobStatus.FAILED, completed_at=_now(), error=error)

    def cancel_job(self, job_id: str) -> Job:
        return self._transition(job_id, JobStatus.PENDING, JobStatus.CANCELLED, completed_at=_now())
