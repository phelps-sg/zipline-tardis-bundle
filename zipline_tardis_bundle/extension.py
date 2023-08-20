from zipline_tardis_bundle import register_tardis_bundle, live_symbols_since

# pylint: disable=line-too-long
# noinspection SpellCheckingInspection
API_KEY = "CHANGE_ME"
EXCHANGE = "coinbase"

register_tardis_bundle(
    "custom-tardis-bundle",
    pairs=["ETH-USD", "BTC-USD"],
    api_key=API_KEY,
    exchange=EXCHANGE,
    start_date="2022-01-01",
    end_date="2022-01-31",
)


def register_with_start_date(bundle_name: str, date: str, fiat_currency: str) -> None:
    register_tardis_bundle(
        bundle_name,
        pairs=list(live_symbols_since(EXCHANGE, start_date, fiat_currency)),
        api_key=API_KEY,
        exchange=EXCHANGE,
        start_date=date,
        end_date="2023-03-01",
    )


for fiat in ["USD", "GBP"]:
    for year in range(2019, 2023):
        start_date = f"{year}-03-30"
        register_with_start_date(
            f"tardis-{EXCHANGE}-since-{year}-{fiat}",
            date=start_date,
            fiat_currency=fiat,
        )
