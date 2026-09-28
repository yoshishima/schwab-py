import asyncio
import datetime
import json
import tempfile
import threading
import unittest
import warnings
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from schwab import auth
from schwab.client import Client
from schwab.contrib.orders import construct_repeat_order
from schwab.orders.common import EquityInstruction, OptionInstruction
from schwab.orders.generic import OrderBuilder
from schwab.utils import EnumEnforcer


class InputValidationTest(unittest.TestCase):
    def test_symbol_validation_preserves_option_padding(self):
        for method, instruction in [('add_equity_leg', EquityInstruction.BUY),
                                    ('add_option_leg', OptionInstruction.BUY_TO_OPEN)]:
            for symbol in (None, '', '  ', 123):
                with self.subTest(method=method, symbol=symbol):
                    with self.assertRaisesRegex(ValueError, 'symbol'):
                        getattr(OrderBuilder(), method)(instruction, symbol, 1)
        symbol = 'SPY   261218C00500000'
        order = OrderBuilder().add_option_leg(OptionInstruction.BUY_TO_OPEN, symbol, 1).build()
        self.assertEqual(symbol, order['orderLegCollection'][0]['instrument']['symbol'])

    def test_decimal_prices_and_quantities_are_json_safe(self):
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            builder = (OrderBuilder().set_price(Decimal('10.15'))
                       .set_stop_price(Decimal('10.10'))
                       .add_equity_leg(EquityInstruction.BUY, 'SPY', Decimal('1.25')))
            result = json.loads(json.dumps(builder.build(), allow_nan=False))
        self.assertEqual('10.15', result['price'])
        self.assertEqual('10.10', result['stopPrice'])
        self.assertEqual(1.25, result['orderLegCollection'][0]['quantity'])
        builder.copy_price(Decimal('10.1234567890123456789'))
        self.assertEqual('10.1234567890123456789', builder.build()['price'])
        builder.copy_stop_price(Decimal('9.1234567890123456789'))
        self.assertEqual('9.1234567890123456789', builder.build()['stopPrice'])

    def test_repeat_order_from_decimal_json(self):
        historical = json.loads('{"orderStrategyType":"SINGLE","orderType":"LIMIT",'
            '"price":10.15,"orderLegCollection":[{"orderLegType":"OPTION",'
            '"instruction":"BUY_TO_OPEN","quantity":2.0,"instrument":'
            '{"assetType":"OPTION","symbol":"SPY   261218C00500000"}}]}', parse_float=Decimal)
        result = json.loads(json.dumps(construct_repeat_order(historical).build(), allow_nan=False))
        self.assertEqual('10.15', result['price'])
        self.assertEqual(2, result['orderLegCollection'][0]['quantity'])

    def test_invalid_decimals_rejected(self):
        for value in ('NaN', 'sNaN', 'Infinity', '-Infinity'):
            for setter in ('set_price', 'set_stop_price', 'copy_price', 'copy_stop_price'):
                with self.subTest(value=value, setter=setter), self.assertRaises(ValueError):
                    getattr(OrderBuilder(), setter)(Decimal(value))
            with self.assertRaises(ValueError):
                OrderBuilder().add_equity_leg(EquityInstruction.BUY, 'SPY', Decimal(value))
        for value in ('0.1234567890123456789', '1e-1000'):
            with self.assertRaisesRegex(ValueError, 'without loss'):
                OrderBuilder().add_equity_leg(EquityInstruction.BUY, 'SPY', Decimal(value)).build()
        with self.assertRaises(ValueError):
            OrderBuilder().add_option_leg(OptionInstruction.BUY_TO_OPEN, 'SPY', Decimal('1.5'))

    def test_wrong_enum_rejected_in_scalar_and_iterable_paths(self):
        enforcer = EnumEnforcer(False)
        with self.assertRaises(ValueError):
            enforcer.convert_enum(OptionInstruction.BUY_TO_OPEN, EquityInstruction)
        for value in ([OptionInstruction.BUY_TO_OPEN], OptionInstruction.BUY_TO_OPEN):
            with self.assertRaises(ValueError):
                enforcer.convert_enum_iterable(value, EquityInstruction)
        self.assertEqual(['BUY'], enforcer.convert_enum_iterable('BUY', EquityInstruction))
        self.assertEqual(['BUY'], enforcer.convert_enum_iterable(EquityInstruction.BUY, EquityInstruction))
        with self.assertRaises(ValueError):
            EnumEnforcer(True).convert_enum_iterable('BUY', EquityInstruction)

    def test_query_zero_and_bare_string(self):
        client = Client('synthetic', Mock(), enforce_enums=False)
        client._get_request = lambda path, params: params
        self.assertEqual(0, client.get_orders_for_account('test', max_results=0)['maxResults'])
        self.assertEqual(0, client.get_orders_for_all_linked_accounts(max_results=0)['maxResults'])
        self.assertNotIn('maxResults', client.get_orders_for_account('test'))
        self.assertEqual('quote', client.get_quotes(['SPY'], fields='quote')['fields'])


