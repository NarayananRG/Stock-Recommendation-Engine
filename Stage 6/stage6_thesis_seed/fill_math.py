from decimal import Decimal, InvalidOperation, localcontext

from .errors import Stage6ThesisSeedError

PRECISION=50

def decimal_value(value,field):
    if isinstance(value,bool): raise Stage6ThesisSeedError(f"INVALID_NUMBER:{field}")
    try: result=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError) as exc: raise Stage6ThesisSeedError(f"INVALID_NUMBER:{field}") from exc
    if not result.is_finite(): raise Stage6ThesisSeedError(f"INVALID_NUMBER:{field}")
    return result

def json_number(value):
    if value==value.to_integral(): return int(value)
    return float(format(value,"f"))

def canonicalize_fills(fills):
    return sorted(fills,key=lambda x:(x["fill_date"],x["transaction_id"]))

def aggregate_fills(fills):
    if not fills:return None,None
    with localcontext() as context:
        context.prec=PRECISION
        quantity=sum(x["quantity"] for x in fills)
        vwap=sum(Decimal(x["quantity"])*decimal_value(x["price"],"price") for x in fills)/Decimal(quantity)
    return {"total_quantity":quantity,"volume_weighted_average_price":json_number(vwap),"currency":"INR"},min(x["fill_date"] for x in fills)
