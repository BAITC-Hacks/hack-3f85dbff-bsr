from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Iterable

import httpx
from rapidfuzz import fuzz

from .config import settings
from .models import Product


PRODUCT_LIST_KEYS = ("products", "items", "results", "data", "rows", "list")
ID_KEYS = ("id", "product_id", "productId", "ID", "ID_TOVAR", "uid")
NAME_KEYS = ("name", "title", "product_name", "productName", "NAME", "NAME_TOVAR", "naimenovanie")
SKU_KEYS = ("sku", "article", "articul", "vendor_code", "vendorCode", "code", "CODE", "art")
CATEGORY_KEYS = ("category", "category_name", "categoryName", "section", "section_name", "group")
PRICE_KEYS = ("price", "PRICE", "base_price", "basePrice", "retail_price", "cost")
STOCK_KEYS = ("stock", "quantity", "qty", "balance", "available", "availability", "ostatok", "rest", "amount")
CERT_KEYS = ("certificate", "certificate_url", "certificateUrl", "cert", "sertifikat")
URL_KEYS = ("url", "detail_url", "detailUrl", "link", "href")
PROPS_KEYS = ("properties", "characteristics", "specifications", "props", "features", "params")

# Слова, которые описывают намерение пользователя, а не сам товар.
QUERY_STOPWORDS = {
    "есть", "ли", "у", "вас", "мне", "нужен", "нужна", "нужно", "нужны",
    "покажи", "показать", "найди", "найти", "ищу", "хочу", "дайте", "дай",
    "товар", "товары", "цена", "стоимость", "сколько", "наличие", "наличии",
    "добавь", "добавить", "корзину", "корзина", "купить", "заказать",
    "аналог", "аналоги", "аналогичный", "замена", "замену",
    "бар", "ма", "керек", "тауар", "тауарды", "көрсет", "тап", "бағасы",
}


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _pick_recursive(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    lowered = {k.lower(): k for k in keys}
    for d in _walk_dicts(data):
        for key, value in d.items():
            if key in keys or key.lower() in lowered:
                if value not in (None, "", [], {}):
                    return value
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace("\u00a0", " ").replace("₸", "").replace("тг", "").strip()
        cleaned = cleaned.replace(" ", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _extract_stock(raw: dict[str, Any]) -> tuple[float | None, str | None]:
    value = _pick_recursive(raw, STOCK_KEYS)
    if value is None:
        return None, None
    if isinstance(value, list):
        nums = []
        for item in value:
            if isinstance(item, dict):
                n = _as_float(_pick_recursive(item, STOCK_KEYS))
                if n is not None:
                    nums.append(n)
        if nums:
            return sum(nums), f"{sum(nums):g}"
        return None, str(value)[:200]
    if isinstance(value, dict):
        nums = []
        for v in value.values():
            n = _as_float(v)
            if n is not None:
                nums.append(n)
        if nums:
            return sum(nums), f"{sum(nums):g}"
        return None, str(value)[:200]
    n = _as_float(value)
    return n, str(value)


def _extract_properties(raw: dict[str, Any]) -> dict[str, Any]:
    props = _pick_recursive(raw, PROPS_KEYS)
    if isinstance(props, dict):
        return props
    if isinstance(props, list):
        out: dict[str, Any] = {}
        for item in props:
            if not isinstance(item, dict):
                continue
            key = item.get("name") or item.get("title") or item.get("key") or item.get("code")
            val = item.get("value") or item.get("val") or item.get("text")
            if key and val not in (None, ""):
                out[str(key)] = val
        return out
    return {}


def normalize_product(raw: dict[str, Any]) -> Product:
    product_id = _pick_recursive(raw, ID_KEYS)
    name = _pick_recursive(raw, NAME_KEYS)
    sku = _pick_recursive(raw, SKU_KEYS)
    category = _pick_recursive(raw, CATEGORY_KEYS)
    price = _as_float(_pick_recursive(raw, PRICE_KEYS))
    stock, stock_text = _extract_stock(raw)
    certificate = _pick_recursive(raw, CERT_KEYS)
    url = _pick_recursive(raw, URL_KEYS)

    if not name:
        name = str(sku or product_id or "Товар")
    if product_id is None:
        product_id = str(sku or name)

    return Product(
        id=str(product_id),
        name=str(name),
        sku=str(sku) if sku is not None else None,
        category=str(category) if category is not None else None,
        price=price,
        stock=stock,
        stock_text=stock_text,
        certificate=str(certificate) if certificate else None,
        url=str(url) if url else None,
        properties=_extract_properties(raw),
        raw=raw,
    )


def extract_product_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []

    for key in PRODUCT_LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            nested = extract_product_list(value)
            if nested:
                return nested

    for value in payload.values():
        if isinstance(value, list) and value and all(isinstance(x, dict) for x in value[:3]):
            return value
    return []


def _normalize_text(text: str) -> str:
    """Нормализует 3×2,5 / 3х2.5 / 3 x 2,5 в один вид: 3x2.5."""
    text = text.lower().replace("ё", "е")
    text = text.replace("×", "x").replace("х", "x").replace("Х", "x").replace("*", "x")
    text = re.sub(r"(?<=\d),(?=\d)", ".", text)
    text = re.sub(r"\s*x\s*", "x", text)
    text = re.sub(r"[^a-zа-я0-9._+\-/x]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _query_terms(query: str) -> tuple[str, list[str], list[str]]:
    normalized = _normalize_text(query)
    tokens = re.findall(r"[a-zа-я][a-zа-я0-9._+\-/]*|\d+(?:\.\d+)?(?:x\d+(?:\.\d+)?)?", normalized)
    tokens = [t for t in tokens if t not in QUERY_STOPWORDS and len(t) > 1]

    # Текстовые якоря: ВВГ, Legrand, DRX125, кабель и т.п.
    anchors = [t for t in tokens if re.search(r"[a-zа-я]", t) and t not in {"шт", "метр", "метра", "метров"}]
    # Спецификации: 3x2.5, 40a, 0.66 и т.п.
    specs = [t for t in tokens if re.search(r"\d", t)]
    return normalized, anchors, specs


def _term_matches(term: str, haystack: str, hay_tokens: list[str]) -> bool:
    if term in haystack:
        return True
    # Позволяет "ввг" совпасть с "ввгнг", но не с совершенно другим словом.
    if len(term) >= 3 and any(tok.startswith(term) or term.startswith(tok) for tok in hay_tokens if len(tok) >= 3):
        return True
    return False


def _product_search_score(query: str, product: Product) -> float | None:
    qnorm, anchors, specs = _query_terms(query)
    if not qnorm:
        return None

    prop_text = " ".join(f"{k} {v}" for k, v in list(product.properties.items())[:20])
    raw_haystack = " ".join(filter(None, [product.name, product.sku, product.category, prop_text]))
    haystack = _normalize_text(raw_haystack)
    hay_tokens = re.findall(r"[a-zа-я][a-zа-я0-9._+\-/]*|\d+(?:\.\d+)?(?:x\d+(?:\.\d+)?)?", haystack)

    compact_q = re.sub(r"\s+", "", qnorm)
    compact_h = re.sub(r"\s+", "", haystack)

    # Точный ID/SKU — максимальный приоритет.
    # Числовой ID считаем точным совпадением только если пользователь действительно
    # ввёл длинный идентификатор, а не цифру из характеристики вроде 3x2.5.
    id_candidates = re.findall(r"(?<!\d)\d{5,12}(?!\d)", qnorm)
    if product.id and product.id.lower() in id_candidates:
        return 1000.0
    if product.sku:
        sku = _normalize_text(product.sku).replace(" ", "")
        if sku and sku in compact_q:
            return 950.0

    matched_anchors = [a for a in anchors if _term_matches(a, haystack, hay_tokens)]

    # Главный фильтр против случайных результатов:
    # если пользователь написал товарное слово (например, ВВГ), кандидат обязан
    # совпасть хотя бы по одному такому якорю.
    if anchors and not matched_anchors:
        return None

    matched_specs = [s for s in specs if s in compact_h or s in haystack]

    # Для запросов только из чисел/параметров требуем хотя бы одну спецификацию.
    if not anchors and specs and not matched_specs:
        return None

    score = 0.0
    score += 85.0 * len(matched_anchors)
    score += 30.0 * len(matched_specs)

    # Бонус за точную фразу и за общее fuzzy-сходство, но fuzzy сам по себе
    # больше не может протащить нерелевантный товар.
    if qnorm in haystack:
        score += 120.0
    score += fuzz.token_set_ratio(qnorm, haystack) * 0.35
    score += fuzz.WRatio(qnorm, haystack) * 0.20

    # Если запрос содержит несколько якорей, вознаграждаем покрытие.
    if anchors:
        coverage = len(matched_anchors) / len(anchors)
        score += coverage * 80.0

    return score


def _analog_score(source: Product, candidate: Product) -> float | None:
    if candidate.id == source.id:
        return None

    src = _normalize_text(" ".join(filter(None, [source.name, source.category])))
    dst = _normalize_text(" ".join(filter(None, [candidate.name, candidate.category])))
    src_tokens = [t for t in src.split() if len(t) >= 3]

    same_category = bool(
        source.category
        and candidate.category
        and _normalize_text(source.category) == _normalize_text(candidate.category)
    )
    family_match = any(_term_matches(t, dst, dst.split()) for t in src_tokens[:8])

    # Не предлагаем совершенно другой тип товара только из-за fuzzy-сходства.
    if not same_category and not family_match:
        return None

    score = float(fuzz.token_set_ratio(src, dst))
    if same_category:
        score += 45.0
    if family_match:
        score += 30.0
    if candidate.stock is not None and candidate.stock > 0:
        score += 10.0
    return score


class EKTClient:
    def __init__(self) -> None:
        self._cache: list[Product] = []
        self._cache_at = 0.0
        self._lock = asyncio.Lock()

    def _auth(self) -> httpx.BasicAuth:
        if not settings.ekt_api_user or not settings.ekt_api_password:
            raise RuntimeError("EKT_API_USER/EKT_API_PASSWORD не настроены в .env")
        return httpx.BasicAuth(settings.ekt_api_user, settings.ekt_api_password)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        base = settings.ekt_api_base.strip().rstrip("/")
        url = f"{base}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(
                timeout=settings.request_timeout_seconds,
                follow_redirects=True,
                trust_env=False,
            ) as client:
                response = await client.get(url, params=params, auth=self._auth())
        except httpx.InvalidURL as exc:
            raise RuntimeError(f"Некорректный адрес EKT API: {url!r}: {exc!r}") from exc
        except httpx.ConnectTimeout as exc:
            raise RuntimeError(f"Таймаут подключения к {url}: {exc!r}") from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"EKT API не ответил за {settings.request_timeout_seconds:g} с: {exc!r}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Сетевая ошибка при запросе {url}: {type(exc).__name__}: {exc!r}") from exc

        if response.status_code >= 400:
            body = response.text[:500].replace("\r", " ").replace("\n", " ").strip()
            if response.status_code == 401:
                hint = "Basic Auth не принят: проверьте EKT_API_USER и EKT_API_PASSWORD."
            elif response.status_code == 403:
                hint = "Доступ запрещён сервером EKT (403)."
            else:
                hint = "EKT API вернул ошибку."
            raise RuntimeError(f"{hint} HTTP {response.status_code} для {response.url}. Ответ: {body or '<пустой>'}")

        try:
            return response.json()
        except ValueError as exc:
            body = response.text[:500].replace("\r", " ").replace("\n", " ").strip()
            ctype = response.headers.get("content-type", "не указан")
            raise RuntimeError(
                f"EKT API вернул не JSON (Content-Type: {ctype}) для {response.url}. Начало ответа: {body or '<пустой>'}"
            ) from exc

    async def get_page(self, page: int = 1) -> list[Product]:
        payload = await self._get("products", {"page": page})
        return [normalize_product(x) for x in extract_product_list(payload)]

    async def get_detail(self, product_id: str) -> Product:
        payload = await self._get("products/detail", {"id": product_id})
        if isinstance(payload, dict):
            candidate = None
            for key in ("product", "item", "data", "result"):
                if isinstance(payload.get(key), dict):
                    candidate = payload[key]
                    break
            raw = candidate or payload
        else:
            raise RuntimeError("Неожиданный формат detail API")
        return normalize_product(raw)

    async def catalog(self, force: bool = False) -> list[Product]:
        now = time.monotonic()
        if not force and self._cache and now - self._cache_at < settings.catalog_cache_seconds:
            return self._cache

        async with self._lock:
            now = time.monotonic()
            if not force and self._cache and now - self._cache_at < settings.catalog_cache_seconds:
                return self._cache

            products: list[Product] = []
            seen: set[str] = set()
            for page in range(1, settings.catalog_max_pages + 1):
                page_items = await self.get_page(page)
                if not page_items:
                    break
                new_count = 0
                for product in page_items:
                    if product.id in seen:
                        continue
                    seen.add(product.id)
                    products.append(product)
                    new_count += 1
                # Если API начал повторять ту же страницу, не зацикливаемся.
                if new_count == 0:
                    break
            self._cache = products
            self._cache_at = time.monotonic()
            return products

    async def search(self, query: str, limit: int = 5) -> list[Product]:
        query = query.strip()
        if not query:
            return []

        products = await self.catalog()
        scored: list[tuple[float, Product]] = []
        for product in products:
            score = _product_search_score(query, product)
            if score is not None:
                scored.append((score, product))

        scored.sort(key=lambda item: item[0], reverse=True)
        if not scored:
            return []

        # Не показываем слабые совпадения. При наличии сильного результата также
        # отсекаем кандидатов, заметно хуже лидера.
        best = scored[0][0]
        threshold = max(70.0, best * 0.48)
        return [p for score, p in scored if score >= threshold][:limit]

    async def analogs(self, source: Product, limit: int = 3) -> list[Product]:
        products = await self.catalog()
        scored: list[tuple[float, Product]] = []
        for product in products:
            score = _analog_score(source, product)
            if score is not None:
                scored.append((score, product))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [p for score, p in scored[:limit] if score >= 55.0]


ekt = EKTClient()
