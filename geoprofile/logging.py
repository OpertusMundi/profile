from logging import getLogger, Filter
from flask import has_request_context, request
from os import getenv
from datetime import date


class ContextFilter(Filter):
    """A filter injecting contextual information into the log."""

    def filter(self, record):
        attributes = ['remote_addr', 'method', 'path', 'remote_user', 'authorization', 'content_length', 'referrer', 'user_agent']
        for attr in attributes:
            if has_request_context():
                value = getattr(request, attr)
                if value is not None:
                    setattr(record, attr, value)
                else:
                    setattr(record, attr, '-')
                print('%s: %s' % (attr, getattr(record, attr)))
            else:
                setattr(record, attr, None)
        return True


def getLoggers():
    """Create default loggers."""
    mainLog = getLogger(getenv('FLASK_APP'))
    accountLog = getLogger(getenv('FLASK_APP') + '.accounting')
    accountLog.addFilter(ContextFilter())

    def accountLogger(execution_start, execution_time, filesize, ticket='-', success=1, comment=None):
        assert isinstance(execution_start, date)
        success = bool(success)
        execution_start = execution_start.strftime("%Y-%m-%d %H:%M:%S")
        accountLog.info(f"ticket={ticket}, success={success}, execution_start={execution_start}, "
                        f"execution_time={execution_time}, comment={comment} filesize={filesize}")
    return mainLog, accountLogger
