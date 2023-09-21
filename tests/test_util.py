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
