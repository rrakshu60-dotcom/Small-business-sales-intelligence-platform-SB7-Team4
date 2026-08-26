from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.invoice import Invoice
from app.models.payment import Payment
from app.models.sales_transaction import SalesTransaction

# =====================================================
# Total Revenue
# =====================================================

def get_total_revenue(
    db: Session
):

    sales_total = (
        db.query(
            func.sum(SalesTransaction.total_amount)
        )
        .scalar()
    )

    if sales_total is not None and sales_total > 0:
        return sales_total

    total = (
        db.query(
            func.sum(Payment.amount_paid)
        )
        .scalar()
    )

    return total or Decimal("0.00")

# =====================================================
# Daily Collections
# =====================================================

def get_daily_collections(
    db: Session
):

    total = (
        db.query(
            func.sum(Payment.amount_paid)
        )
        .filter(
            Payment.payment_date == date.today()
        )
        .scalar()
    )

    return total or Decimal("0.00")

# =====================================================
# Total Outstanding
# =====================================================

def get_total_outstanding(
    db: Session
):

    total = (
        db.query(
            func.sum(Invoice.total_amount)
        )
        .filter(
            Invoice.payment_status != "Paid"
        )
        .scalar()
    )

    return total or Decimal("0.00")
