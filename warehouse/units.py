from decimal import Decimal
from .storage import records


def package_for(connection, pack_id):
    '''按包装主键取固定换算，不回退到商品的最新包装。'''
    row = connection.execute('SELECT sku,pieces_per_box FROM packaging WHERE pack_id=?',
                             [pack_id]).fetchone()
    if row is None:
        raise ValueError('包装引用未知')
    return row[0], Decimal(str(row[1]))


def facts_map(connection):
    '''
    订单行到换算事实的映射。包装锚定在订单引用的版本上，不使用商品最新包装；
    发运按件记录时不要求它单独引用包装，按箱记录时包装必须与订单一致。
    '''
    packs = {}
    for row in records(connection, 'SELECT * FROM packaging'):
        packs[row['pack_id']] = (row['sku'], Decimal(str(row['pieces_per_box'])))
    result = {}
    for row in records(connection, 'SELECT * FROM order_lines ORDER BY line_id'):
        pack = packs.get(row['pack_id'])
        info = {'order_sku':row['sku'],'order_pack_id':row['pack_id'],'factor':None,
                'ordered_pieces':None,'issue':None}
        if pack is None:
            info['issue'] = '包装引用未知'
        else:
            info['factor'] = pack[1]
            if pack[0] != row['sku']:
                info['issue'] = '订单包装引用未知或不匹配'
            elif row['unit'] not in {'piece','box'}:
                info['issue'] = '数量单位未知'
            else:
                info['ordered_pieces'] = Decimal(str(row['quantity'])) * (
                    pack[1] if row['unit'] == 'box' else Decimal(1))
        result[row['line_id']] = info
    return result


def facts_for(connection, line_id):
    return facts_map(connection).get(line_id)


def pieces(connection, line_id, quantity, unit, facts=None):
    info = (facts if facts is not None else facts_map(connection)).get(line_id)
    if info is None:
        raise ValueError('订单行引用未知')
    if info['issue']:
        raise ValueError(info['issue'])
    if unit not in {'piece','box'}:
        raise ValueError('数量单位未知')
    return Decimal(str(quantity)) * (info['factor'] if unit == 'box' else Decimal(1))


def convert(connection, line_id, quantity, unit, facts=None):
    '''逐行换算，返回 (件数, 阻塞原因)，不抛出异常。'''
    info = (facts if facts is not None else facts_map(connection)).get(line_id)
    if info is None:
        return None, '订单行引用未知'
    if info['issue']:
        return None, info['issue']
    if unit not in {'piece','box'}:
        return None, '数量单位未知'
    return Decimal(str(quantity)) * (info['factor'] if unit == 'box' else Decimal(1)), None
