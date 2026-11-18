from datetime import datetime
from decimal import Decimal

from .facts import order_facts, receipt_facts, shipment_facts
from .storage import records
from .units import convert, facts_map

ZERO = Decimal(0)


def _time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _milestone(ordered, reductions, progresses):
    '''

    最早的里程碑时刻：截至该时刻累计完成量已达到当时仍然有效的应履约数量。
    reductions 为未发取消（下调应履约），progresses 为发运或签收累计。
    每个事件带来源单据自己的发生时间，因此同一组单据无论按什么顺序补录结果相同。
    '''
    reduced = {}
    for stamp, _reference, amount in reductions:
        reduced[stamp] = reduced.get(stamp, ZERO) + amount
    progressed = {}
    for stamp, _reference, amount in progresses:
        progressed[stamp] = progressed.get(stamp, ZERO) + amount
    done = ZERO
    cancelled = ZERO
    trigger = None
    for stamp in sorted(set(reduced) | set(progressed)):
        cancelled += reduced.get(stamp, ZERO)
        done += progressed.get(stamp, ZERO)
        committed = ordered - cancelled
        if committed > ZERO and done >= committed:
            trigger = stamp
            break
    if trigger is None:
        return None
    # 里程碑由业务进度事实落章：若完成是随后续取消才成立的，仍记在最后一次进度上。
    if trigger in progressed:
        return trigger
    earlier = [stamp for stamp in progressed if stamp < trigger]
    return max(earlier) if earlier else None


def _iso(value):
    return value.isoformat() if value is not None else None


def decimal_text(value):
    return None if value is None else str(value)


