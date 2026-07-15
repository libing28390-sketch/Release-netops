"""Worker abstraction for unified jobs.

Database target claiming supplies cross-process/device locking. The local
executor only controls work within this API/worker process.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from services.discovery_service import DiscoveryService
from services.job_service import claim_targets, complete_target, get_job


logger = logging.getLogger(__name__)


def _execute_target(job: dict, target: dict) -> dict:
    job_type = job.get('job_type') or 'generic'
    if job_type == 'discovery':
        result = DiscoveryService().discover_device(
            target['target_id'], requested_by=job.get('created_by') or 'system',
        )
        if not result.get('success'):
            raise RuntimeError(result.get('error') or 'Discovery failed')
        return result
    raise RuntimeError(f"No worker handler registered for job_type '{job_type}'")


def run_job(job_id: str) -> dict:
    """Run queued targets until exhausted or cancellation is requested."""
    while True:
        job = get_job(job_id)
        if job.get('cancel_requested') or job.get('status') in {'succeeded', 'partially_failed', 'failed', 'cancelled', 'timeout'}:
            return job
        targets = claim_targets(job_id)
        if not targets:
            return get_job(job_id)
        workers = min(max(1, int(job.get('concurrency_limit') or 1)), len(targets))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f'nexora-job-{job_id[:8]}') as executor:
            futures = {executor.submit(_execute_target, job, target): target for target in targets}
            for future in as_completed(futures):
                target = futures[future]
                try:
                    result = future.result(timeout=max(1, int(job.get('timeout_seconds') or 300)))
                    complete_target(target['id'], status='succeeded', result=result)
                except Exception as exc:
                    logger.error("Job %s target %s failed: %s", job_id, target['target_id'], exc, exc_info=True)
                    complete_target(target['id'], status='failed', error_message=str(exc))
