import datetime
import unittest
from unittest.mock import AsyncMock, Mock, patch

from schwab.client import Client
from schwab.orders import options
from tests import review_regressions_test


class StreamRegistrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_reconnect_does_not_duplicate_and_clear_removes_handlers(self):
        fixture = review_regressions_test.StreamLifecycleTest()
        fixture.setUp()
        client = fixture.client
        handler = Mock()
        with patch('schwab.streaming.ws_client.connect', new=AsyncMock(
                side_effect=[fixture.socket(), fixture.socket()])):
            try:
                for _ in range(2):
                    await client.login()
                    client.add_chart_equity_handler(handler)
                    handler.reset_mock()
                    client._overflow_items.append({'data': [{
                        'service': 'CHART_EQUITY', 'content': [{'5': 123.45}]}]})
                    await client.handle_message()
                    handler.assert_called_once()
                client.add_account_activity_handler(handler)
                client.clear_handlers('CHART_EQUITY')
                self.assertNotIn('CHART_EQUITY', client._handlers)
                self.assertEqual(1, len(client._handlers['ACCT_ACTIVITY']))
                client.clear_handlers()
                self.assertFalse(client._handlers)
            finally:
                await client._close_connection()

    async def test_bound_method_registration_is_idempotent(self):
        from schwab.streaming import StreamClient
        client = StreamClient(Mock())
        class Receiver:
            def handle(self, message):
                pass
        receiver = Receiver()
        client.add_account_activity_handler(receiver.handle)
        client.add_account_activity_handler(receiver.handle)
        self.assertEqual(1, len(client._handlers['ACCT_ACTIVITY']))


class VerticalValidationTest(unittest.TestCase):
    def test_all_templates(self):
        def symbol(kind, strike, underlying='SPY', expiration='261218'):
            return options.OptionSymbol(underlying, expiration, kind, str(strike)).build()
        for direction in ('bull', 'bear'):
            for kind in ('call', 'put'):
                for action in ('open', 'close'):
                    name = f'{direction}_{kind}_vertical_{action}'
                    template = getattr(options, name)
                    contract = kind[0].upper()
                    low, high = symbol(contract, 500), symbol(contract, 510)
                    with self.subTest(template=name):
                        template(low, high, 1, '1.00').build()
                        template('opaque-a', 'opaque-b', 1, '1.00').build()
                        invalid = [
                            (high, low), (low, low),
                            (symbol('P' if contract == 'C' else 'C', 500), high),
                            (low, symbol(contract, 510, underlying='QQQ')),
                            (low, symbol(contract, 510, expiration='270115')),
                        ]
                        for first, second in invalid:
                            with self.subTest(first=first, second=second):
                                with self.assertRaises(ValueError):
                                    template(first, second, 1, '1.00')


class QueryContextTest(unittest.TestCase):
    def setUp(self):
        self.client = Client('synthetic', Mock())
        self.client._get_request = Mock(side_effect=lambda path, params: params)

    def test_context_inference_and_mismatch(self):
        p = self.client.PriceHistory
        for value_name, type_name, members, types in (
                ('period', 'period_type', p.Period, p.PeriodType),
                ('frequency', 'frequency_type', p.Frequency, p.FrequencyType)):
            for member in members:
                with self.subTest(member=member):
                    result = self.client.get_price_history('SPY', **{value_name: member})
                    wire_type = 'periodType' if value_name == 'period' else 'frequencyType'
                    self.assertEqual(member.context, result[wire_type])
                    self.assertEqual(member.value, result[value_name])
                    for context in types:
                        if context.value != member.context:
                            self.client._get_request.reset_mock()
                            with self.assertRaises(ValueError):
                                self.client.get_price_history('SPY', **{
                                    value_name: member, type_name: context})
                            self.client._get_request.assert_not_called()
        self.client.set_enforce_enums(False)
        self.assertEqual({'symbol': 'SPY', 'period': 1, 'frequency': 1},
                         self.client.get_price_history('SPY', period=1, frequency=1))
        with self.assertRaises(ValueError):
            self.client.get_price_history('SPY', period=p.Period.ONE_YEAR, period_type='day')

    def test_date_end_bounds_and_explicit_datetimes(self):
        for day in (datetime.date(2026, 9, 27), datetime.date(2026, 12, 31),
                    datetime.date(2024, 2, 29)):
            start = day.isoformat() + 'T00:00:00.000Z'
            end = (day + datetime.timedelta(days=1)).isoformat() + 'T00:00:00.000Z'
            for query in (lambda **kw: self.client.get_orders_for_account('test', **kw),
                          self.client.get_orders_for_all_linked_accounts):
                result = query(from_entered_datetime=day, to_entered_datetime=day)
                self.assertEqual(start, result['fromEnteredTime'])
                self.assertEqual(end, result['toEnteredTime'])
            result = self.client.get_transactions('test', start_date=day, end_date=day)
            self.assertEqual(start, result['startDate'])
            self.assertEqual(end, result['endDate'])
        exact = datetime.datetime(2026, 9, 27, 12, tzinfo=datetime.timezone(
            datetime.timedelta(hours=-4)))
        result = self.client.get_transactions('test', end_date=exact)
        self.assertEqual('2026-09-27T16:00:00.000Z', result['endDate'])
