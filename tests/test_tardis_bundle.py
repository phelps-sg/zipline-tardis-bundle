import datetime
import logging
import os
import runpy
import shutil
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Iterator, List, Set
from unittest.mock import MagicMock, call

import pandas as pd
import zipline.utils.paths as pth
from exchange_calendars import ExchangeCalendar
from datetime import timezone
from fn import F
from numpy import dtype
from pytest import fixture
from ray.util.client import ray
from zipline import Blotter, TradingAlgorithm, get_calendar
from zipline.assets import AssetDBWriter
from zipline.data import bundles
from zipline.data.adjustments import SQLiteAdjustmentWriter
from zipline.data.bcolz_daily_bars import BcolzDailyBarReader, BcolzDailyBarWriter
from zipline.data.bcolz_minute_bars import BcolzMinuteBarWriter
from zipline.data.bundles import to_bundle_ingest_dirname
from zipline.data.bundles.core import (
    adjustment_db_relative,
    asset_db_relative,
    cache_path,
    daily_equity_relative,
    minute_equity_relative,
    register,
)
from zipline.data.data_portal import DataPortal
from zipline.extensions import load
from zipline.finance import metrics
from zipline.finance.trading import SimulationParameters
from zipline.pipeline.loaders import USEquityPricingLoader
from zipline.utils.cache import dataframe_cache, working_dir
from zipline.utils.run_algo import BenchmarkSpec

import zipline_tardis_bundle as tb
from zipline_tardis_bundle import (
    Asset,
    CALENDAR_24_7,
    EMPTY_FILE_SIZE,
    TardisBundle,
    assets_to_strs,
    tardis_bundle,
    tardis_files,
    tardis_ingester,
    to_tardis_date,
    strs_to_assets,
    utc_timestamp
)

ZIPLINE_TEST_DIR = "./data/testing/zipline"


class MockRay:
    @staticmethod
    def get(futures):
        return futures

    def __init__(self):
        pass

    def shutdown(self):
        pass


def microseconds(seconds: int | float) -> float:
    return seconds * 10e5


def timestamp(offset: int | float, start: datetime.datetime) -> float:
    return microseconds(start.timestamp() + offset)


def empty_pricing_data(*args: str) -> pd.DataFrame:
    return pd.DataFrame(dict(), index=list(map(utc_timestamp, args)))


def quotes_df(
    timestamps: list[float],
    ask_prices: list[float],
    bid_prices: list[float],
    ask_amounts: list[float],
    bid_amounts: list[float],
    asset: Asset,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "local_timestamp": timestamps,
            "symbol": asset.symbol,
            "ask_amount": ask_amounts,
            "bid_amount": bid_amounts,
            "ask_price": ask_prices,
            "bid_price": bid_prices,
        }
    )


@dataclass
class MockSize:
    st_size: int


# pylint: disable=too-few-public-methods
class MockDirEntry:
    def __init__(self, name: str, size: int = 200):
        self.name = name
        self.size = size

    @staticmethod
    def is_file() -> bool:
        return True

    def stat(self):
        return MockSize(self.size)


