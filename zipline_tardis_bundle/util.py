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
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Set, Union

import pandas as pd
from tardis_dev import get_exchange_details


@dataclass(frozen=True, eq=True)
class Asset:
    symbol: str


@lru_cache
def exchange_details_cached(exchange: str) -> Dict[Any, Any]:
    return get_exchange_details(exchange)


@lru_cache
def all_symbols(exchange: str) -> Set[str]:
    """
    Query the Tardis API to obtain the entire set of symbols for the
    specified exchange.

    @param exchange: The exchange to query
    @return: The entire set of symbols traded on the exchange
    """
    info = exchange_details_cached(exchange)
    return {s["id"] for s in info["availableSymbols"]}


_currency_reg_ex = re.compile(r"^([A-Z0-9]+)-([A-Z0-9]+)$")


@lru_cache
def live_symbols_since(exchange: str, date: str, fiat_currency: str = None) -> Set[str]:
    """
    Query the Tardis API to obtain the set of symbols that are
    currently actively traded and also have historical data
    going back to at least the specified date.

    @param exchange: The exchange to query
    @param date: Symbols must have data going back
        to this date or earlier
    @param fiat_currency: Only include pairs for the specified
        fiat currency
    @return: The corresponding set of symbols
    """
    range_start = utc_timestamp(date)
    info = exchange_details_cached(exchange)
    return {
        s["id"]
        for s in info["availableSymbols"]
        if ("availableTo" not in s)
        and ("availableSince" in s)
        and (pd.Timestamp(s["availableSince"]) <= range_start)
        and (
            (fiat_currency is None)
            or (_currency_reg_ex.match(s["id"]).group(2) == fiat_currency)
        )
    }


def utc_timestamp(date: Union[str, pd.Timestamp]) -> pd.Timestamp:
    return pd.Timestamp(date, tz="UTC")


def strs_to_assets(symbols: Iterable[str]) -> List[Asset]:
    return [Asset(s) for s in symbols]


def assets_to_strs(assets: Iterable[Asset]) -> List[str]:
    return [a.symbol for a in assets]


def earliest_date(result: pd.DataFrame) -> pd.Timestamp:
    return pd.Timestamp(result.index[0])


def latest_date(result: pd.DataFrame) -> pd.Timestamp:
    return pd.Timestamp(result.index[-1])


def to_tardis_date(timestamp: pd.Timestamp) -> str:
    return timestamp.strftime("%Y-%m-%d")
