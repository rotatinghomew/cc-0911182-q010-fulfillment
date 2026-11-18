from .build import decimal_text, order_snapshot
from .storage import canonical, digest, transaction


def inspect(connection):
    '''

    把累积快照发现的阻塞原因和数量差异登记为当前异常。
    每条异常保留来源单据引用；不改变任何独立事实表的行。
    '''
    snapshot = order_snapshot(connection)
    with transaction(connection):
        connection.execute('DELETE FROM dispatch_issues')
        for issue in snapshot['issues']:
            payload = {'kind':issue['kind'],'id':issue['id'],'line_id':issue['line_id'],
                       'reason':issue['reason'],
                       'recorded_pieces':decimal_text(issue['recorded_pieces']),
                       'applied_pieces':decimal_text(issue['applied_pieces'])}
            connection.execute('INSERT INTO dispatch_issues VALUES (?,?,?,?,?)',
                               [digest(payload),issue['kind'],issue['id'],
                                canonical(payload),issue['reason']])
    return snapshot['issues']