# pylint: disable=protected-access
class TestTardisBundle:
    @fixture
    def tardis_quotes_1(self) -> pd.DataFrame:
        return quotes_df(
            timestamps=[
                timestamp(t, datetime.datetime(2012, 1, 1)) for t in [0, 61, 62]
            ],
            ask_prices=[1691.82, 1691.80, 2000],
            bid_prices=[1691.81, 1691.79, 1000],
            ask_amounts=[0.24, 0.25, 1.0],
            bid_amounts=[0.25, 0.26, 1.0],
            asset=Asset("ETH-USD"),
        )

    @fixture
    def tardis_quotes_2(self) -> pd.DataFrame:
        return quotes_df(
            timestamps=[
                timestamp(t, datetime.datetime(2012, 1, 2)) for t in [120, 170, 240]
            ],
            ask_prices=[200, 20, 2000],
            bid_prices=[100, 10, 1000],
            ask_amounts=[1.0, 2.5, 5.0],
            bid_amounts=[1.0, 2.5, 5.0],
            asset=Asset("ETH-USD"),
        )

    @fixture
    def tardis_quotes_3(self) -> pd.DataFrame:
        timestamps = [
            datetime.datetime(2012, 1, 1, hour=23, minute=59),
            datetime.datetime(2012, 1, 2, hour=1, minute=0),
            datetime.datetime(2012, 1, 2, hour=1, minute=1),
            datetime.datetime(2012, 1, 2, hour=1, minute=2),
        ]
        return quotes_df(
            timestamps=[t.timestamp() * 10e5 for t in timestamps],
            ask_prices=[1, 200, 20, 2000],
            bid_prices=[500, 100, 10, 1000],
            ask_amounts=[0, 1.0, 2.5, 5.0],
            bid_amounts=[1.0, 2.5, 5.0],
            asset=Asset("ETH-USD"),
        )

    @fixture
    def ray_client(self):
        ray.init(num_cpus=2)
        yield
        ray.shutdown()

    @fixture
    def zipline_environment(self):
        test_dir = os.path.join(tempfile.gettempdir(), ZIPLINE_TEST_DIR)

        def clean() -> None:
            shutil.rmtree(test_dir, ignore_errors=True)

        environ = {"ZIPLINE_ROOT": test_dir}
        if os.path.exists(test_dir):
            clean()
        os.makedirs(test_dir)

        yield environ

        clean()

    def test_to_tardis_date(self):
        assert to_tardis_date(pd.Timestamp("2022-01-01 05:12")) == "2022-01-01"

    def test_convert_to_ohlc(self, tardis_quotes_1: pd.DataFrame):
        (ask_0, ask_1, ask_2) = tardis_quotes_1.ask_price
        (bid_0, bid_1, bid_2) = tardis_quotes_1.bid_price

        pipeline = F() >> tb._index_to_datetime >> tb._convert_to_ohlc
        result = pipeline(tb._ResampleData("filename", tardis_quotes_1)).dfr

        assert len(result.index) == 2
        assert result.index[0] == pd.Timestamp("2012-01-01", tz="UTC")
        diff = result.index[1] - result.index[0]
        assert diff.seconds == 60
        assert (
            result["open"][0]
            == result["close"][0]
            == result["high"][0]
            == result["low"][0]
            == (ask_0 + bid_0) / 2
        )
        assert (
            result["volume"][0]
            == tardis_quotes_1.ask_amount[0] + tardis_quotes_1.bid_amount[0]
        )
        assert result["volume"][1] == 0.25 + 0.26 + 2.0
        assert result["open"][1] == result["high"][1] == (ask_1 + bid_1) / 2
        assert result["close"][1] == result["low"][1] == (ask_2 + bid_2) / 2

    def test_generate_empty_metadata(self):
        test_pairs = ["ETH-USD", "BTC-USD"]
        result = tb._generate_empty_metadata(strs_to_assets(test_pairs))
        assert len(result) == 2
        assert set(result.columns) == {
            "start_date",
            "end_date",
            "auto_close_date",
            "symbol",
            "calendar_name",
            "exchange",
        }
        assert result.start_date.dtype == dtype("<M8[ns]")
        assert result.end_date.dtype == dtype("<M8[ns]")
        assert result.auto_close_date.dtype == dtype("<M8[ns]")
        assert result.symbol.dtype == dtype("O")
        assert result.calendar_name.dtype == dtype("O")
        assert result.exchange.dtype == dtype("O")

    def test_generate_metadata(self):
        test_start_date = pd.Timestamp("2011-01-01")
        test_end_date = pd.Timestamp("2020-01-01")
        test_pairs = strs_to_assets(["ETH-USD", "BTC-GBP"])
        test_df = pd.DataFrame(dict(), index=[test_start_date, test_end_date])
        for pair in test_pairs:
            result = tb._generate_metadata(test_df, pair)
            assert result == (
                test_start_date,
                test_end_date,
                test_end_date,
                pair.symbol,
                CALENDAR_24_7,
                CALENDAR_24_7,
            )

    def test_no_splits(self):
        splits = tb._no_splits()
        assert set(splits.columns) == {"sid", "ratio", "effective_date"}
        assert len(splits) == 0

    def test_no_dividends(self):
        dividends = tb._no_dividends()
        # pylint: disable=duplicate-code
        assert set(dividends.columns) == {
            "sid",
            "amount",
            "ex_date",
            "record_date",
            "declared_date",
            "pay_date",
        }
        assert len(dividends) == 0

    def test_resample_and_merge(
        self, mocker, tardis_quotes_1: pd.DataFrame, tardis_quotes_2: pd.DataFrame
    ):
        mock_dir = {
            "coinbase_quotes_2012-01-01_ETH-USD.csv.gz": tardis_quotes_1,
            "coinbase_quotes_2012-01-02_ETH-USD.csv.gz": tardis_quotes_2,
        }

        def mock_read_quotes_data(filename: str, _csv_dir: str) -> tb._ResampleData:
            return tb._ResampleData(filename, mock_dir[filename])

        mocker.patch(
            "zipline_tardis_bundle._read_quotes_data",
            side_effect=mock_read_quotes_data,
        )

        result = tb._resample_and_merge(
            "NotDir",
            iter(mock_dir.keys()),
            ray_client=MockRay(),  # type: ignore
            to_future=lambda f: f,
            frequency="1Min",
        )
        assert result is not None
        assert (result.index == result.index.sort_values()).all()
        assert len(result.index.drop_duplicates()) == len(result.index)  # type: ignore
        assert (result.volume.values == [0.49, 2.51, 7.0, 0.0, 10.0]).all()  # type: ignore
        assert (
            result.open[0]
            == result.high[0]
            == result.low[0]
            == result.close[0]
            == 1691.815
        )
        assert result.open[2] == result.high[2] == 150
        assert result.low[2] == result.close[2] == 15
        assert (
            result.open[4]
            == result.high[4]
            == result.low[4]
            == result.close[4]
            == 1500.0
        )

    # noinspection PyTypeChecker
    def test_asset_file_dict(self):
        test_exchange = "coinbase"
        filenames = [
            "coinbase_quotes_2023-01-19_ETH-GBP.csv.gz",
            "coinbase_quotes_2023-02-19_ETH-USD.csv.gz",
            "coinbase_quotes_2023-02-19_ETH-GBP.csv.gz",
            "coinbase_quotes_2023-02-20_ETH-GBP.csv.gz",
            "coinbase_quotes_2023-03-20_ETH-GBP.csv.gz",
            "coinbase_quotes_2023-02-20_ETH-GBP.unconfirmed",
            "coinbase_quotes_2023-02-19_API3-USD.csv.gz",
            "temporary-file.txt",
        ]

        def test_files() -> Iterator[MockDirEntry]:
            for name in filenames:
                yield MockDirEntry(name)
            yield MockDirEntry(
                "coinbase_quotes_2023-02-21_ETH-GBP.csv.gz", size=EMPTY_FILE_SIZE
            )

        def files_for(asset_symbol: str) -> Set[str]:
            return set(
                tardis_files(
                    Asset(asset_symbol),
                    test_exchange,
                    pd.Timestamp("2023-02-19"),
                    pd.Timestamp("2023-02-21"),
                    test_files(),  # type: ignore
                )
            )

        assert files_for("ETH-GBP") == {filenames[2], filenames[3]}
        assert files_for("ETH-USD") == {filenames[1]}
        assert files_for("API3-USD") == {filenames[6]}
        assert files_for("ETH-EUR") == set()

    def test_within_range(self):
        range_start = pd.Timestamp("2010-01-01")
        range_end = pd.Timestamp("2024-01-01")

        def within(df: pd.DataFrame) -> bool:
            return tb._within_range(range_start, range_end, df)

        test_df_1 = empty_pricing_data("2021-01-01", "2022-01-01")
        assert within(test_df_1)

        test_df_2 = empty_pricing_data("2009-01-01", "2022-01-01")
        assert not within(test_df_2)

        test_df_3 = empty_pricing_data("2010-01-01", "2024-01-01")
        assert within(test_df_3)

        test_df_4 = empty_pricing_data("2021-01-01", "2024-05-01")
        assert not within(test_df_4)

    def test_extension(self, mocker, zipline_environment):
        mocker.patch("os.environ", zipline_environment)
        runpy.run_path("./zipline_tardis_bundle/extension.py")
        tardis_bundles = [bundle for bundle in bundles.bundles if "tardis" in bundle]
        assert len(tardis_bundles) > 0
        for bundle in tardis_bundles:
            bundle_data = bundles.bundles[bundle]
            assert bundle_data.minutes_per_day == 60 * 24
            assert bundle_data.calendar_name == CALENDAR_24_7
            assert bundle_data.start_session > pd.Timestamp("2009")

    # pylint: disable=too-many-locals, attribute-defined-outside-init
    def test_tardis_bundle(self, mocker, zipline_environment):
        class MockWriter:
            def write(self, *_args, **_kwargs):
                pass

        asset_db_writer = MockWriter()
        minute_bar_writer = MockWriter()
        daily_bar_writer = MockWriter()
        adjustment_writer = MockWriter()

        asset_db_writer.write = MagicMock()
        minute_bar_writer.write = MagicMock()
        daily_bar_writer.write = MagicMock()
        adjustment_writer.write = MagicMock()

        start_date = "2010-01-01"
        end_date = "2020-01-01"
        start_session = pd.Timestamp(start_date)
        end_session = pd.Timestamp(end_date)

        test_pricing_data = empty_pricing_data(start_date, end_date)
        test_pairs = strs_to_assets(["ETH-USD", "BTC-USD"])
        test_api_key = "TEST-API-KEY"
        test_exchange = "coinbase"

        mocker.patch(
            "zipline_tardis_bundle.CSV_DIR",
            "./tests/data/tardis_bundle",
        )
        mocker.patch(
            "zipline_tardis_bundle._download_data",
            return_value=None,
        )
        mocker.patch(
            "zipline_tardis_bundle._data_pipeline",
            return_value=[
                (i, test_pricing_data, tb._generate_metadata(test_pricing_data, pair))
                for i, pair in enumerate(test_pairs)
            ],
        )

        # noinspection PyTypeChecker
        tardis_bundle(
            environ=zipline_environment,
            asset_db_writer=asset_db_writer,
            minute_bar_writer=minute_bar_writer,
            daily_bar_writer=daily_bar_writer,
            adjustment_writer=adjustment_writer,
            _calendar=None,
            start_session=start_session,
            end_session=end_session,
            _cache=None,
            _show_progress=False,
            _output_dir=None,
            pairs=test_pairs,
            api_key=test_api_key,
            exchange=test_exchange,
            start_date=start_session,
            end_date=end_session,
        )

        asset_db_writer.write.assert_called_once()
        args = asset_db_writer.write.call_args[1]
        metadata: pd.DataFrame = args["equities"]
        assert len(metadata) == len(test_pairs)
        for sid, row in metadata.iterrows():
            assert row["symbol"] == test_pairs[sid].symbol  # type: ignore
            assert row["calendar_name"] == CALENDAR_24_7

        def check_writer(writer: MockWriter):
            # noinspection PyUnresolvedReferences
            # type: ignore
            writer.write.assert_has_calls(
                [call([(i, test_pricing_data)]) for i in range(len(test_pairs))]
            )

        check_writer(daily_bar_writer)
        check_writer(minute_bar_writer)

        adjustment_writer.write.assert_called_once()
        args = adjustment_writer.write.call_args[1]
        pd.testing.assert_frame_equal(args["splits"], tb._no_splits())
        pd.testing.assert_frame_equal(args["dividends"], tb._no_dividends())

    def test_data_pipeline(self, mocker):
        start_date = "2010-01-01"
        end_date = "2021-01-01"
        start_session = pd.Timestamp(start_date)
        end_session = pd.Timestamp(end_date)

        test_files_by_asset = {
            Asset("ETH-USD"): ["quotes1.csv.gz", "quotes2.csv.gz"],
            Asset("BTC-USD"): ["quotes3.csv.gz", "quotes4.csv.gz"],
        }
        test_pairs = list(test_files_by_asset.keys())
        test_frequency = "1Min"
        test_pricing_data = empty_pricing_data(start_date, end_date)

        def get_test_filenames(asset: Asset, *_args) -> Iterator[str]:
            return iter(test_files_by_asset[asset])

        mocker.patch(
            "zipline_tardis_bundle._resample_and_merge",
            return_value=test_pricing_data,
        )
        mocker.patch(
            "zipline_tardis_bundle.tardis_files",
            side_effect=get_test_filenames,
        )
        mocker.patch("os.scandir", return_value=None)

        pipeline = tb._data_pipeline(
            test_pairs,
            start_session,
            end_session,
            "coinbase",
            test_frequency,
        )
        result = list(pipeline)

        assert len(result) == len(test_pairs)
        assert len({sid for sid, _, _ in result}) == len(test_pairs)

        for sid, pricing_data, metadata in result:
            pd.testing.assert_frame_equal(pricing_data, test_pricing_data)
            assert metadata[3] == test_pairs[sid].symbol

    def test_filter_quotes_data(self):
        df1 = empty_pricing_data("2012-01-01", "2012-01-02", "2012-01-03")
        result = tb._clean_quotes_data(
            tb._ResampleData("coinbase_quotes_2012-01-02_ETH-USD.csv.gz", df1)
        )
        assert result.dfr.index[0].date() == datetime.date(2012, 1, 2)
        assert result.dfr.index[-1].date() == datetime.date(2012, 1, 2)

    def test_ingest_and_backtest(self, mocker, zipline_environment):
        test_bundle_name = "test-tardis-bundle"

        # Test data files are already provided in the repo
        #  so patch download_quotes_data to do nothing.
        mocker.patch(
            "zipline_tardis_bundle.download_quotes_data",
            return_value=None,
        )
        mocker.patch(
            "zipline_tardis_bundle.CSV_DIR",
            "./tests/data/tardis_bundle",
        )
        trading_calendar = ingest(
            zipline_environment,
            test_bundle_name,
            test_pairs=["ETH-USD"],
            test_api_key="TEST-API-KEY",
            test_exchange="coinbase",
            test_start_date=pd.Timestamp("2022-01-01"),
            test_end_date=pd.Timestamp("2022-01-03"),
            show_progress=True,
        )

        perf = run_backtest(
            zipline_environment,
            test_bundle_name,
            trading_calendar,
            test_algo_file="./tests/zipline_strategy.py",
            test_capital_base=100000,
            test_data_frequency="minute",
        )

        assert perf is not None
        assert "ETH" in perf.columns
        assert len(perf["ETH"]) == 2


