import logging
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

# Keep long-running collectors from piling up overlapping executions. The
# database lock still protects multi-instance deployments; these defaults
# protect a single process from its own misfires and slow jobs.
_SCHEDULER_MISFIRE_GRACE = max(5, int(os.environ.get('SCHEDULER_MISFIRE_GRACE_SECONDS', '30')))
scheduler = AsyncIOScheduler(
    job_defaults={
        'coalesce': True,
        'max_instances': 1,
        'misfire_grace_time': _SCHEDULER_MISFIRE_GRACE,
    },
)

# 全局单例调度器

def refresh_dynamic_scheduler():
    """
    刷新动态调度任务。
    延迟导入以避免与 services/scheduler_service.py 产生循环引用。
    """
    from services.scheduler_service import sync_scheduler_jobs
    sync_scheduler_jobs(scheduler)
    logger.info("[Scheduler] Dynamic jobs refreshed successfully.")
