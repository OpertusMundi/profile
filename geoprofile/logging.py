from logging import getLogger, Filter
from logging.config import fileConfig
from flask import has_request_context, request
from os import path, getenv
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
    if getenv('LOGGING') is None:
        log_file_path = path.join(path.dirname(path.abspath(__file__)), 'logging.conf')
        fileConfig(log_file_path)
    else:
        fileConfig(getenv('LOGGING'))
    mainLog = getLogger(getenv('FLASK_APP'))
    accountLog = getLogger(getenv('FLASK_APP') + '.accounting')
    accountLog.addFilter(ContextFilter())

    def accountLogger(execution_start, execution_time, filesize, ticket='-', success=1, comment=None):
        assert isinstance(execution_start, date)
        success = bool(success)
        execution_start = execution_start.strftime("%Y-%m-%d %H:%M:%S")
        accountLog.info("ticket=%s, success=%s, execution_start=%s, execution_time=%ss, comment=%s, filesize=%s",
                        ticket, success, execution_start, execution_time, comment, filesize)
    return mainLog, accountLogger
