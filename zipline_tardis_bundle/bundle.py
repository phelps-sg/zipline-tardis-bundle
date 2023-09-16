#
# Copyright (C) 2023 Steve Phelps.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations

import datetime
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import (
    Any,
    Callable,
    Iterator,
    List,
    Mapping,
    Optional,
    Pattern,
    Sized,
    Tuple,
)
from urllib.error import HTTPError

import numpy as np
import pandas as pd
from fn import F
from ray.util.client import RayAPIStub, ray
from tardis_dev import datasets
from zipline.assets import AssetDBWriter
from zipline.data.adjustments import SQLiteAdjustmentWriter
from zipline.data.bcolz_daily_bars import BcolzDailyBarWriter
from zipline.data.bcolz_minute_bars import BcolzMinuteBarWriter
from zipline.data.bundles import register

from zipline_tardis_bundle.util import (
    Asset,
    assets_to_strs,
    earliest_date,
    latest_date,
    strs_to_assets,
    to_tardis_date,
    utc_timestamp,
)

CSV_DIR = os.environ.get("ZIPLINE_TARDIS_DIR") or "./data/tardis_bundle"
CALENDAR_24_7 = "24/7"
EMPTY_FILE_SIZE = 20  # The size in bytes of an empty .csv.gz file

MINUTES_PER_DAY = 60 * 24

_Metadata = Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, str, str, str]
_IngestPipeline = Iterator[Tuple[int, pd.DataFrame, _Metadata]]

logger = logging.getLogger(__name__)


@dataclass
class _ResampleData:
    filename: str
    dfr: pd.DataFrame

    def new_data(self, new_dfr: pd.DataFrame) -> _ResampleData:
        return _ResampleData(self.filename, new_dfr)


def tardis_ingester(
    pairs: List[Asset], api_key: str, exchange: str, start_date: str, end_date: str
) -> Callable:
    return TardisBundle(
        pairs, api_key, exchange, pd.Timestamp(start_date), pd.Timestamp(end_date)
    ).ingest


def register_tardis_bundle(
    bundle_name: str,
    pairs: List[str],
    api_key: str,
    exchange: str,
    start_date: str,
    end_date: str,
) -> None:
    register(
        bundle_name,
        tardis_ingester(strs_to_assets(pairs), api_key, exchange, start_date, end_date),
        start_session=pd.Timestamp(start_date),
        end_session=pd.Timestamp(end_date),
        calendar_name=CALENDAR_24_7,
        minutes_per_day=MINUTES_PER_DAY,
    )


# pylint: disable=too-few-public-methods
class TardisBundle:
    def __init__(
        self,
        pairs: List[Asset],
        api_key: str,
        exchange: str,
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
    ):
        self.pairs = pairs
        self.api_key = api_key
        self.exchange = exchange
        self.start_date = start_date
        self.end_date = end_date
        self.calendar_name = CALENDAR_24_7
        self.start_session = None
        self.end_session = None
        self.create_writers = True
        self.minutes_per_day = MINUTES_PER_DAY

    def ingest(
        self,
        environ: Mapping[str, str],
        asset_db_writer: AssetDBWriter,
        minute_bar_writer: BcolzMinuteBarWriter,
        daily_bar_writer: BcolzDailyBarWriter,
        adjustment_writer: SQLiteAdjustmentWriter,
        calendar: object,
        start_session: pd.Timestamp,
        end_session: pd.Timestamp,
        cache: object,
        show_progress: bool,
        output_dir: str,
    ) -> None:
        tardis_bundle(
            environ,
            asset_db_writer,
            minute_bar_writer,
            daily_bar_writer,
            adjustment_writer,
            calendar,
            start_session,
            end_session,
            cache,
            show_progress,
            output_dir,
            self.pairs,
            self.api_key,
            self.exchange,
            self.start_date,
            self.end_date,
        )


