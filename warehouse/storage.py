import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

import duckdb


def open_store(path):
    connection = duckdb.connect(str(path))
    connection.execute("SET threads=1")
    connection.execute(Path(__file__).with_name('schema.sql').read_text())
    return connection


def records(connection, query, parameters=None):
    cursor = connection.execute(query, parameters or [])
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


@contextmanager
def transaction(connection):
    connection.execute('BEGIN TRANSACTION')
    try:
        yield
        connection.execute('COMMIT')
    except BaseException:
        connection.execute('ROLLBACK')
        raise


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()
