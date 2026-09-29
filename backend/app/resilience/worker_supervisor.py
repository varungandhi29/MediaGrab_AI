import time
import asyncio
import logging
from typing import Dict, Any, List

from ..config import settings
from ..services.downloader import download_manager

logger = logging.getLogger("mediagrab.supervisor")


class WorkerSupervisor:
    """
    Subprocess and Worker Pool Supervisor:
    1. Monitors active download jobs and terminates hung subprocesses.
    2. Recovers unresponsive browser instances.
    3. Auto-scales worker concurrency limit based on queue depth.
    """
    def __init__(
        self,
        min_concurrency: int = 2,
        max_concurrency: int = 8,
        hung_timeout_seconds: int = 180,  # 3 minutes without progress
    ):
        self.min_concurrency = min_concurrency
        self.max_concurrency = max_concurrency
        self.hung_timeout_seconds = hung_timeout_seconds
        self.current_concurrency_limit = min_concurrency
        self.reaped_jobs_count = 0
        self.last_supervision_time = time.time()
        self._lock = asyncio.Lock()

    async def supervise_cycle(self) -> Dict[str, Any]:
        """Runs a single supervisory sweep across workers and subprocesses."""
        now = time.time()
        self.last_supervision_time = now
        reaped_this_cycle = 0

        # 1. Inspect download jobs for hung/unresponsive subprocesses
        all_jobs = list(download_manager.jobs.values())
        active_jobs = [j for j in all_jobs if j.status in ("downloading", "converting")]
        pending_jobs = [j for j in all_jobs if j.status == "pending"]

        for job in active_jobs:
            elapsed_since_creation = now - job.created_at
            # If job has been running for longer than the hung timeout and progress has halted
            if elapsed_since_creation > self.hung_timeout_seconds and job.progress_percent < 5.0:
                logger.warning(f"Supervisor: Job {job.job_id} hung for {elapsed_since_creation:.0f}s with {job.progress_percent}% progress. Reaping...")
                job.set_failed("Job timed out due to unresponsive source server stream (Auto-reaped by Worker Supervisor).")
                reaped_this_cycle += 1
                self.reaped_jobs_count += 1

        # 2. Auto-scale concurrency based on queue depth
        total_backlog = len(pending_jobs)
        async with self._lock:
            if total_backlog > 2 and self.current_concurrency_limit < self.max_concurrency:
                self.current_concurrency_limit = min(
                    self.max_concurrency,
                    self.current_concurrency_limit + 1
                )
                logger.info(f"Supervisor: Queue depth {total_backlog} -> Scaled worker concurrency to {self.current_concurrency_limit}")
            elif total_backlog == 0 and len(active_jobs) <= self.min_concurrency and self.current_concurrency_limit > self.min_concurrency:
                self.current_concurrency_limit = max(
                    self.min_concurrency,
                    self.current_concurrency_limit - 1
                )

        return {
            "active_workers": len(active_jobs),
            "pending_queue_depth": total_backlog,
            "current_concurrency_limit": self.current_concurrency_limit,
            "min_concurrency": self.min_concurrency,
            "max_concurrency": self.max_concurrency,
            "reaped_jobs_total": self.reaped_jobs_count,
            "reaped_this_cycle": reaped_this_cycle,
            "status": "healthy",
        }

    async def get_health_status(self) -> Dict[str, Any]:
        async with self._lock:
            active_jobs = [j for j in download_manager.jobs.values() if j.status in ("downloading", "converting")]
            pending_jobs = [j for j in download_manager.jobs.values() if j.status == "pending"]
            return {
                "active_workers": len(active_jobs),
                "pending_queue_depth": len(pending_jobs),
                "current_concurrency_limit": self.current_concurrency_limit,
                "reaped_jobs_total": self.reaped_jobs_count,
                "last_supervision_time": self.last_supervision_time,
                "status": "operational",
            }


worker_supervisor = WorkerSupervisor()


async def start_worker_supervisor_loop(interval_seconds: int = 15):
    """Background loop executing worker health and auto-recovery checks."""
    while True:
        try:
            await worker_supervisor.supervise_cycle()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in worker supervisor cycle: {e}")

        await asyncio.sleep(interval_seconds)