# pylint: disable=too-many-locals
def tardis_bundle(
    environ: Mapping[str, str],
    asset_db_writer: AssetDBWriter,
    minute_bar_writer: BcolzMinuteBarWriter,
    daily_bar_writer: BcolzDailyBarWriter,
    adjustment_writer: SQLiteAdjustmentWriter,
    _calendar: object,
    start_session: pd.Timestamp,
    end_session: pd.Timestamp,
    _cache: object,
    _show_progress: bool,
    _output_dir: object,
    pairs: List[Asset],
    api_key: str,
    exchange: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    ray_client: RayAPIStub = ray,
) -> None:
    """
    Build a backtesting data bundle for Tardis data.
    """
    if not api_key:
        api_key = environ.get("TARDIS_API_KEY")
        if not api_key:
            raise ValueError("TARDIS_API_KEY environment variable is not set")

    logger.debug("start_session = %s", start_session)
    logger.debug("end_session = %s", end_session)

    if start_session < start_date:
        logger.debug("Setting start_session to %s", start_date)
        start_session = start_date

    if end_session > end_date:
        logger.debug("Setting end_session to %s", end_date)
        end_session = end_date

    _download_data(start_session, end_session, api_key, pairs, exchange)

    logger.info("Ingesting Tardis pricing data... ")
    ray_client.init()

    minute_pipeline = _data_pipeline(
        pairs, start_session, end_session, exchange, frequency="1Min"
    )
    daily_pipeline = _data_pipeline(
        pairs, start_session, end_session, exchange, frequency="1D"
    )

    metadata_df = _write_pipeline(minute_bar_writer, minute_pipeline, pairs)
    _ = _write_pipeline(daily_bar_writer, daily_pipeline, pairs)

    asset_db_writer.write(equities=metadata_df)

    # There are no adjustments for crypto assets but Zipline
    #  still requires empty tables for splits and dividends
    adjustment_writer.write(splits=_no_splits(), dividends=_no_dividends())

    logger.info("Ingestion of Tardis data complete.")
    ray_client.shutdown()


@lru_cache
def _tardis_regex(exchange: str = "[a-zA-Z0-9]+") -> Pattern:
    return re.compile(
        f"^{exchange}" + r"_quotes_([0-9]+-[0-9]+-[0-9]+)_([A-Z\-0-9]+).csv.gz$"
    )


def _date_as_str(tardis_filename: str) -> str:
    return _tardis_regex().match(tardis_filename).group(1)


def _date_of(tardis_filename: str) -> datetime.date:
    return pd.Timestamp(_date_as_str(tardis_filename)).date()


def tardis_files(
    asset: Asset,
    exchange: str,
    from_date: pd.Timestamp,
    to_date: pd.Timestamp,
    directory: Iterator[Any],
) -> Iterator[str]:
    """
    Transform an iterator over directory entries for files downloaded from Tardis into an
    iterator over the filenames that correspond to the specified asset, date range
    and exchange.

    @param asset: The asset, e.g. "ETH-USD"
    @param exchange: The exchange, e.g. "coinbase"
    @param directory: An iterator over directory entries
    @param from_date: The earliest date to include
    @param to_date: The latest date to include
    @return: An iterator over the corresponding filenames
    """
    rx = _tardis_regex(exchange)
    for entry in directory:
        if entry.is_file() and entry.stat().st_size > EMPTY_FILE_SIZE:
            match = rx.match(entry.name)
            if match is not None:
                matched_asset = Asset(match.group(2))
                matched_date = pd.Timestamp(match.group(1))
                if from_date <= matched_date <= to_date:
                    if matched_asset == asset:
                        yield entry.name


def download_quotes_data(
    exchange: str,
    start_session: pd.Timestamp,
    end_session: pd.Timestamp,
    pairs: List[Asset],
    api_key: str,
    csv_dir: str,
) -> None:
    """
    Ensure all raw data files for the specified pairs, exchange and date range are available
    in the specified directory.  Any files that are not already presented will be downloaded
    from Tardis.

    @param exchange: The exchange to request data for, e.g. "coinbase"
    @param start_session: The earliest date
    @param end_session: The latest date
    @param pairs: A list of pairs to download
    @param api_key: The Tardis API key
    @param csv_dir: The directory to download files to
    """
    logger.info(
        "Downloading any uncached Tardis data for %s on %s between %s and %s... ",
        ", ".join(assets_to_strs(pairs)),
        exchange,
        start_session,
        end_session,
    )
    # Note that this function only downloads files that are not already present.
    datasets.download(
        exchange=exchange,
        data_types=["quotes"],
        from_date=to_tardis_date(start_session),
        to_date=to_tardis_date(end_session),
        symbols=assets_to_strs(pairs),
        api_key=api_key,
        download_dir=csv_dir,
        concurrency=256,
    )
    logger.info("Downloading complete.")


