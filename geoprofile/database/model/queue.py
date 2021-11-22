from sqlalchemy.sql import expression
from sqlalchemy.sql import func
from geoprofile.database import db
import uuid
from hashlib import md5


class Queue(db.Model):
    """Queue Model
    Extends:
        db.Model
    Attributes:
        id (int): Primary Key.
        ticket (str): The ticket assigned to the request.
        status (int): The status of the process.
        success (bool): Whether the process has been completed.
        execution_time (float): The execution time in seconds.
        requested_time (datetime): The timestamp of the request.
        result (str): The path of the result.
        filesize (int): The size of the result file.
        comment (str): The error message in case of failure.

    """
    id = db.Column(db.BigInteger(), primary_key=True)
    ticket = db.Column(db.String(511), default=lambda: md5(str(uuid.uuid4()).encode()).hexdigest(), nullable=False, unique=True)
    status = db.Column(db.SmallInteger(), server_default='0', nullable=True)
    success = db.Column(db.SmallInteger(), server_default='0', nullable=True)
    execution_time = db.Column(db.Float(), nullable=True)
    requested_time = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    result = db.Column(db.Text(), nullable=True)
    filesize = db.Column(db.Integer(), nullable=True)
    comment = db.Column(db.Text(), nullable=True)

    def __iter__(self):
        for key in ['ticket', 'status', 'success', 'execution_time', 'requested_time', 'result', 'filesize', 'comment']:
            yield key, getattr(self, key)

    def get(self, **kwargs):
        queue = self.query.filter_by(**kwargs).first()
        if queue is None:
            return None
        return dict(queue)
