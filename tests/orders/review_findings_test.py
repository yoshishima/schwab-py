'''Failing tests for order-construction review findings.

Each test describes the order the caller intended. They fail against the
current implementation and are expected to pass once the finding is fixed.
'''
import json
import unittest
import warnings

from decimal import Decimal

from schwab.orders.common import (
        EquityInstruction, OptionInstruction, first_triggers_second)
from schwab.orders.equities import equity_buy_limit, equity_sell_limit
from schwab.orders.generic import OrderBuilder
from schwab.orders.options import (
        bull_call_vertical_open, option_buy_to_open_limit,
        option_buy_to_open_market)


CALL_500 = 'SPY   240621C00500000'
CALL_510 = 'SPY   240621C00510000'
PUT_500 = 'SPY   240621P00500000'
PUT_510 = 'SPY   240621P00510000'


def _quietly(func, *args):
    # Float prices emit a deprecation warning that is not under test here.
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return func(*args)


class FloatPriceIntentTest(unittest.TestCase):

    def test_float_arithmetic_noise_does_not_drop_a_tick(self):
        # Each expression lands one ULP below the intended cent, e.g.
        # (10.1 + 10.2) / 2 == 10.149999999999999. Truncation then drops a
        # whole tick. Deliberate extra digits such as 19.9999999 must still
        # truncate (see generic_test.test_price_do_not_round_up).
        cases = {
            'midpoint (10.1 + 10.2) / 2': ((10.1 + 10.2) / 2, '10.15'),
            '1.15 * 3': (1.15 * 3, '3.45'),
            '2.3 - 0.2': (2.3 - 0.2, '2.10'),
        }
        for label, (value, expected) in cases.items():
            with self.subTest(label, setter='set_price'):
                builder = _quietly(OrderBuilder().set_price, value)
                self.assertEqual(expected, builder.build()['price'])
            with self.subTest(label, setter='set_stop_price'):
                builder = _quietly(OrderBuilder().set_stop_price, value)
                self.assertEqual(expected, builder.build()['stopPrice'])

    def test_nonzero_price_is_not_truncated_to_zero(self):
        # 0.00003 truncates to '0.0000'. A zero sell limit is not what the
        # caller asked for, so this should be rejected, not sent.
        for setter in ('set_price', 'set_stop_price'):
            with self.subTest(setter=setter):
                with self.assertRaises(ValueError):
                    _quietly(getattr(OrderBuilder(), setter), 0.00003)


class OptionTickAndQuantityTest(unittest.TestCase):

    def test_option_prices_below_one_are_not_sub_penny(self):
        # The four-decimal rule for prices below $1 is an equity rule.
        # Options trade in at least whole cents.
        cases = {
            'single option': lambda: option_buy_to_open_limit(
                CALL_500, 1, 0.555),
            'vertical': lambda: bull_call_vertical_open(
                CALL_500, CALL_510, 1, 0.555),
        }
        for label, make_order in cases.items():
            with self.subTest(label):
                self.assertEqual('0.55', _quietly(make_order).build()['price'])

    def test_option_legs_reject_fractional_contracts(self):
        with self.subTest('add_option_leg'):
            with self.assertRaises(ValueError):
                OrderBuilder().add_option_leg(
                    OptionInstruction.BUY_TO_OPEN, CALL_500, 1.5)
        with self.subTest('template'):
            with self.assertRaises(ValueError):
                option_buy_to_open_market(CALL_500, 0.5)


class InvalidInputTest(unittest.TestCase):

    def test_legs_require_a_symbol(self):
        # A None symbol is silently dropped from the built instrument.
        cases = {
            'equity None': lambda: OrderBuilder().add_equity_leg(
                EquityInstruction.BUY, None, 1),
            'equity empty': lambda: OrderBuilder().add_equity_leg(
                EquityInstruction.BUY, '', 1),
            'option None': lambda: OrderBuilder().add_option_leg(
                OptionInstruction.BUY_TO_OPEN, None, 1),
        }
        for label, add_leg in cases.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    add_leg()

    def test_bull_call_vertical_rejects_put_symbols(self):
        with self.assertRaises(ValueError):
            bull_call_vertical_open(PUT_500, PUT_510, 1, '1.00')

    def test_bull_call_vertical_rejects_inverted_strikes(self):
        # Passing (short, long) as bear_call_vertical_open expects yields a
        # bear call spread, which opens for a credit, priced as NET_DEBIT.
        with self.assertRaises(ValueError):
            bull_call_vertical_open(CALL_510, CALL_500, 1, '1.00')

    def test_wrong_enum_type_rejected_even_without_enforcement(self):
        # With enforce_enums=False a member of the wrong enum is stored as-is
        # and build() later fails with an unrelated TypeError.
        with self.assertRaises(ValueError):
            OrderBuilder(enforce_enums=False).add_equity_leg(
                OptionInstruction.BUY_TO_OPEN, 'AAPL', 1)


class DecimalInputTest(unittest.TestCase):

    def test_decimal_price_does_not_use_deprecated_float_path(self):
        # Decimal is the exact type callers should use for money, yet it is
        # routed through truncate_float and its float deprecation warning.
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            builder = OrderBuilder().set_price(Decimal('10.15'))
        self.assertEqual('10.15', builder.build()['price'])

    def test_decimal_quantity_is_accepted_and_serializable(self):
        # Decimal prices are accepted but Decimal quantities raise.
        order = OrderBuilder().add_equity_leg(
            EquityInstruction.BUY, 'AAPL', Decimal('10')).build()
        self.assertEqual(
            10, json.loads(json.dumps(order))['orderLegCollection'][0][
                'quantity'])


class BuilderReuseTest(unittest.TestCase):

    def test_first_triggers_second_does_not_mutate_first_order(self):
        entry = equity_buy_limit('AAPL', 10, '150.00')
        before = entry.build()

        first_triggers_second(entry, equity_sell_limit('AAPL', 10, '160.00'))

        self.assertEqual(before, entry.build())

    def test_reused_first_order_does_not_accumulate_children(self):
        entry = equity_buy_limit('AAPL', 10, '150.00')

        first_triggers_second(entry, equity_sell_limit('AAPL', 10, '160.00'))
        second = first_triggers_second(
            entry, equity_sell_limit('AAPL', 10, '140.00')).build()

        self.assertEqual(1, len(second['childOrderStrategies']))
        self.assertEqual('140.00', second['childOrderStrategies'][0]['price'])