def _write_pipeline(
    writer: BcolzMinuteBarWriter | BcolzDailyBarWriter,
    pipeline: _IngestPipeline,
    pairs: Sized,
) -> pd.DataFrame:
    metadata_df = _generate_empty_metadata(pairs)

    for sid, data, metadata in pipeline:
        writer.write([(sid, data)])
        metadata_df.iloc[sid] = metadata  # type: ignore

    return metadata_df


def _generate_empty_metadata(pairs: Sized) -> pd.DataFrame:
    """
    Generate the metadata table required by Zipline which
    specifies metadata attributes for each asset in the
    bundle.  The returned data frame will have the
    correct dimensions, asset names and columns, but
    the actual metadata entries will be null and are
    meant to be populated later.

    @param pairs: The list of pairs to generate metadata for
    @return A pandas data frame containing empty metadata
    """
    data_types = [
        ("start_date", "datetime64[ns]"),
        ("end_date", "datetime64[ns]"),
        ("auto_close_date", "datetime64[ns]"),
        ("symbol", "object"),
        ("calendar_name", "object"),
        ("exchange", "object"),
    ]
    return pd.DataFrame(np.empty(len(pairs), dtype=data_types))


def _generate_metadata(pricing_data: pd.DataFrame, asset: Asset) -> _Metadata:
    """
    Generate Zipline metadata for the specified asset and pricing data.

    @param pricing_data: The pricing data that will be ingested into Zipline
    @param asset: The asset
    @return: A row of metadata that can be written to the Zipline asset DB
    """
    start_date = pricing_data.index[0]
    end_date = pricing_data.index[-1]
    return (  # type: ignore
        start_date,
        end_date,
        end_date,
        asset.symbol,
        CALENDAR_24_7,
        CALENDAR_24_7,
    )


def _no_dividends() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "sid",
            "amount",
            "ex_date",
            "record_date",
            "declared_date",
            "pay_date",
        ]
    )


def _no_splits() -> pd.DataFrame:
    return pd.DataFrame(columns=["sid", "ratio", "effective_date"])


def _read_quotes_data(filename: str, csv_dir: str) -> _ResampleData:
    """
    Read raw Tardis quotes data from the specified filename in the
    specified directory as a pandas data frame.

    @param csv_dir: The directory containing downloaded CSV files
    @param filename: The filename to read from
    @return: A pandas data frame containing the read data
    """
    return _ResampleData(
        filename, dfr=pd.read_csv(os.path.join(csv_dir, filename), parse_dates=False)
    )


def _index_to_datetime(data: _ResampleData) -> _ResampleData:
    # noinspection PyTypeChecker
    data.dfr.set_index(
        pd.to_datetime(data.dfr["timestamp"] * 1000, utc=True), inplace=True
    )
    return data


def _convert_to_ohlc(data: _ResampleData, freq: str = "1Min") -> _ResampleData:
    """
    Convert raw quotes data from Tardis into the 1-minute
    Open/High/Low/Close (OHLC) format required by Zipline.
    OHLC prices are computed from the mid-price, and volume
    is summed over one-minute windows.
    """
    data.dfr["mid"] = (data.dfr["bid_price"] + data.dfr["ask_price"]) / 2.0
    data.dfr["volume"] = data.dfr["ask_amount"] + data.dfr["bid_amount"]
    mid_price = data.dfr["mid"].resample(freq).ohlc()
    volume = data.dfr["volume"].resample(freq).sum()
    return data.new_data(pd.concat([mid_price, volume], axis=1))


