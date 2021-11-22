"""A collection of DB actions."""

from . import db
from .model import Queue


class DBItemNotFound(Exception):
    """Raised when an item not found on update."""


def db_queue(**data):
    """Add a record to queue table.

    Arguments:
        **data: The queue record data.

    Returns:
        (dict): The inserted queue record.
    """
    fields = data.keys()
    assert 'request' in fields
    queue = Queue(**data)
    db.session.add(queue)
    db.session.commit()
    return dict(queue)


def db_update_queue_status(ticket, **data):
    """Update Queue status.

    Arguments:
        ticket (str): Request ticket.
        **data: Data to update.

    Raises:
        DBItemNotFound -- Ticket not found in table.
    """
    from datetime import datetime, timezone
    elem = Queue.query.filter_by(ticket=ticket).first()
    if elem is None:
        raise DBItemNotFound("Item with ticket '{}' not found in table queue.".format(ticket))
    for key in data.keys():
        setattr(elem, key, data[key])
    elem.execution_time = (datetime.now(timezone.utc) - elem.initiated).total_seconds()
    db.session.add(elem)
    db.session.commit()


def db_get_active_jobs():
    """Returns a list with all the active jobs.

    Retrieves the active processes and information about each one.

    Returns:
        (list): A list with items the details about each active process.
    """

    jobs = Queue.query \
        .with_entities(Queue.ticket, Queue.initiated) \
        .filter(Queue.success == 0) \
        .all()

    return [dict(zip(['ticket', 'initiated'], job)) for job in jobs]
