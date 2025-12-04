"""Торговый сценарий ATAIX Eurasia для лабораторной работы №08.

Скрипт поддерживает два режима:

1. **Автоматический** — повторяет шаги из задания: проверяет баланс, ищет лучшую
	цену, выставляет ордера на покупку на 2 %, 5 % и 8 % ниже и создает связанные
	продажи после исполнения.
2. **Интерактивный** — ориентирован на пару LTC/USDT: после вывода текущего
	баланса и лучших цен предлагает меню с действиями: создать покупку на 2 %, 4 %
	или 6 % ниже лучшей цены, а также отменить ордер.

Для реальных запросов нужны ключи ATAIX. Перед запуском выставьте `ATAIX_API_KEY`
и `ATAIX_API_SECRET` в окружении. Флаг `--dry-run` позволяет протестировать логику
без обращений к API.
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


BASE_URL = "https://api.ataix.kz/api"
ORDER_FILE_DEFAULT = "orders.json"
USDT = "USDT"
DEFAULT_SYMBOL = "LTCUSDT"
MAX_SYMBOL_PRICE = Decimal("0.6")
AUTO_BUY_DISCOUNTS = (
	Decimal("0.02"),
	Decimal("0.05"),
	Decimal("0.08"),
)
INTERACTIVE_DISCOUNTS = (
	Decimal("0.02"),
	Decimal("0.04"),
	Decimal("0.06"),
)
SELL_MARKUP = Decimal("0.02")
DECIMAL_STEP = Decimal("0.00000001")

_symbol_format_candidates: List[str] = []
env_symbol_format = os.environ.get("ATAIX_SYMBOL_FORMAT")
if env_symbol_format:
	_symbol_format_candidates.append(env_symbol_format.lower())
_symbol_format_candidates.extend(["dash", "slash", "upper", "lower"])
SYMBOL_FORMATS: List[str] = []
for candidate in _symbol_format_candidates:
	if candidate not in ("dash", "slash", "upper", "lower"):
		continue
	if candidate not in SYMBOL_FORMATS:
		SYMBOL_FORMATS.append(candidate)
if not SYMBOL_FORMATS:
	SYMBOL_FORMATS.append("dash")


_order_size_fields = []
env_order_field = os.environ.get("ATAIX_ORDER_SIZE_FIELD")
if env_order_field:
	_order_size_fields.append(env_order_field.strip())
_order_size_fields.extend(["quantity", "amount", "volume"])
ORDER_SIZE_FIELDS = []
for field in _order_size_fields:
	if field and field not in ORDER_SIZE_FIELDS:
		ORDER_SIZE_FIELDS.append(field)
if not ORDER_SIZE_FIELDS:
	ORDER_SIZE_FIELDS.append("quantity")


class AtaixAPIError(RuntimeError):
	"""Исключение, когда ATAIX возвращает ошибку."""


def decimal_argument(value: str) -> Decimal:
	"""Преобразует аргументы CLI в Decimal с проверкой."""

	try:
		return Decimal(value)
	except (InvalidOperation, ValueError) as exc:  # pragma: no cover - защитная проверка
		raise argparse.ArgumentTypeError(f"Cannot convert {value!r} to Decimal") from exc


def iso_now() -> str:
	"""Возвращает текущее UTC время в формате ISO 8601."""

	return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def quantize(value: Decimal) -> Decimal:
	"""Нормализует Decimal до точности биржи."""

	return value.quantize(DECIMAL_STEP, rounding=ROUND_DOWN)


def load_orders(path: Path) -> List[Dict[str, Any]]:
	"""Читает сохраненные ордера из JSON-файла."""

	if not path.exists():
		return []
	try:
		raw = path.read_text(encoding="utf-8")
		if not raw.strip():
			return []
		data = json.loads(raw)
		return data.get("orders", []) if isinstance(data, dict) else []
	except json.JSONDecodeError as exc:  # pragma: no cover - защитная проверка
		raise RuntimeError(f"Cannot parse {path}: {exc}") from exc


def save_orders(path: Path, orders: List[Dict[str, Any]]) -> None:
	"""Сохраняет список ордеров на диск."""

	payload = {"orders": orders}
	path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


@dataclass
class OrderRecord:
	"""Сериализуемое представление ордера ATAIX."""

	order_id: str
	symbol: str
	side: str
	amount: str
	price: str
	status: str
	created_at: str
	note: Optional[str] = None
	linked_order_id: Optional[str] = None

	def as_dict(self) -> Dict[str, Any]:
		return asdict(self)


class AtaixClient:
	"""Минимальный REST-клиент ATAIX с аутентификацией."""

	def __init__(
		self,
		api_key: Optional[str],
		api_secret: Optional[str],
		*,
		base_url: str = BASE_URL,
		dry_run: bool = False,
	) -> None:
		self.base_url = base_url.rstrip("/")
		self.session = requests.Session()
		self.session.headers.update(
			{
				"Accept": "application/json",
				"Content-Type": "application/json",
			}
		)
		if api_key:
			self.session.headers["X-API-KEY"] = api_key
		if api_secret:
			self.session.headers["X-API-SECRET"] = api_secret
		self.dry_run = dry_run
		self._dry_run_orders: Dict[str, Dict[str, Any]] = {}
		self._symbol_cache: Dict[str, Dict[str, str]] = {}

	@classmethod
	def from_env(cls, *, dry_run: bool = False) -> "AtaixClient":
		"""Создает клиент, считывая ключи из переменных окружения."""

		key = "Pr2kA2C0c3iFpKseqPWKSSbXCu90puUZALxayzOD2NOIwNliWSZQFBPiy3okY9h9nWPGKshJcQh0XFep6S3o8B"
		secret = os.environ.get("ATAIX_API_SECRET")
		if not dry_run and not key:
			raise RuntimeError(
				"ATAIX_API_KEY must be set (ATAIX_API_SECRET опционально) или запускайте с --dry-run"
			)
		return cls(key, secret, dry_run=dry_run)

	def get_available_balance(self, currency: str) -> Decimal:
		"""Возвращает доступный баланс указанной валюты."""

		currency = currency.upper()
		if self.dry_run:
			return Decimal("1000")
		payload = self._request("GET", f"/user/balances/{currency}")
		available = None
		if isinstance(payload, dict):
			for key in ("available", "balance", "amount"):
				if key in payload:
					available = payload[key]
					break
		if available is None:
			raise AtaixAPIError(f"Balance payload missing 'available': {payload}")
		return Decimal(str(available))

	def get_highest_bid(self, symbol: str) -> Decimal:
		"""Возвращает максимальную цену покупки для символа."""

		symbol = symbol.upper()
		if self.dry_run:
			return Decimal("0.5")
		entries = self._get_symbol_price_entries(symbol)
		price_candidates: List[Decimal] = []
		for entry in entries:
			bid_value = entry.get("bid") or entry.get("buy") or entry.get("highestBid")
			if bid_value is not None:
				price_candidates.append(Decimal(str(bid_value)))
		if not price_candidates:
			raise AtaixAPIError(f"Cannot determine highest bid for {symbol}")
		return max(price_candidates)

	def get_lowest_ask(self, symbol: str) -> Decimal:
		"""Возвращает минимальную цену продажи для символа."""

		symbol = symbol.upper()
		if self.dry_run:
			return Decimal("0.51")
		entries = self._get_symbol_price_entries(symbol)
		price_candidates: List[Decimal] = []
		for entry in entries:
			ask_value = entry.get("ask") or entry.get("sell") or entry.get("lowestAsk")
			if ask_value is not None:
				price_candidates.append(Decimal(str(ask_value)))
		if not price_candidates:
			raise AtaixAPIError(f"Cannot determine lowest ask for {symbol}")
		return min(price_candidates)

	def create_limit_order(
		self,
		*,
		symbol: str,
		side: str,
		amount: Decimal,
		price: Decimal,
	) -> Dict[str, Any]:
		"""Размещает лимитный ордер и возвращает ответ ATAIX."""

		symbol = symbol.upper()
		side = side.lower()
		amount = quantize(amount)
		price = quantize(price)
		if self.dry_run:
			order_id = f"dry-{uuid.uuid4().hex}"
			order = {
				"orderId": order_id,
				"symbol": symbol,
				"side": side,
				"amount": str(amount),
				"price": str(price),
				"status": "NEW",
			}
			self._dry_run_orders[order_id] = order.copy()
			return order
		response: Optional[Dict[str, Any]] = None
		last_error: Optional[AtaixAPIError] = None
		success = False
		for fmt in SYMBOL_FORMATS:
			formatted_symbol = self._format_symbol(symbol, fmt)
			for idx, size_field in enumerate(ORDER_SIZE_FIELDS):
				payload = {
					"symbol": formatted_symbol,
					"side": side,
					"type": "limit",
					"price": str(price),
				}
				payload[size_field] = str(amount)
				try:
					response = self._request("POST", "/orders", json=payload)
					success = True
					break
				except AtaixAPIError as exc:
					last_error = exc
					error_text = str(exc)
					if "Unexpected parameter" in error_text and idx < len(ORDER_SIZE_FIELDS) - 1:
						continue
					if "Invalid symbol" in error_text and fmt != SYMBOL_FORMATS[-1]:
						break
					raise
			if success:
				break
		if response is None and last_error:
			raise last_error
		if response is None:
			raise AtaixAPIError("Failed to place order: unknown error")
		if not isinstance(response, dict):
			response = {"result": response}
		if not response.get("orderId"):
			alt_id = response.get("orderID") or response.get("id")
			if alt_id:
				response["orderId"] = alt_id
		if not response.get("orderId"):
			raise AtaixAPIError(f"Order response lacks ID: {response}")
		response.setdefault("status", "NEW")
		return response

	def get_order_status(self, order_id: str) -> str:
		"""Запрашивает актуальный статус ордера."""

		if self.dry_run:
			state = self._dry_run_orders.get(order_id)
			return state.get("status", "UNKNOWN") if state else "UNKNOWN"
		response = self._request("GET", f"/orders/{order_id}")
		envelope = response if isinstance(response, dict) else {}
		details = envelope.get("result", envelope)
		if isinstance(details, dict):
			for key in ("orderStatus", "status", "state"):
				value = details.get(key)
				if isinstance(value, str):
					return value.upper()
		raise AtaixAPIError(f"Failed to read status for order {order_id}: {response}")

	def cancel_order(self, order_id: str) -> Dict[str, Any]:
		"""Отменяет ордер на бирже."""

		if self.dry_run:
			order = self._dry_run_orders.get(order_id)
			if order:
				order["status"] = "CANCELED"
				status = order["status"]
			else:
				status = "UNKNOWN"
			return {"orderId": order_id, "status": status}
		response = self._request("DELETE", f"/orders/{order_id}")
		return response if isinstance(response, dict) else {"orderId": order_id, "status": "CANCELED"}

	def _request(self, method: str, path: str, **kwargs: Any) -> Any:
		"""Выполняет HTTP-запрос и распаковывает ответ ATAIX."""

		url = f"{self.base_url}{path}"
		response = self.session.request(method, url, timeout=20, **kwargs)
		response.raise_for_status()
		payload = response.json()
		if isinstance(payload, dict) and payload.get("status") is False:
			message = payload.get("message") or payload
			raise AtaixAPIError(f"ATAIX rejected the request: {message}")
		return payload.get("result", payload) if isinstance(payload, dict) else payload

	@staticmethod
	def _iter_symbol_entries(payload: Any) -> List[Dict[str, Any]]:
		"""Преобразует ответ с ценами в список словарей."""

		if isinstance(payload, dict):
			entries = payload.get("result", payload)
			if isinstance(entries, list):
				return [item for item in entries if isinstance(item, dict)]
			if isinstance(entries, dict):
				return [entries]
		if isinstance(payload, list):
			return [item for item in payload if isinstance(item, dict)]
		return []

	def _get_symbol_price_entries(self, symbol: str) -> List[Dict[str, Any]]:
		"""Фильтрует ценовые данные по нужной паре без передачи лишних параметров."""

		target = self._normalize_symbol(symbol)
		payload = self._request("GET", "/prices")
		entries = []
		for entry in self._iter_symbol_entries(payload):
			candidate_names = [
				entry.get("symbol"),
				entry.get("symbolCode"),
				f"{entry.get('baseCurrency', '')}{entry.get('quoteCurrency', '')}",
			]
			for name in candidate_names:
				if isinstance(name, str) and self._normalize_symbol(name) == target:
					entries.append(entry)
					self._remember_symbol(entry)
					break
		return entries

	def _remember_symbol(self, entry: Dict[str, Any]) -> None:
		name = entry.get("symbol") or entry.get("symbolCode") or ""
		normalized = self._normalize_symbol(name)
		if not normalized:
			return
		base = entry.get("baseCurrency") or entry.get("baseCurrencyCode")
		quote = entry.get("quoteCurrency") or entry.get("quoteCurrencyCode")
		if (not base or not quote) and isinstance(name, str):
			clean = name.replace("-", "/").replace("_", "/")
			if "/" in clean:
				parts = clean.split("/")
				if len(parts) == 2:
					base = base or parts[0]
					quote = quote or parts[1]
		self._symbol_cache[normalized] = {
			"base": (base or "").upper(),
			"quote": (quote or "").upper(),
			"raw": name,
		}

	@staticmethod
	def _normalize_symbol(name: str) -> str:
		return "".join(ch for ch in name.upper() if ch.isalnum())

	def _format_symbol(self, symbol: str, fmt: str) -> str:
		normalized = self._normalize_symbol(symbol)
		info = self._symbol_cache.get(normalized)
		base = info.get("base") if info else None
		quote = info.get("quote") if info else None
		if not base or not quote:
			clean = normalized
			# fallback assumes quote is last 4 chars (USDT or KZT etc.)
			quote = quote or clean[-4:]
			base = base or clean[:-4]
		if fmt == "upper":
			return f"{base}{quote}"
		if fmt == "lower":
			return f"{base}{quote}".lower()
		if fmt == "slash":
			return f"{base}/{quote}"
		return f"{base}-{quote}"


class TradingWorkflow:
	"""Оркеструет шаги лабораторной работы для выбранного символа."""

	def __init__(
		self,
		client: AtaixClient,
		*,
		symbol: str,
		amount: Optional[Decimal],
		order_file: Path,
	) -> None:
		self.client = client
		self.symbol = symbol.upper()
		self.amount = amount
		self.order_file = order_file

	def run_auto(self) -> None:
		"""Запускает ранее описанный автоматический сценарий."""

		if self.amount is None:
			raise RuntimeError("Для автоматического режима укажите --amount")

		available = self.client.get_available_balance(USDT)
		print(f"Available {USDT}: {available}")

		best_bid = self.client.get_highest_bid(self.symbol)
		print(f"Highest bid for {self.symbol}: {best_bid}")

		if best_bid >= MAX_SYMBOL_PRICE:
			raise RuntimeError(
				f"The asset price {best_bid} exceeds the 0.6 {USDT} constraint."
			)

		required = sum(
			self._discount_price(best_bid, d) * self.amount for d in AUTO_BUY_DISCOUNTS
		)
		if available < required:
			raise RuntimeError(
				f"Not enough {USDT} balance ({available}) to cover {required} required."
			)

		new_orders = self._place_buy_orders(
			reference_price=best_bid,
			amount=self.amount,
			discounts=AUTO_BUY_DISCOUNTS,
		)
		self._append_records(new_orders)
		if new_orders:
			print(f"Stored {len(new_orders)} buy orders in {self.order_file}")

		self._sync_orders()

	def interactive_menu(self) -> None:
		"""Запускает интерактивное меню для пары LTC/USDT."""

		print(
			"Интерактивный режим: пара {symbol}. Введите q для выхода.".format(
				symbol=self.symbol
			)
		)
		while True:
			available = self.client.get_available_balance(USDT)
			best_bid = self.client.get_highest_bid(self.symbol)
			best_ask = self.client.get_lowest_ask(self.symbol)
			print(
				f"\nБаланс {USDT}: {available} | Лучшая покупка: {best_bid} | "
				f"Лучшая продажа: {best_ask}"
			)
			self._print_local_orders()
			print(
				"1 - Покупка на 2% ниже\n"
				"2 - Покупка на 4% ниже\n"
				"3 - Покупка на 6% ниже\n"
				"4 - Отменить ордер\n"
				"q - Выход"
			)
			choice = input("Выберите действие [1-4, q]: ").strip().lower()
			if choice == "q":
				break
			if choice in {"1", "2", "3"}:
				index = int(choice) - 1
				discount = INTERACTIVE_DISCOUNTS[index]
				amount = self._prompt_amount()
				if amount is None:
					print("Действие отменено пользователем.")
					continue
					records = self._place_buy_orders(
						reference_price=best_bid,
						amount=amount,
						discounts=(discount,),
					)
					self._append_records(records)
					self._sync_orders()
			elif choice == "4":
				order_id = input("Введите ID ордера для отмены: ").strip()
				if order_id:
					self._cancel_and_update(order_id)
				else:
					print("ID не введен, отмена действия.")
			else:
				print("Неизвестная команда, попробуйте снова.")

	def _place_buy_orders(
		self,
		*,
		reference_price: Decimal,
		amount: Decimal,
		discounts: tuple[Decimal, ...],
	) -> List[Dict[str, Any]]:
		"""Создает покупочные ордера по списку скидок."""

		records: List[Dict[str, Any]] = []
		for discount in discounts:
			target_price = self._discount_price(reference_price, discount)
			response = self.client.create_limit_order(
				symbol=self.symbol,
				side="buy",
				amount=amount,
				price=target_price,
			)
			order_record = OrderRecord(
				order_id=self._extract_order_id(response),
				symbol=self.symbol,
				side="buy",
				amount=str(quantize(amount)),
				price=str(target_price),
				status=str(response.get("status", "NEW")).upper(),
				created_at=iso_now(),
				note=f"Buy order {discount * Decimal(100)}% below best bid",
			)
			records.append(order_record.as_dict())
			print(
				f"Created buy order {order_record.order_id} at {order_record.price} "
				f"({discount * Decimal(100)}% discount)"
			)
		return records

	def _print_local_orders(self) -> None:
		orders = load_orders(self.order_file)
		if not orders:
			print("Локальных ордеров пока нет.")
			return
		print("Последние ордера:")
		for entry in orders[-5:]:
			print(
				f" - {entry['order_id']} | {entry['side']} | {entry['status']} | "
				f"цена {entry['price']} | связь {entry.get('linked_order_id', '-')}"
			)

	def _append_records(self, records: List[Dict[str, Any]]) -> None:
		if not records:
			return
		orders = load_orders(self.order_file)
		orders.extend(records)
		save_orders(self.order_file, orders)

	def _cancel_and_update(self, order_id: str) -> None:
		try:
			response = self.client.cancel_order(order_id)
			status = str(response.get("status", "CANCELED")).upper()
		except (AtaixAPIError, requests.HTTPError) as exc:
			print(f"Не удалось отменить ордер: {exc}")
			return
		orders = load_orders(self.order_file)
		updated = False
		for entry in orders:
			if entry["order_id"] == order_id:
				entry["status"] = status
				updated = True
		if updated:
			save_orders(self.order_file, orders)
			print(f"Статус ордера {order_id} обновлен до {status}.")
		else:
			print("Ордер отменен на бирже, но его не оказалось в локальном списке.")

	def _sync_orders(self) -> None:
		"""Обновляет статусы и выставляет продажи для исполненных покупок."""

		orders = load_orders(self.order_file)
		if not orders:
			print("No orders to sync yet.")
			return

		changed = False
		sell_records: List[Dict[str, Any]] = []
		for entry in orders:
			status = self.client.get_order_status(entry["order_id"]).upper()
			if status != entry.get("status"):
				entry["status"] = status
				changed = True
				print(f"Order {entry['order_id']} new status: {status}")

			if (
				entry["side"].lower() == "buy"
				and status == "FILLED"
				and not entry.get("linked_order_id")
			):
				sell_price = self._markup_price(Decimal(entry["price"]), SELL_MARKUP)
				response = self.client.create_limit_order(
					symbol=entry["symbol"],
					side="sell",
					amount=Decimal(entry["amount"]),
					price=sell_price,
				)
				sell_record = OrderRecord(
					order_id=self._extract_order_id(response),
					symbol=entry["symbol"],
					side="sell",
					amount=str(quantize(Decimal(entry["amount"]))),
					price=str(sell_price),
					status=str(response.get("status", "NEW")).upper(),
					created_at=iso_now(),
					note=f"Sell order +{SELL_MARKUP * Decimal(100)}% over buy {entry['order_id']}",
					linked_order_id=entry["order_id"],
				)
				entry["linked_order_id"] = sell_record.order_id
				sell_records.append(sell_record.as_dict())
				print(
					f"Created linked sell order {sell_record.order_id} for buy {entry['order_id']}"
				)
				changed = True

		if sell_records:
			orders.extend(sell_records)
		if changed:
			save_orders(self.order_file, orders)
			print(f"Updated {self.order_file} with refreshed statuses.")

	@staticmethod
	def _discount_price(reference: Decimal, discount: Decimal) -> Decimal:
		return quantize(reference * (Decimal(1) - discount))

	@staticmethod
	def _markup_price(reference: Decimal, markup: Decimal) -> Decimal:
		return quantize(reference * (Decimal(1) + markup))

	@staticmethod
	def _extract_order_id(payload: Dict[str, Any]) -> str:
		for key in ("orderId", "orderID", "id", "order_id"):
			if payload.get(key):
				return str(payload[key])
		raise AtaixAPIError(f"Cannot find order ID in payload: {payload}")

	@staticmethod
	def _prompt_amount() -> Optional[Decimal]:
		while True:
			raw = input("Введите количество монет (пусто — отмена): ").strip()
			if not raw:
				return None
			try:
				value = Decimal(raw)
			except InvalidOperation:
				print("Не удалось распознать число, попробуйте снова.")
				continue
			if value <= 0:
				print("Количество должно быть больше нуля.")
				continue
			return quantize(value)


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="ATAIX Lab 08 trading assistant")
	parser.add_argument(
		"--symbol",
		default=DEFAULT_SYMBOL,
		help="Торговая пара (по умолчанию LTCUSDT)",
	)
	parser.add_argument(
		"--amount",
		type=decimal_argument,
		help="Количество актива для автоматического режима",
	)
	parser.add_argument(
		"--order-file",
		default=ORDER_FILE_DEFAULT,
		help="Path to the JSON file that stores order history",
	)
	parser.add_argument(
		"--dry-run",
		action="store_true",
		help="Skip real HTTP requests and simulate everything locally",
	)
	parser.add_argument(
		"--auto",
		action="store_true",
		help="Запустить автоматический сценарий (по умолчанию меню)",
	)
	return parser


def main() -> None:
	parser = build_parser()
	args = parser.parse_args()
	client = AtaixClient.from_env(dry_run=args.dry_run)
	workflow = TradingWorkflow(
		client,
		symbol=args.symbol,
		amount=args.amount,
		order_file=Path(args.order_file),
	)
	if args.auto:
		workflow.run_auto()
	else:
		workflow.interactive_menu()


if __name__ == "__main__":
	main()
