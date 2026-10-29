from enum import StrEnum


class TransactionType(StrEnum):
    SALE = "sale"
    CUSTOMER_PAYMENT = "customer_payment"
    EXPENSE = "expense"
    SUPPLIER_PURCHASE = "supplier_purchase"
    SUPPLIER_PAYMENT = "supplier_payment"


class PaymentMethod(StrEnum):
    CASH = "cash"
    DIGITAL = "digital"  # mobile wallets: ZainCash, FastPay, ...
    BANK = "bank"  # bank transfer / card (Qi Card, ...)
    CREDIT = "credit"  # on account - no money moves yet


class ReconciliationStatus(StrEnum):
    RECONCILED = "reconciled"
    UNRECONCILED = "unreconciled"
    EXCLUDED = "excluded"  # confirmed duplicate / void: ignored by every total


class TransactionSource(StrEnum):
    MANUAL = "manual"
    SEED = "seed"
    CSV_IMPORT = "csv_import"


class CategoryKind(StrEnum):
    SALE = "sale"
    EXPENSE = "expense"
    PURCHASE = "purchase"
