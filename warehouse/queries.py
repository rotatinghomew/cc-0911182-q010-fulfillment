from .build import order_snapshot
from .facts import order_facts,shipment_facts,receipt_facts
from .storage import records


def overview(connection):
    return {'orders':order_facts(connection),'shipments':shipment_facts(connection),'receipts':receipt_facts(connection),
            'cancellations':records(connection,'SELECT * FROM cancellations ORDER BY cancel_id'),
            'returns':records(connection,'SELECT * FROM returns ORDER BY return_id')}


def orders(connection):
    return order_snapshot(connection)['lines']


def line_quantities(connection,line_id):
    '''

    某订单行的累积数量及逐笔数量依据。返回 None 表示订单行不存在。
    '''
    snapshot=order_snapshot(connection)
    for line in snapshot['lines']:
        if line['line_id']==line_id:
            return {'line':line,
                    'details':[row for row in snapshot['details'] if row['line_id']==line_id]}
    return None


def build_details(connection):
    return order_snapshot(connection)['details']


def blocked_reasons(connection):
    return order_snapshot(connection)['issues']


def discrepancies(connection):
    return order_snapshot(connection)['discrepancies']
