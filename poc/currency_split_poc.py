import datetime
import json
import urllib.request
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Tuple


def get_cbr_rate(currency_code: str, target_date: datetime.date) -> Tuple[Decimal, str]:
    """
    Получает официальный курс валюты ЦБ РФ на указанную дату.
    Если на дату торгов не было (выходной/праздник), откатывается назад до 7 дней (FR-4.3).
    """
    if currency_code == "RUB":
        return Decimal("1.0"), target_date.isoformat()

    for days_back in range(7):
        check_date = target_date - datetime.timedelta(days=days_back)
        url = f"https://cbr-xml-daily.ru{check_date.strftime('%Y/%m/%d')}/daily_json.js"
        try:
            req = urllib.request.urlopen(url, timeout=5)
            data = json.loads(req.read().decode("utf-8"))
            valute = data["Valute"][currency_code]
            rate = Decimal(str(valute["Value"])) / Decimal(str(valute["Nominal"]))
            return rate, check_date.isoformat()
        except Exception:
            continue

    raise RuntimeError(f"Не удалось получить курс {currency_code} за период от {target_date}")


def split_amount_exact(
    total_rub: Decimal, consumers: List[str], payer: str
) -> Dict[str, Decimal]:
    """
    Делит сумму в рублях на N потребителей с точностью до 1 копейки (FR-3.3).
    Реализует правило Tie-breaking: при равных дробных частях плательщик
    получает лишнюю копейку в последнюю очередь.
    """
    n = len(consumers)
    if n == 0:
        return {}

    total_kopecks = int((total_rub * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    base_kopecks = total_kopecks // n
    remainder = total_kopecks % n

    # Сортируем потребителей так, чтобы плательщик стоял в самом конце списка
    ordered_consumers = [c for c in consumers if c != payer] + (
        [payer] if payer in consumers else []
    )

    shares: Dict[str, Decimal] = {}
    for idx, person in enumerate(ordered_consumers):
        extra = 1 if idx < remainder else 0
        shares[person] = Decimal(base_kopecks + extra) / Decimal("100")

    return shares


def simplify_debts(net_balances: Dict[str, Decimal]) -> List[Tuple[str, str, Decimal]]:
    """
    Оптимизирует граф долгов, минимизируя количество переводов (FR-5.3).
    Возвращает список кортежей: (Отправитель, Получатель, Сумма).
    """
    creditors = [[user, bal] for user, bal in net_balances.items() if bal > Decimal("0.00")]
    debtors = [[user, -bal] for user, bal in net_balances.items() if bal < Decimal("0.00")]

    transactions: List[Tuple[str, str, Decimal]] = []

    while creditors and debtors:
        # Сортируем по убыванию суммы долга/кредита
        creditors.sort(key=lambda x: x[1], reverse=True)
        debtors.sort(key=lambda x: x[1], reverse=True)

        creditor = creditors[0]
        debtor = debtors[0]

        transfer_amount = min(creditor[1], debtor[1])
        transactions.append((debtor[0], creditor[0], transfer_amount))

        creditor[1] -= transfer_amount
        debtor[1] -= transfer_amount

        if creditor[1] == Decimal("0.00"):
            creditors.pop(0)
        if debtor[1] == Decimal("0.00"):
            debtors.pop(0)

    return transactions


if __name__ == "__main__":
    # Симуляция поездки: 3 участника (Алиса, Боб, Чарли), базовая валюта RUB
    participants = ["Алиса", "Боб", "Чарли"]
    net_balances = {p: Decimal("0.00") for p in participants}

    # Трата 1: Ужин в Европе в воскресенье (выходной день, проверка отката даты курса)
    # Платит Алиса, едят все трое
    tx1_date = datetime.date(2026, 11, 15)
    tx1_currency = "EUR"
    tx1_payer = "Алиса"
    tx1_amount_eur = Decimal("100.00")

    rate, actual_rate_date = get_cbr_rate(tx1_currency, tx1_date)
    tx1_rub = (tx1_amount_eur * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tx1_shares = split_amount_exact(tx1_rub, participants, payer=tx1_payer)

    print(f"=== ТРАТА 1 (Мультивалюта + Выходной день) ===")
    print(f"Дата чека: {tx1_date} | Дата курса ЦБ: {actual_rate_date} | Курс EUR: {rate:.4f} RUB")
    print(f"Сумма: {tx1_amount_eur} EUR -> {tx1_rub} RUB (Оплатила: {tx1_payer})")
    print(f"Распределение долей: {tx1_shares}")
    assert sum(tx1_shares.values()) == tx1_rub

    net_balances[tx1_payer] += tx1_rub
    for user, share in tx1_shares.items():
        net_balances[user] -= share

    # Трата 2: Такси в рублях. Платит Боб за себя и Чарли
    tx2_payer = "Боб"
    tx2_rub = Decimal("1500.00")
    tx2_shares = split_amount_exact(tx2_rub, ["Боб", "Чарли"], payer=tx2_payer)

    print(f"\n=== ТРАТА 2 (Локальная валюта) ===")
    print(f"Сумма: {tx2_rub} RUB (Оплатил: {tx2_payer})")
    print(f"Распределение долей: {tx2_shares}")

    net_balances[tx2_payer] += tx2_rub
    for user, share in tx2_shares.items():
        net_balances[user] -= share

    # Итоговая сверка и оптимизация переводов
    print(f"\n=== ИТОГОВЫЕ БАЛАНСЫ УЧАСТНИКОВ ===")
    for user, bal in net_balances.items():
        print(f"{user}: {bal:+.2f} RUB")

    assert sum(net_balances.values()) == Decimal("0.00"), "Нарушен инвариант нулевой суммы балансов!"

    print(f"\n=== ОПТИМИЗИРОВАННЫЙ ГРАФ ПЕРЕВОДОВ ===")
    transfers = simplify_debts(net_balances)
    for sender, receiver, amount in transfers:
        print(f"{sender} -> {receiver}: {amount:.2f} RUB")
