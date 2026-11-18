from .storage import records
from .units import convert, facts_map


def order_facts(connection):
    facts = facts_map(connection)
    rows = records(connection, 'SELECT * FROM order_lines ORDER BY line_id')
    for row in rows:
        info = facts[row['line_id']]
        row['ordered_pieces'] = info['ordered_pieces']
        row['issue'] = info['issue']
    return rows


def shipment_facts(connection):
    facts = facts_map(connection)
    result = []
    for row in records(connection, 'SELECT * FROM shipments ORDER BY shipment_id'):
        row['pieces'], row['issue'] = convert(connection, row['line_id'],
                                              row['quantity'], row['unit'], facts)
        result.append(row)
    return result


def receipt_facts(connection):
    facts = facts_map(connection)
    rows = records(connection,
        'SELECT r.*,s.line_id,s.occurred_at AS shipment_at FROM receipts_business r '
        'LEFT JOIN shipments s USING(shipment_id) ORDER BY receipt_id')
    for row in rows:
        row['pieces'], row['issue'] = convert(connection, row['line_id'],
                                              row['quantity'], row['unit'], facts)
        if row['shipment_at'] is None:
            row['issue'] = '尚无对应发运'
        elif row['issue'] is None and row['occurred_at'] < row['shipment_at']:
            row['issue'] = '签收早于对应发运'
        row.pop('shipment_at')
    return rows
