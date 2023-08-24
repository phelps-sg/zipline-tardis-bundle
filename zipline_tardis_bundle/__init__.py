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
"""Tardis bundle.

This module provides functionality for importing Tardis data into zipline.
See:
    - https://zipline.ml4trading.io/bundles.html
    - https://tardis.dev/
"""
from __future__ import annotations

import logging

from .bundle import (
    CALENDAR_24_7,
    Asset,
    TardisBundle,
    register_tardis_bundle,
    tardis_bundle,
)
from .util import live_symbols_since

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
