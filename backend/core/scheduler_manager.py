import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

# 全局单例调度器
scheduler = AsyncIOScheduler()

def refresh_dynamic_scheduler():
    """
    刷新动态调度任务。
    延迟导入以避免与 services/scheduler_service.py 产生循环引用。
    """
    from services.scheduler_service import sync_scheduler_jobs
    sync_scheduler_jobs(scheduler)
    logger.info("[Scheduler] Dynamic jobs refreshed successfully.")