# pylint: disable=too-many-locals
def ingest(
    environ: dict,
    test_bundle_name: str,
    test_pairs: List[str],
    test_api_key: str,
    test_exchange: str,
    test_start_date: pd.Timestamp,
    test_end_date: pd.Timestamp,
    show_progress: bool,
) -> ExchangeCalendar:
    register(
        test_bundle_name,
        tardis_ingester(
            pairs=strs_to_assets(test_pairs),
            api_key=test_api_key,
            exchange=test_exchange,
            start_date=to_tardis_date(test_start_date),
            end_date=to_tardis_date(test_end_date),
        ),
        calendar_name="24/7",
        minutes_per_day=1440,
    )

    bundle = TardisBundle(
        strs_to_assets(test_pairs),
        test_api_key,
        test_exchange,
        test_start_date,
        test_end_date,
    )

    trading_calendar = get_calendar("24/7")

    start_session = bundle.start_session
    end_session = bundle.end_session

    if start_session is None or start_session < trading_calendar.first_session:
        start_session = trading_calendar.first_session

    if end_session is None or end_session > trading_calendar.last_session:
        end_session = trading_calendar.last_session

    time_now = pd.Timestamp("2023-01-01 12:00 UTC")
    time_now = time_now.tz_convert("utc").tz_localize(None)

    time_str = to_bundle_ingest_dirname(time_now)
    cachepath = cache_path(test_bundle_name, environ=environ)
    pth.ensure_directory(pth.data_path([test_bundle_name, time_str], environ=environ))
    pth.ensure_directory(cachepath)
    with dataframe_cache(
        cachepath, clean_on_failure=False
    ) as cache, ExitStack() as stack:
        # we use `cleanup_on_failure=False` so that we don't purge the
        # cache directory if the load fails in the middle
        if bundle.create_writers:
            working_directory = stack.enter_context(
                working_dir(pth.data_path([], environ=environ))
            )
            daily_bars_path = working_directory.ensure_dir(
                *daily_equity_relative(test_bundle_name, time_str)
            )
            daily_bar_writer = BcolzDailyBarWriter(
                daily_bars_path,
                trading_calendar,
                start_session,
                end_session,
            )
            # Do an empty write to ensure that the daily ctables exist
            # when we create the SQLiteAdjustmentWriter below. The
            # SQLiteAdjustmentWriter needs to open the daily ctables so
            # that it can compute the adjustment ratios for the dividends.

            daily_bar_writer.write(())
            minute_bar_writer = BcolzMinuteBarWriter(
                working_directory.ensure_dir(
                    *minute_equity_relative(test_bundle_name, time_str)
                ),
                trading_calendar,
                start_session,
                end_session,
                minutes_per_day=bundle.minutes_per_day,
            )
            assets_db_path = working_directory.getpath(
                *asset_db_relative(test_bundle_name, time_str)
            )
            asset_db_writer = AssetDBWriter(assets_db_path)

            adjustment_db_writer = stack.enter_context(
                SQLiteAdjustmentWriter(
                    working_directory.getpath(
                        *adjustment_db_relative(test_bundle_name, time_str)
                    ),
                    BcolzDailyBarReader(daily_bars_path),
                    overwrite=True,
                )
            )
        else:
            daily_bar_writer = None
            minute_bar_writer = None
            asset_db_writer = None
            adjustment_db_writer = None

        logging.info("Ingesting %s", test_bundle_name)
        bundle.ingest(
            environ,
            asset_db_writer,
            minute_bar_writer,
            daily_bar_writer,
            adjustment_db_writer,
            trading_calendar,
            start_session,
            end_session,
            cache,
            show_progress,
            pth.data_path([test_bundle_name, time_str], environ=environ),
        )

        return trading_calendar


