"""Order management — the "Trading-as-Git" order lifecycle.

Orders are staged, reviewed, committed with a message, then pushed (executed),
with a full append-only history reviewable by id. Clean-room reimplementation of
the OpenAlice concept in Python; nothing ported from its source.
"""
from .ledger import OrderManager, OrderRecord

__all__ = ["OrderManager", "OrderRecord"]
