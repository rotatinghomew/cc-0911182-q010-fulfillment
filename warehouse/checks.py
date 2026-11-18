from datetime import datetime
from decimal import Decimal, InvalidOperation


def text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('文本标识不能为空')
    return value


def exact(value):
    '''文本型业务字段原样保留，便于以稳定业务引用回查。'''
    if not isinstance(value, str):
        raise ValueError('文本字段必须为字符串')
    return value


def number(value, nonnegative=False):
    if isinstance(value, bool):
        raise ValueError('布尔值不是数量')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('数值格式错误') from None
    if not result.is_finite() or (nonnegative and result < 0):
        raise ValueError('数量超出范围')
    return str(result)


def moment(value):
    text(value)
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.utcoffset() is None:
        raise ValueError('时间必须包含时区')
    return stamp.isoformat()
