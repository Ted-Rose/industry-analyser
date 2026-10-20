"""DB-connection resilience for long-running scrape commands.

A management command holds one Django connection for its whole run.
When Postgres (or a NAT between Cloud Run and Aiven) drops it, every
subsequent ORM call raises 'connection already closed' — the request
signals that drive close_old_connections() never fire in a command,
so Django never reconnects on its own.
"""

import logging
from functools import wraps

from django.db import connection
from django.db.utils import InterfaceError, OperationalError

logger = logging.getLogger('scrape_jobs')


def retry_on_connection_loss(func):
    """Retry ``func`` once when the DB connection has been dropped.

    On InterfaceError/OperationalError the connection is pinged; when
    it is unusable it is closed (the next ORM call reconnects lazily)
    and ``func`` runs once more. Errors on a still-usable connection
    (deadlocks, statement timeouts) are re-raised without a retry.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (InterfaceError, OperationalError):
            if connection.is_usable():
                raise
            logger.warning(
                'DB connection dropped during %s - reconnecting',
                func.__qualname__,
            )
            connection.close()
            return func(*args, **kwargs)

    return wrapper
