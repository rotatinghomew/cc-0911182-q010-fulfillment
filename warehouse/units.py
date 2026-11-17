from decimal import Decimal


def pieces(connection,line_id,quantity,unit):
    row=connection.execute('SELECT o.sku,p.sku,p.pieces_per_box FROM order_lines o JOIN packaging p USING(pack_id) WHERE line_id=?',[line_id]).fetchone()
    if row is None or row[0]!=row[1]:
        raise ValueError('订单包装引用未知或不匹配')
    if unit not in {'piece','box'}:
        raise ValueError('数量单位未知')
    return Decimal(str(quantity))*(row[2] if unit=='box' else Decimal(1))
