from decimal import Decimal
from .facts import order_facts,shipment_facts,receipt_facts
from .storage import digest,transaction


def inspect(connection):
    issues=[]
    orders={row['line_id']:row for row in order_facts(connection)}
    shipped={}
    for row in shipment_facts(connection):
        if row['issue']:
            issues.append({'kind':'shipment','id':row['shipment_id'],'reason':row['issue']})
        else:
            shipped[row['line_id']]=shipped.get(row['line_id'],Decimal(0))+row['pieces']
    for line,quantity in shipped.items():
        if quantity>orders[line]['ordered_pieces']:
            issues.append({'kind':'order','id':line,'reason':'累计发运超过订单数量'})
    for row in receipt_facts(connection):
        if row['issue']:
            issues.append({'kind':'receipt','id':row['receipt_id'],'reason':row['issue']})
    with transaction(connection):
        connection.execute('DELETE FROM dispatch_issues')
        for issue in issues:
            connection.execute('INSERT INTO dispatch_issues VALUES (?,?,?,?)',[digest(issue),issue['kind'],issue['id'],issue['reason']])
    return issues
