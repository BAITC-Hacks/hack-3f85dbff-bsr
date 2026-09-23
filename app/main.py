from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .ai import extract_quantity, is_confirmation, llm_answer, product_id_candidates, wants_add, wants_analog, wants_purchase_info
from .attachments import save_upload
from .cart import add_line, clear_pending, create_pending, get_cart, get_pending
from .ekt_client import ekt
from .models import ChatRequest, ChatResponse, ConfirmRequest, PendingItem
from .session_state import get_products, is_followup, remember_products, select_from_text

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="EKT AI Assistant", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health():
    return {"ok": True, "service": "EKT AI Assistant", "version": "2.0.0"}


@app.get("/api/debug/ekt")
async def debug_ekt():
    from .config import settings
    info = {
        "base": settings.ekt_api_base,
        "user": settings.ekt_api_user,
        "password_configured": bool(settings.ekt_api_password),
        "proxy_env_ignored": True,
    }
    try:
        items = await ekt.get_page(1)
        info.update({"ok": True, "products_on_page_1": len(items)})
    except Exception as exc:
        info.update({"ok": False, "error_type": type(exc).__name__, "error": str(exc)})
    return info


@app.get("/api/catalog")
async def catalog(page: int = 1):
    try:
        return await ekt.get_page(page)
    except Exception as exc:
        raise HTTPException(502, f"EKT API недоступен: {exc}") from exc


@app.get("/api/product/{product_id}")
async def product(product_id: str):
    try:
        return await ekt.get_detail(product_id)
    except Exception as exc:
        raise HTTPException(502, f"Не удалось получить карточку товара: {exc}") from exc


@app.get("/api/search")
async def search(q: str, limit: int = 6):
    try:
        return await ekt.search(q, min(max(limit, 1), 20))
    except Exception as exc:
        raise HTTPException(502, f"Ошибка поиска по EKT API: {exc}") from exc


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    allowed = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "image/jpeg", "image/png", "image/webp", "text/plain",
    }
    if file.content_type and file.content_type not in allowed:
        raise HTTPException(415, "Поддерживаются PDF, DOCX, XLSX, TXT, JPEG, PNG, WEBP")
    return await save_upload(file)


@app.get("/api/cart/{session_id}")
async def cart(session_id: str):
    return get_cart(session_id)


@app.post("/api/cart/cancel/{session_id}")
async def cancel_cart_action(session_id: str):
    clear_pending(session_id)
    return {"ok": True}


@app.post("/api/cart/confirm")
async def confirm(req: ConfirmRequest):
    pending = get_pending(req.session_id)
    if not pending or pending.pending_id != req.pending_id:
        raise HTTPException(409, "Нет актуального подтверждаемого действия")

    try:
        product = await ekt.get_detail(pending.product_id)
    except Exception as exc:
        raise HTTPException(502, f"Не удалось повторно проверить товар: {exc}") from exc

    qty = pending.quantity
    if product.stock is not None and product.stock <= 0:
        clear_pending(req.session_id)
        raise HTTPException(409, "Товар закончился до подтверждения")
    if product.stock is not None and qty > product.stock:
        raise HTTPException(409, f"Запрошено {qty:g}, доступно только {product.stock:g}")

    add_line(req.session_id, product, qty)
    clear_pending(req.session_id)
    result = get_cart(req.session_id)
    return {"ok": True, "message": f"{product.name} — {qty:g} добавлено в корзину.", "cart": result}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    text = req.message.strip()
    if not text and not req.attachment_ids:
        raise HTTPException(400, "Введите сообщение или приложите файл")

    # Подтверждение всегда обрабатывает backend, а не LLM.
    pending = get_pending(req.session_id)
    if pending and is_confirmation(text):
        try:
            product = await ekt.get_detail(pending.product_id)
        except Exception as exc:
            raise HTTPException(502, f"Не удалось повторно проверить товар: {exc}") from exc
        if product.stock is not None and pending.quantity > product.stock:
            return ChatResponse(answer=f"Сейчас доступно только {product.stock:g}. Укажите меньшее количество.", products=[product])
        if product.stock is not None and product.stock <= 0:
            clear_pending(req.session_id)
            return ChatResponse(answer="Пока вы подтверждали, товар закончился. Могу подобрать аналог.", products=[product])
        add_line(req.session_id, product, pending.quantity)
        clear_pending(req.session_id)
        remember_products(req.session_id, [product])
        cart_data = get_cart(req.session_id)
        return ChatResponse(answer=f"Готово: {product.name} — {pending.quantity:g} добавлено в корзину.", products=[product], cart_url=cart_data.cart_url)

    try:
        products = []

        # Точный ID имеет приоритет.
        for candidate in product_id_candidates(text):
            try:
                products = [await ekt.get_detail(candidate)]
                break
            except Exception:
                pass

        # Короткий follow-up использует товары из текущей сессии.
        if not products and is_followup(text):
            selected = select_from_text(req.session_id, text)
            previous = get_products(req.session_id)
            if selected:
                products = [selected] + [p for p in previous if p.id != selected.id][:4]

        if not products:
            products = await ekt.search(text, 5)
    except Exception as exc:
        if wants_purchase_info(text):
            return ChatResponse(answer=await llm_answer(text, [], req.attachment_ids))
        raise HTTPException(502, f"Не удалось обратиться к каталогу EKT: {exc}") from exc

    # Подтягиваем detail для первых результатов.
    detailed = []
    for p in products[:3]:
        try:
            detailed.append(await ekt.get_detail(p.id))
        except Exception:
            detailed.append(p)
    products = detailed + products[len(detailed):]

    if products:
        remember_products(req.session_id, products)

    if products and wants_analog(text):
        source = products[0]
        analogs = await ekt.analogs(source, 3)
        if analogs:
            remember_products(req.session_id, [source] + analogs)
        answer = await llm_answer(text, [source] + analogs, req.attachment_ids, extra="Первый товар — исходная позиция, остальные — кандидаты в аналоги.")
        return ChatResponse(answer=answer, products=analogs)

    if products and products[0].stock is not None and products[0].stock <= 0:
        analogs = await ekt.analogs(products[0], 3)
        answer = await llm_answer(text, [products[0]] + analogs, req.attachment_ids, extra="У исходного товара нулевой остаток; предложи подходящие аналоги и объясни выбор.")
        return ChatResponse(answer=answer, products=analogs)

    if products and wants_add(text):
        p = products[0]
        qty = extract_quantity(text)
        if p.stock is not None and p.stock <= 0:
            analogs = await ekt.analogs(p, 3)
            answer = await llm_answer(text, [p] + analogs, req.attachment_ids, extra="Исходного товара нет в наличии. Ничего в корзину не добавлять; предложить аналоги.")
            return ChatResponse(answer=answer, products=analogs)
        if p.stock is not None and qty > p.stock:
            return ChatResponse(answer=f"Вы запросили {qty:g}, но по данным API доступно {p.stock:g}. Укажите количество не больше остатка.", products=[p])

        pending_action = create_pending(req.session_id, p, qty)
        return ChatResponse(
            answer=f"Нашёл «{p.name}». Добавить {qty:g} в корзину? Корзина изменится только после вашего подтверждения.",
            products=[p],
            confirmation_required=True,
            pending=PendingItem(pending_id=pending_action.pending_id, product=p, quantity=qty),
        )

    answer = await llm_answer(text, products, req.attachment_ids)
    return ChatResponse(answer=answer, products=products)
