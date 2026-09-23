from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from .config import settings
from .models import CartLine, CartResponse, Product


@dataclass
class PendingAction:
    pending_id: str
    product_id: str
    quantity: float
    created_at: float


CARTS: dict[str, dict[str, CartLine]] = {}
PENDING: dict[str, PendingAction] = {}


def create_pending(session_id: str, product: Product, quantity: float) -> PendingAction:
    pending = PendingAction(str(uuid.uuid4()), product.id, quantity, time.time())
    PENDING[session_id] = pending
    return pending


def get_pending(session_id: str) -> PendingAction | None:
    pending = PENDING.get(session_id)
    if pending and time.time() - pending.created_at > 15 * 60:
        PENDING.pop(session_id, None)
        return None
    return pending


def clear_pending(session_id: str) -> None:
    PENDING.pop(session_id, None)


def add_line(session_id: str, product: Product, quantity: float) -> None:
    cart = CARTS.setdefault(session_id, {})
    current = cart.get(product.id)
    new_qty = quantity + (current.quantity if current else 0)
    line_total = product.price * new_qty if product.price is not None else None
    cart[product.id] = CartLine(product=product, quantity=new_qty, line_total=line_total)


def get_cart(session_id: str) -> CartResponse:
    items = list(CARTS.get(session_id, {}).values())
    if items and all(x.line_total is not None for x in items):
        total = sum(float(x.line_total) for x in items if x.line_total is not None)
    else:
        total = None
    base = settings.public_base_url.rstrip("/")
    return CartResponse(items=items, total=total, cart_url=f"{base}/?session={session_id}#cart")
