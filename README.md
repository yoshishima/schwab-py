# `schwab-py`: A Charles Schwab API wrapper

[![Discord](https://img.shields.io/discord/720378361880248621.svg?label=&logo=discord&logoColor=ffffff&color=7389D8&labelColor=6A7EC2)](https://discord.gg/BEr6y6Xqyv)
[![Patreon](https://img.shields.io/endpoint.svg?url=https%3A%2F%2Fshieldsio-patreon.vercel.app%2Fapi%3Fusername%3Dschwabpy%26type%3Dpatrons&style=flat)](https://patreon.com/schwabpy)
[![Documentation](https://readthedocs.org/projects/schwab-py/badge/?version=latest)](https://schwab-py.readthedocs.io/en/latest/?badge=latest)
[![Tests](https://github.com/alexgolec/schwab-py/actions/workflows/python.yml/badge.svg)](https://github.com/alexgolec/schwab-py/actions/workflows/python.yml)
[![PyPI](https://badge.fury.io/py/schwab-py.svg)](https://badge.fury.io/py/schwab-py)
[![Coverage](https://codecov.io/gh/alexgolec/schwab-py/branch/main/graph/badge.svg)](https://codecov.io/gh/alexgolec/schwab-py)

## What is `schwab-py`?

`schwab-py` is an unofficial wrapper around the Charles Schwab Trader and
Market Data APIs. It provides a thin Python interface over the HTTP and
streaming endpoints while returning the original response data for callers to
interpret.

Notable functionality includes:

- OAuth login, token storage, and token refresh
- Account details, balances, positions, transactions, and order history
- Order placement, replacement, cancellation, templates, and code generation
- Quotes, fundamentals, instruments, movers, market hours, and price history
- Option chains and option expiration chains
- Streaming quotes, charts, account activity, and order book data

## Requirements

`schwab-py` requires Python 3.12 or newer. The test matrix covers Python 3.12,
3.13, and 3.14, with current development focused on Python 3.14 compatibility.

## Installation

```console
pip install schwab-py
```

Before using the library, create an account and application on the
[Charles Schwab developer site](https://developer.schwab.com/login). Record the
API key, app secret, and callback URL. The application must be approved by
Schwab before it can access the APIs, which can take several days.

See the [getting-started guide](https://schwab-py.readthedocs.io/en/latest/getting-started.html)
for detailed setup instructions.

## Quick start

The following example authenticates and requests available daily price history
for Apple:

```python
import json

from schwab import auth

api_key = 'YOUR_API_KEY'
app_secret = 'YOUR_APP_SECRET'
callback_url = 'https://127.0.0.1:8182/'
token_path = '/path/to/token.json'

client = auth.easy_client(
    api_key,
    app_secret,
    callback_url,
    token_path,
)

response = client.get_price_history_every_day('AAPL')
response.raise_for_status()
print(json.dumps(response.json(), indent=4))
```

Never commit or share API secrets or token files.

## Important API behavior

### Price history

The raw `Client.get_price_history` method supports period-based queries or an
explicit start and end time. The `get_price_history_every_*` convenience
methods use an explicit date range and do not send the redundant `period`
parameter. If omitted, their start time defaults to January 1, 1971 UTC and
their end time defaults to the current time. Schwab may limit the returned
history based on candle frequency.

### Order history

The order-history endpoints have different maximum ranges. When date bounds
are omitted:

- `get_orders_for_account` requests the preceding 365 days.
- `get_orders_for_all_linked_accounts` requests the preceding 60 days.

Both methods default the end of the range to the current time. Pass explicit
date bounds when a narrower range is required.

### Boolean query parameters

Optional boolean parameters must be actual Python `bool` values. For example,
pass `indicative=True`, not `indicative='true'`. This validation also applies to
`include_underlying_quote`, `need_extended_hours_data`, and
`need_previous_close`.

## Migrating from `tda-api`

The former TD Ameritrade APIs are no longer available, so `tda-api` cannot be
used for new requests. See the
[transition guide](https://schwab-py.readthedocs.io/en/latest/tda-transition.html)
for migration instructions.

## Why use `schwab-py`?

1. **Safer authentication.** The library implements Schwab's OAuth callback
   flow and manages token refresh, avoiding the need to build security-sensitive
   authentication code from scratch.
2. **Minimal API wrapping.** Methods expose Schwab's endpoints without hiding
   the underlying HTTP responses, allowing callers to handle status codes and
   response payloads directly.
3. **Order-building utilities.** Templates and builders make common equity and
   option orders easier to construct while retaining access to raw order specs.
4. **Synchronous and asynchronous clients.** Applications can choose the model
   that best fits their workload, including asynchronous streaming support.

## Limitations

- The API is not connected to thinkorswim-specific functionality, although it
  can access and trade against the same eligible Schwab accounts.
- Paper trading is not supported.
- Historical option pricing data is not available.
- API availability, permissions, limits, and response formats are controlled by
  Charles Schwab and may change independently of this library.

## Documentation and support

The complete documentation is available on
[Read the Docs](https://schwab-py.readthedocs.io/en/latest/). Community support
is available through the [Discord server](https://discord.gg/BEr6y6Xqyv).

Bug reports and suggestions can be submitted through
[GitHub Issues](https://github.com/alexgolec/schwab-py/issues). Contributions are
welcome through [pull requests](https://github.com/alexgolec/schwab-py/pulls).

`schwab-py` is released under the
[MIT License](https://github.com/alexgolec/schwab-py/blob/main/LICENSE).

## Disclaimer

`schwab-py` is an unofficial API wrapper. It is not endorsed by or affiliated
with Charles Schwab or any associated organization. Review and comply with the
terms of service for the underlying APIs. The project authors accept no
responsibility for damage resulting from use of this package. See the
[LICENSE](https://github.com/alexgolec/schwab-py/blob/main/LICENSE) file for
details.