def order_snapshot(connection):
    '''

    按订单行汇总承诺、已发、已收、未履约、退货中和已退回数量，并给出里程碑。
    只读取现有独立事实表，不改变这些表的取数方式。
    '''
    facts = facts_map(connection)
    orders = {row['line_id']: row for row in order_facts(connection)}
    shipments = shipment_facts(connection)
    receipts = receipt_facts(connection)
    cancellations = records(connection, 'SELECT * FROM cancellations ORDER BY cancel_id')
    returns = records(connection, 'SELECT * FROM returns ORDER BY return_id')

    issues = []
    details = []
    seen = set()

    def report(kind, reference, reason, line_id=None, recorded=None, applied=None):
        key = (kind, reference, reason)
        if key in seen:
            return
        seen.add(key)
        issues.append({'kind':kind,'id':reference,'line_id':line_id,'reason':reason,
                       'recorded_pieces':recorded,'applied_pieces':applied})

    shipment_by_id = {}
    shipments_by_line = {}
    unusable_shipments = set()
    for row in shipments:
        shipment_by_id[row['shipment_id']] = row
        if row['line_id'] in orders:
            shipments_by_line.setdefault(row['line_id'], []).append(row)
        else:
            unusable_shipments.add(row['shipment_id'])
            report('shipment', row['shipment_id'], row['issue'] or '订单行引用未知')
    for row in shipments:
        if row['line_id'] in orders and row['issue']:
            unusable_shipments.add(row['shipment_id'])
            report('shipment', row['shipment_id'], row['issue'])

    receipts_by_shipment = {}
    for row in receipts:
        receipts_by_shipment.setdefault(row['shipment_id'], []).append(row)
        if row['shipment_id'] not in shipment_by_id:
            report('receipt', row['receipt_id'], '尚无对应发运')
        elif row['shipment_id'] in unusable_shipments:
            report('receipt', row['receipt_id'], row['issue'] or '发运引用的订单行未知')
    returns_by_shipment = {}
    for row in returns:
        returns_by_shipment.setdefault(row['shipment_id'], []).append(row)
        if row['shipment_id'] not in shipment_by_id:
            report('return', row['return_id'], '发运引用未知')
        elif row['shipment_id'] in unusable_shipments:
            report('return', row['return_id'], '发运引用的订单行未知')

    cancels_by_line = {}
    for row in cancellations:
        if row['line_id'] in orders:
            cancels_by_line.setdefault(row['line_id'], []).append(row)
        else:
            report('cancellation', row['cancel_id'], '订单行引用未知')

    lines = []
    for line_id in sorted(orders):
        order = orders[line_id]
        ordered = order['ordered_pieces']
        line_issue_count = len(issues)
        if order['issue']:
            report('order', line_id, order['issue'], line_id)

        def line_issues():
            return issues[line_issue_count:]

        def note_issue(kind, reference, reason, recorded=None, applied=None):
            report(kind, reference, reason, line_id, recorded, applied)

        # 未发取消：只能下调应履约数量，且累计不超过订单数量。
        unshipped_cancelled = ZERO
        after_dispatch = ZERO
        cancel_events = []
        for row in sorted(cancels_by_line.get(line_id, []),
                          key=lambda item: (_time(item['occurred_at']), item['cancel_id'])):
            amount, reason = convert(connection, line_id, row['quantity'], row['unit'], facts)
            applied = None
            note = None
            if amount is None:
                note_issue('cancellation', row['cancel_id'], reason or '数量无法换算')
            elif row['phase'] == 'unshipped':
                applied = min(amount, max(ZERO, (ordered or ZERO) - unshipped_cancelled))
                unshipped_cancelled += applied
                cancel_events.append((_time(row['occurred_at']), row['cancel_id'], applied))
                if applied < amount:
                    note_issue('cancellation', row['cancel_id'], '取消数量超过应履约数量',
                               amount, applied)
            else:
                # 发出后的取消申请只是申请，不冲减任何已发数量。
                applied = ZERO
                after_dispatch += amount
                note = '发出后取消申请，不冲减已发数量'
            details.append({'line_id':line_id,'goal_kind':'order','goal_id':line_id,
                            'event':'cancel_unshipped' if row['phase'] == 'unshipped'
                            else 'cancel_after_dispatch',
                            'event_id':row['cancel_id'],'occurred_at':row['occurred_at'],
                            'quantity':row['quantity'],'unit':row['unit'],'pieces':amount,
                            'applied_pieces':applied,'issue':None,'note':note})

        # 发运按发运单聚合，签收和退货只在本发运的件数内计入，拆包不会放大数量。
        segments = {}
        for row in sorted(shipments_by_line.get(line_id, []),
                          key=lambda item: (_time(item['occurred_at']), item['shipment_id'])):
            segments[row['shipment_id']] = {'row':row,'pieces':row['pieces'],
                                            'receipts':[],'returns':[],
                                            'received':ZERO,'request_here':ZERO,
                                            'returned_here':ZERO}
            if row['pieces'] is None:
                note_issue('shipment', row['shipment_id'], row['issue'] or '数量无法换算')
        shipped = sum((segment['pieces'] for segment in segments.values()
                       if segment['pieces'] is not None), ZERO)

        for shipment_id, segment in segments.items():
            shipment = segment['row']
            cap = segment['pieces'] if segment['pieces'] is not None else ZERO
            running = ZERO
            for row in sorted(receipts_by_shipment.get(shipment_id, []),
                              key=lambda item: (_time(item['occurred_at']), item['receipt_id'])):
                amount, reason = convert(connection, line_id, row['quantity'], row['unit'], facts)
                applied = None
                note = reason
                if amount is not None:
                    if _time(row['occurred_at']) < _time(shipment['occurred_at']):
                        note = '签收早于对应发运'
                    elif segment['pieces'] is None:
                        note = '对应发运无法换算'
                    else:
                        applied = min(amount, max(ZERO, cap - running))
                        running += applied
                        if applied < amount:
                            note = '签收超过对应发运数量'
                if note:
                    note_issue('receipt', row['receipt_id'], note, amount, applied)
                segment['receipts'].append({'row':row,'pieces':amount,
                                            'applied':applied,'issue':note})
            segment['received'] = running

            running = ZERO
            for row in sorted(returns_by_shipment.get(shipment_id, []),
                              key=lambda item: (_time(item['occurred_at']), item['return_id'])):
                amount, reason = convert(connection, line_id, row['quantity'], row['unit'], facts)
                requested = None
                received = None
                note = reason
                if amount is not None:
                    requested = min(amount, max(ZERO, cap - running))
                    running += requested
                    if row['phase'] == 'received':
                        received = min(amount, max(ZERO, cap - segment['returned_here']))
                        segment['returned_here'] += received
                    if requested < amount:
                        note = '退货数量超过相应发运数量'
                if note:
                    note_issue('return', row['return_id'], note, amount, requested)
                segment['returns'].append({'row':row,'pieces':amount,'requested':requested,
                                           'returned':received,'issue':note})
            segment['request_here'] = running

        for segment in segments.values():
            shipment = segment['row']
            details.append({'line_id':line_id,'goal_kind':'shipment',
                            'goal_id':shipment['shipment_id'],'event':'shipment',
                            'event_id':shipment['shipment_id'],
                            'occurred_at':shipment['occurred_at'],
                            'quantity':shipment['quantity'],'unit':shipment['unit'],
                            'pieces':segment['pieces'],'applied_pieces':segment['pieces'],
                            'issue':shipment['issue'],'note':None})
            for entry in segment['receipts']:
                row = entry['row']
                details.append({'line_id':line_id,'goal_kind':'shipment',
                                'goal_id':shipment['shipment_id'],'event':'receipt',
                                'event_id':row['receipt_id'],'occurred_at':row['occurred_at'],
                                'quantity':row['quantity'],'unit':row['unit'],
                                'pieces':entry['pieces'],'applied_pieces':entry['applied'],
                                'issue':entry['issue'],'note':None})
            for entry in segment['returns']:
                row = entry['row']
                base = {'line_id':line_id,'goal_kind':'shipment',
                        'goal_id':shipment['shipment_id'],'event_id':row['return_id'],
                        'occurred_at':row['occurred_at'],'quantity':row['quantity'],
                        'unit':row['unit'],'pieces':entry['pieces'],
                        'issue':entry['issue'],'note':None}
                details.append(dict(base, event='return_requested',
                                    applied_pieces=entry['requested']))
                if row['phase'] == 'received':
                    details.append(dict(base, event='return_received',
                                        applied_pieces=entry['returned']))

        received = sum((segment['received'] for segment in segments.values()), ZERO)
        return_pending = sum((segment['request_here'] - segment['returned_here']
                              for segment in segments.values()), ZERO)
        returned = sum((segment['returned_here'] for segment in segments.values()), ZERO)

        blocking = [issue for issue in line_issues() if issue['applied_pieces'] is None]
        if ordered is None:
            committed = unfulfilled = net_received = None
            milestones = (None, None, None)
            received_complete = None
        else:
            committed = max(ZERO, ordered - unshipped_cancelled)
            unfulfilled = max(ZERO, committed - shipped)
            net_received = max(ZERO, received - returned)
            # 完成签收必须以存在应履约数量为前提，全部取消只说明不再需要履约。
            received_complete = committed > ZERO and net_received >= committed
            if blocking:
                received_complete = None
                milestones = (None, None, None)
            else:
                ship_events = [(_time(segment['row']['occurred_at']),
                                segment['row']['shipment_id'], segment['pieces'])
                               for segment in segments.values()
                               if segment['pieces'] is not None]
                receipt_events = [(_time(entry['row']['occurred_at']),
                                   entry['row']['receipt_id'],
                                   entry['applied'] if entry['applied'] is not None else ZERO)
                                  for segment in segments.values()
                                  for entry in segment['receipts']]
                positive = [event for event in ship_events if event[2] > ZERO]
                first_shipped = min(positive, key=lambda event: (event[0], event[1]))[0] \
                    if positive else None
                all_shipped = _milestone(ordered, cancel_events, ship_events)
                all_received = _milestone(ordered, cancel_events, receipt_events)
                # 首次发运只看发运事实，取消不会抹去曾经发生的发运。
                milestones = (_iso(first_shipped), _iso(all_shipped), _iso(all_received))
            if shipped > committed:
                if shipped > ordered:
                    reason = '累计发运超过订单数量'
                else:
                    reason = '累计发运超过未发取消后的应履约数量'
                note_issue('order', line_id, reason, shipped, committed)

        lines.append({'line_id':line_id,'sku':order['sku'],'pack_id':order['pack_id'],
                      'order_quantity':order['quantity'],'unit':order['unit'],
                      'amount':order['amount'],'promised_at':order['promised_at'],
                      'ordered_pieces':ordered,'committed_pieces':committed,
                      'shipped_pieces':shipped if ordered is not None else None,
                      'received_pieces':received if ordered is not None else None,
                      'unfulfilled_pieces':unfulfilled,
                      'return_pending_pieces':return_pending if ordered is not None else None,
                      'returned_pieces':returned if ordered is not None else None,
                      'net_received_pieces':net_received,
                      'after_dispatch_cancel_pieces':(after_dispatch
                                                       if ordered is not None else None),
                      'first_shipped_at':milestones[0],
                      'all_shipped_at':milestones[1],
                      'all_received_at':milestones[2],
                      'received_complete':received_complete,
                      'blocked':order['issue'] is not None or bool(blocking),
                      'issues':line_issues()})

    discrepancies = [issue for issue in issues
                     if issue['recorded_pieces'] is not None
                     and issue['applied_pieces'] is not None
                     and issue['recorded_pieces'] != issue['applied_pieces']]
    return {'lines':lines,'details':details,'issues':issues,'discrepancies':discrepancies}
