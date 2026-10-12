"""Small process loop that publishes due PostgreSQL outbox messages."""

from __future__ import annotations

import logging
import os
import signal
import time

from services.alert_delivery_relay_service import relay_alert_deliveries_once


logger = logging.getLogger('alert_delivery_relay')
_stopping = False


def _stop(_signum, _frame) -> None:
    global _stopping
    _stopping = True


def main() -> None:
    logging.basicConfig(
        level=os.environ.get('LOG_LEVEL', 'INFO').upper(),
        format='%(asctime)s %(levelname)s %(name)s %(message)s',
    )
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    interval = max(0.1, float(os.environ.get('ALERT_NOTIFICATION_RELAY_INTERVAL_SECONDS', '0.5')))
    batch_size = max(1, min(100, int(os.environ.get('ALERT_NOTIFICATION_RELAY_BATCH_SIZE', '50'))))
    logger.info('Alert delivery relay started (interval=%s, batch=%s)', interval, batch_size)
    while not _stopping:
        started = time.monotonic()
        try:
            result = relay_alert_deliveries_once(limit=batch_size)
            if result.get('published') or result.get('failed') or result.get('recovered') or result.get('terminal_failures'):
                logger.info('Alert relay cycle: %s', result)
        except Exception:
            logger.exception('Alert delivery relay cycle failed')
        remaining = interval - (time.monotonic() - started)
        if remaining > 0 and not _stopping:
            time.sleep(remaining)
    logger.info('Alert delivery relay stopped')


if __name__ == '__main__':
    main()
