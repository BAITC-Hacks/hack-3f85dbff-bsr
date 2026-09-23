from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .models import Product


@dataclass
class SessionState:
    products: list[Product] = field(default_factory=list)
    selected_index: int = 0
    updated_at: float = field(default_factory=time.time)


_SESSIONS: dict[str, SessionState] = {}
_TTL_SECONDS = 60 * 60 * 4


def _cleanup() -> None:
    now = time.time()
    expired = [sid for sid, state in _SESSIONS.items() if now - state.updated_at > _TTL_SECONDS]
    for sid in expired:
        _SESSIONS.pop(sid, None)


def remember_products(session_id: str, products: list[Product], selected_index: int = 0) -> None:
    if not products:
        return
    _cleanup()
    _SESSIONS[session_id] = SessionState(
        products=products[:8],
        selected_index=max(0, min(selected_index, len(products) - 1)),
        updated_at=time.time(),
    )


def get_products(session_id: str) -> list[Product]:
    _cleanup()
    state = _SESSIONS.get(session_id)
    if not state:
        return []
    state.updated_at = time.time()
    return state.products


def get_selected(session_id: str) -> Product | None:
    products = get_products(session_id)
    if not products:
        return None
    state = _SESSIONS[session_id]
    idx = max(0, min(state.selected_index, len(products) - 1))
    return products[idx]


def select_from_text(session_id: str, text: str) -> Product | None:
    products = get_products(session_id)
    if not products:
        return None

    t = text.lower()
    index = None
    if re.search(r"\b(перв(ый|ую|ого)|1[- ]?й|бірінші)\b", t):
        index = 0
    elif re.search(r"\b(втор(ой|ую|ого)|2[- ]?й|екінші)\b", t):
        index = 1
    elif re.search(r"\b(трет(ий|ью|ьего)|3[- ]?й|үшінші)\b", t):
        index = 2

    if index is not None and index < len(products):
        _SESSIONS[session_id].selected_index = index
        _SESSIONS[session_id].updated_at = time.time()
        return products[index]

    return get_selected(session_id)


def is_followup(text: str) -> bool:
    t = text.lower().strip()
    markers = [
        "сертифик", "характерист", "параметр", "цена", "стоим", "сколько",
        "остат", "налич", "этот", "этого", "его", "ее", "её", "перв",
        "втор", "трет", "добав", "корзин", "купить", "закаж", "дешевле",
        "дороже", "подробнее", "ссылка", "артикул", "код", "осы", "бірінші",
        "екінші", "үшінші", "бағасы", "сипаттам", "қалдық", "себет",
    ]
    return any(m in t for m in markers)