def _clean_quotes_data(data: _ResampleData) -> _ResampleData:
    # some quotes files begin with a few records from the previous day
    return data.new_data(
        data.dfr[data.dfr.index.map(lambda x: x.date()) == _date_of(data.filename)]
    )


def _read_and_convert(filename: str, csv_dir: str, frequency: str) -> pd.DataFrame:
    def read(f: str) -> _ResampleData:
        return _read_quotes_data(f, csv_dir)

    def resample(data: _ResampleData) -> _ResampleData:
        return _convert_to_ohlc(data, frequency)

    pipeline: Callable[[str], _ResampleData] = (
        F() >> read >> _index_to_datetime >> _clean_quotes_data >> resample
    )
    return pipeline(filename).dfr


def _resample_and_merge(
    csv_dir: str,
    filenames: Iterator[str],
    frequency: str,
    ray_client: RayAPIStub = ray,
    to_future: Callable[
        [Callable[[str, str, str], pd.DataFrame]],
        Callable[[str, str, str], pd.DataFrame],
    ] = lambda f: ray.remote(f).remote,
) -> Optional[pd.DataFrame]:
    """
    Load the Tardis data in the supplied CSV file names.  The file names
    should correspond to files which contain data for the same asset, but
    over different days.  The data is then ETL-ed to the price/volume
    OHLC format required by Zipline, and we return a single merged data-frame
    containing all the data. By default, we use the ray library to process each
    file in parallel, but optional named arguments can be used to easily inject
    mocks for testing.

    @param csv_dir: The path of the directory containing the files to load
    @param filenames: The list of filenames to load
    @param ray_client: The ray client to use for parallel extraction
    @param to_future: A higher-order function used to obtain a remote for ray
    @return: A single data-frame containing the ETL-ed data.
    """
    process = to_future(_read_and_convert)
    data_frames = ray_client.get(
        [process(filename, csv_dir, frequency) for filename in filenames]
    )
    if len(data_frames) == 0:
        return None
    result = pd.concat(data_frames, axis=0)
    result.sort_index(inplace=True)
    return result


def _within_range(
    start_session: pd.Timestamp,
    end_session: pd.Timestamp,
    pricing_data: pd.DataFrame,
) -> bool:
    start = utc_timestamp(start_session)
    end = utc_timestamp(end_session)
    return (earliest_date(pricing_data) >= start) and (latest_date(pricing_data) <= end)


def _download_data(
    start_session: pd.Timestamp,
    end_session: pd.Timestamp,
    api_key: str,
    pairs: List[Asset],
    exchange: str,
) -> None:
    try:
        if not os.path.exists(CSV_DIR):
            os.makedirs(CSV_DIR)

        download_quotes_data(
            exchange, start_session, end_session, pairs, api_key, CSV_DIR
        )
    except HTTPError as error:
        logger.error(error)
        raise error


def _data_pipeline(
    pairs: List[Asset],
    start_session: pd.Timestamp,
    end_session: pd.Timestamp,
    exchange: str,
    frequency: str,
) -> _IngestPipeline:
    for sid, asset in enumerate(pairs):
        logger.info(
            "Ingesting data for %s at %s frequency... ", asset.symbol, frequency
        )
        file_names = tardis_files(
            asset, exchange, start_session, end_session, os.scandir(CSV_DIR)
        )
        pricing_data = _resample_and_merge(CSV_DIR, file_names, frequency)
        if pricing_data is not None:
            if not _within_range(start_session, end_session, pricing_data):
                logger.warning(
                    (
                        "Data with timestamps %s to %s outside "
                        "of specified range %s to %s for asset %s"
                    ),
                    earliest_date(pricing_data),
                    latest_date(pricing_data),
                    start_session,
                    end_session,
                    asset,
                )
            logger.info("Ingestion for %s complete.", asset.symbol)
            yield sid, pricing_data, _generate_metadata(pricing_data, asset)
        else:
            logger.warning(
                "No non-empty data files for %s at %s frequency",
                asset.symbol,
                frequency,
            )