# pylint: disable=too-many-locals
def run_backtest(
    environ: dict,
    test_bundle_name: str,
    trading_calendar: ExchangeCalendar,
    test_algo_file: str,
    test_capital_base: int,
    test_data_frequency: str,
) -> pd.DataFrame:
    bundle_data = bundles.load(
        test_bundle_name,
        environ,
        None,
    )

    start = pd.Timestamp("2022-01-01")
    end = pd.Timestamp("2022-01-02")

    # date parameter validation
    assert trading_calendar.sessions_distance(start, end) >= 1

    benchmark_spec = BenchmarkSpec.from_cli_params(
        no_benchmark=True,
        benchmark_sid=None,
        benchmark_symbol=None,
        benchmark_file=None,
    )

    benchmark_sid, benchmark_returns = benchmark_spec.resolve(
        asset_finder=bundle_data.asset_finder,
        start_date=start,
        end_date=end,
    )

    namespace: dict = dict()

    def read_algo():
        with open(test_algo_file, "r", encoding="UTF-8") as algo_file:
            result = algo_file.read()
        return result

    algo_text = read_algo()

    first_trading_day = bundle_data.equity_minute_bar_reader.first_trading_day

    data = DataPortal(
        bundle_data.asset_finder,
        trading_calendar=trading_calendar,
        first_trading_day=first_trading_day,
        equity_minute_reader=bundle_data.equity_minute_bar_reader,
        equity_daily_reader=bundle_data.equity_daily_bar_reader,
        adjustment_reader=bundle_data.adjustment_reader,
        future_minute_reader=bundle_data.equity_minute_bar_reader,
        future_daily_reader=bundle_data.equity_daily_bar_reader,
    )

    pipeline_loader = USEquityPricingLoader.without_fx(
        bundle_data.equity_daily_bar_reader,
        bundle_data.adjustment_reader,
    )

    def choose_loader(_column):
        return pipeline_loader

    metrics_set = metrics.load("default")
    blotter: object = load(Blotter, "default")

    return TradingAlgorithm(
        namespace=namespace,
        data_portal=data,
        get_pipeline_loader=choose_loader,
        trading_calendar=trading_calendar,
        sim_params=SimulationParameters(
            start_session=start,
            end_session=end,
            trading_calendar=trading_calendar,
            capital_base=test_capital_base,
            data_frequency=test_data_frequency,
        ),
        metrics_set=metrics_set,
        blotter=blotter,
        benchmark_returns=benchmark_returns,
        benchmark_sid=benchmark_sid,
        algo_filename=test_algo_file,
        script=algo_text,
    ).run()


def test_utc_timestamp():
    test_date_str = "2012-03-03"
    test_date = datetime.date(2012, 3, 3)
    result = utc_timestamp(test_date_str)
    assert result.tzinfo is timezone.utc
    assert result.date() == test_date

    result_ts = utc_timestamp(pd.Timestamp(test_date_str))
    assert result_ts.tzinfo is timezone.utc
    assert result.date() == test_date


def test_assets_to_strs():
    assets = [Asset(str(n)) for n in range(10)]
    result = assets_to_strs(assets)
    assert result == [str(n) for n in range(10)]


def test_strs_to_assets():
    strs = [str(n) for n in range(10)]
    result = strs_to_assets(strs)
    assert result == [Asset(str(n)) for n in range(10)]
