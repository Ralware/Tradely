from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.models import TradingRules
from app.core.trading_rules import (
    binance_rules_from_exchange_info,
    calculate_amount_transaction,
)


CRYPTO_RULES = TradingRules(
    quantity_step=0.00001,
    min_quantity=0.00001,
    min_notional=5,
    fractional=True,
    source="Binance Spot Exchange Rules",
)


def test_amount_buy_rounds_down_and_reconciles_fees():
    result = calculate_amount_transaction(
        side="BUY", requested_amount=100.001, price=100000,
        rules=CRYPTO_RULES, fees=0.5,
    )
    assert result["quantity"] == 0.001
    assert result["actual_amount"] == 100
    assert result["remaining_amount"] == pytest.approx(0.001)
    assert result["total_cash_cost"] == pytest.approx(100.5)
    assert result["net_proceeds"] is None


def test_amount_sell_checks_available_market_value():
    with pytest.raises(ValueError, match="exceeds the available holdings market value"):
        calculate_amount_transaction(
            side="SELL", requested_amount=250, price=100000,
            rules=CRYPTO_RULES, available_quantity=0.002, fees=1,
        )
    result = calculate_amount_transaction(
        side="SELL", requested_amount=50, price=100000,
        rules=CRYPTO_RULES, available_quantity=0.002, fees=1,
    )
    assert result["quantity"] == 0.0005
    assert result["actual_amount"] == 50
    assert result["net_proceeds"] == 49
    assert result["remaining_holding_quantity"] == 0.0015
    assert result["max_sell_amount"] == 200


def test_amount_rejects_below_step_or_minimum_notional():
    with pytest.raises(ValueError, match="quantity step"):
        calculate_amount_transaction(
            side="BUY", requested_amount=0.000001, price=100000,
            rules=CRYPTO_RULES, fees=0,
        )
    with pytest.raises(ValueError, match="minimum notional"):
        calculate_amount_transaction(
            side="BUY", requested_amount=4.0, price=100000,
            rules=CRYPTO_RULES, fees=0,
        )


def test_binance_exchange_info_rules_are_parsed_for_exact_pair():
    payload = {
        "symbols": [{
            "symbol": "BTCUSDT",
            "filters": [
                {"filterType": "LOT_SIZE", "stepSize": "0.00001000", "minQty": "0.00001000",
                 "maxQty": "9000.00000000"},
                {"filterType": "NOTIONAL", "minNotional": "5.00000000"},
            ],
        }],
    }
    rules = binance_rules_from_exchange_info(payload, "BTCUSDT")
    assert rules.quantity_step == 0.00001
    assert rules.min_quantity == 0.00001
    assert rules.max_quantity == 9000
    assert rules.min_notional == 5
    assert rules.source == "Binance Spot Exchange Rules"
    assert Decimal(str(rules.quantity_step)) == Decimal("0.00001")
