import datetime

import pandas as pd

from zipline_tardis_bundle.util import (
    Asset,
    assets_to_strs,
    strs_to_assets,
    utc_timestamp,
)


def test_utc_timestamp():
    test_date_str = "2012-03-03"
    test_date = datetime.date(2012, 3, 3)
    result = utc_timestamp(test_date_str)
    assert result.tzinfo is datetime.timezone.utc
    assert result.date() == test_date

    result_ts = utc_timestamp(pd.Timestamp(test_date_str))
    assert result_ts.tzinfo is datetime.timezone.utc
    assert result.date() == test_date


def test_assets_to_strs():
    assets = [Asset(str(n)) for n in range(10)]
    result = assets_to_strs(assets)
    assert result == [str(n) for n in range(10)]


def test_strs_to_assets():
    strs = [str(n) for n in range(10)]
    result = strs_to_assets(strs)
    assert result == [Asset(str(n)) for n in range(10)]