class AsyncRefreshTest(unittest.IsolatedAsyncioTestCase):
    def make_client(self, received, writer):
        with patch('schwab.auth.AsyncOAuth2Client') as async_session:
            if received:
                with patch('schwab.auth.OAuth2Client') as sync_session:
                    sync_session.return_value.fetch_token.return_value = {'access_token': 'initial'}
                    client = auth.client_from_received_url('synthetic', 'synthetic',
                        auth.AuthContext('https://localhost', 'unused', 'state'),
                        'https://localhost?code=synthetic', writer, asyncio=True)
            else:
                client = auth.client_from_access_functions('synthetic', 'synthetic',
                    lambda: {'creation_timestamp': 123, 'token': {'access_token': 'initial'}},
                    writer, asyncio=True)
            callback = async_session.call_args.kwargs['update_token']
        return client, callback

    async def test_both_factory_callbacks_persist_file_off_loop(self):
        for received in (False, True):
            with self.subTest(received=received), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'token.json'
                writer = auth.__dict__['__make_update_token_func'](str(path))
                client, callback = self.make_client(received, writer)
                threads = []
                with patch('schwab.auth.os.fsync', side_effect=lambda fd: threads.append(threading.get_ident())):
                    await callback({'access_token': 'refreshed'})
                self.assertTrue(threads)
                self.assertNotIn(threading.get_ident(), threads)
                saved = json.loads(path.read_text())
                self.assertEqual({'access_token': 'refreshed'}, saved['token'])
                self.assertEqual(client.token_metadata.creation_timestamp, saved['creation_timestamp'])
                self.assertEqual(saved['token'], client.token_metadata.token)

    async def test_failure_propagates_and_custom_writer_stays_on_loop(self):
        for received in (False, True):
            writer = Mock()
            client, callback = self.make_client(received, writer)
            seen = []
            def fail(*args, **kwargs):
                seen.append(threading.get_ident())
                raise OSError('persistence failed')
            writer.side_effect = fail
            with self.assertRaisesRegex(OSError, 'persistence failed'):
                await callback({'access_token': 'refreshed'})
            self.assertEqual([threading.get_ident()], seen)
            self.assertEqual({'access_token': 'refreshed'}, client.token_metadata.token)

    async def test_canceled_write_finishes_before_next_write(self):
        started = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        seen = []
        def writer(payload):
            value = payload['token']['access_token']
            if value == 'first':
                loop.call_soon_threadsafe(started.set)
                if not release.wait(5):
                    raise TimeoutError('test writer not released')
            seen.append(value)
        writer._schwab_file_writer = True
        client, callback = self.make_client(False, writer)
        first = asyncio.create_task(callback({'access_token': 'first'}))
        try:
            await asyncio.wait_for(started.wait(), 2)
            first.cancel()
            second = asyncio.create_task(callback({'access_token': 'second'}))
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await first
        await second
        self.assertEqual(['first', 'second'], seen)
        self.assertEqual({'access_token': 'second'}, client.token_metadata.token)
