from .facts import order_facts,shipment_facts,receipt_facts
from .storage import records


def overview(connection):
    return {'orders':order_facts(connection),'shipments':shipment_facts(connection),'receipts':receipt_facts(connection),
            'cancellations':records(connection,'SELECT * FROM cancellations ORDER BY cancel_id'),
            'returns':records(connection,'SELECT * FROM returns ORDER BY return_id')}
