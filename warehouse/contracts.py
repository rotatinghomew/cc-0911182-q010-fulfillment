from .checks import exact,moment,number,text

MOMENTS={'promised_at','occurred_at'}


def normalize(table,original):
    row=dict(original)
    for field,value in row.items():
        if field in {'quantity','pieces_per_box','amount'}:
            row[field]=number(value,True)
        elif field in MOMENTS or field.endswith('_at'):
            row[field]=moment(value)
        elif field in {'sku','unit','phase'}:
            row[field]=exact(value)
        else:
            row[field]=text(value)
    if 'unit' in row and row['unit'] not in {'box','piece'}:
        raise ValueError('数量单位未知')
    if table=='packaging' and float(row['pieces_per_box'])<=0:
        raise ValueError('包装换算应为正')
    if table=='cancellations' and row['phase'] not in {'unshipped','requested_after_dispatch'}:
        raise ValueError('取消阶段无效')
    if table=='returns' and row['phase'] not in {'requested','received'}:
        raise ValueError('退货阶段无效')
    return row
