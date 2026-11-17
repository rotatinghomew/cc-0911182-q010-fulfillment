from .contracts import normalize
from .storage import canonical, digest, transaction
from .tables import TABLES


def ingest(connection, payload):
    if set(payload) != {'batch_id', 'tables'}:
        raise ValueError('报送必须包含批号和数据表')
    batch = payload['batch_id']
    if not isinstance(batch, str) or not batch.strip():
        raise ValueError('批号不能为空')
    if not isinstance(payload['tables'], dict):
        raise ValueError('数据表必须为对象')
    signature = digest(payload)
    prepared = []
    for table, rows in payload['tables'].items():
        if table not in TABLES:
            raise ValueError('未知数据表：' + table)
        if not isinstance(rows, list):
            raise ValueError('表记录必须为数组')
        columns, keys = TABLES[table]
        for original in rows:
            if not isinstance(original, dict) or set(original) != set(columns):
                raise ValueError('记录字段与契约不符：' + table)
            row = normalize(table, original)
            prepared.append((table, columns, keys, row))
    with transaction(connection):
        prior = connection.execute('SELECT signature FROM receipts WHERE batch_id=?', [batch]).fetchone()
        if prior:
            if prior[0] != signature:
                raise ValueError('相同批号内容不一致')
            return {'batch_id': batch, 'inserted': 0, 'replayed': True}
        inserted = 0
        for table, columns, keys, row in prepared:
            existing = connection.execute('SELECT payload FROM source_rows WHERE table_name=? AND row_key=?',
                [table, canonical([row[key] for key in keys])]).fetchone()
            serialized = canonical(row)
            if existing:
                if existing[0] != serialized:
                    raise ValueError('业务主键内容冲突：' + table)
                continue
            names = ','.join('"' + column + '"' for column in columns)
            marks = ','.join('?' for column in columns)
            connection.execute('INSERT INTO "' + table + '" (' + names + ') VALUES (' + marks + ')',
                [row[column] for column in columns])
            connection.execute('INSERT INTO source_rows VALUES (?,?,?,?)',
                [table, canonical([row[key] for key in keys]), serialized, batch])
            inserted += 1
        connection.execute('INSERT INTO receipts VALUES (?,?,?)', [batch, signature, inserted])
    return {'batch_id': batch, 'inserted': inserted, 'replayed': False}
