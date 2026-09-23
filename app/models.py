from typing import Any
from pydantic import BaseModel, Field


class Product(BaseModel):
    id: str
    name: str
    sku: str | None = None
    category: str | None = None
    price: float | None = None
    stock: float | None = None
    stock_text: str | None = None
    certificate: str | None = None
    url: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)


class ChatRequest(BaseModel):
    session_id: str
    message: str
    attachment_ids: list[str] = Field(default_factory=list)


class PendingItem(BaseModel):
    pending_id: str
    product: Product
    quantity: float


class ChatResponse(BaseModel):
    answer: str
    products: list[Product] = Field(default_factory=list)
    confirmation_required: bool = False
    pending: PendingItem | None = None
    cart_url: str | None = None


class ConfirmRequest(BaseModel):
    session_id: str
    pending_id: str


class CartLine(BaseModel):
    product: Product
    quantity: float
    line_total: float | None = None


class CartResponse(BaseModel):
    items: list[CartLine]
    total: float | None = None
    cart_url: str
