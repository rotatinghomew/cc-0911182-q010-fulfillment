from .storage import records
from .units import pieces


def order_facts(connection):
    rows=records(connection,'SELECT * FROM order_lines ORDER BY line_id')
    for row in rows:
        row['ordered_pieces']=pieces(connection,row['line_id'],row['quantity'],row['unit'])
    return rows


def shipment_facts(connection):
    result=[]
    for row in records(connection,'SELECT * FROM shipments ORDER BY shipment_id'):
        try:
            row['pieces']=pieces(connection,row['line_id'],row['quantity'],row['unit'])
            row['issue']=None
        except ValueError as error:
            row['pieces']=None
            row['issue']=str(error)
        result.append(row)
    return result


def receipt_facts(connection):
    rows=records(connection,'SELECT r.*,s.line_id FROM receipts_business r LEFT JOIN shipments s USING(shipment_id) ORDER BY receipt_id')
    for row in rows:
        row['pieces']=pieces(connection,row['line_id'],row['quantity'],row['unit']) if row['line_id'] else None
        row['issue']=None if row['line_id'] else '尚无对应发运'
    return rows
