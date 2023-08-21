#
# Copyright (C) 2024 Steve Phelps.
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
import os
import shutil

ZIPLINE_CONFIG_FILENAME = "extension.py"

if __name__ == "__main__":
    filename = ZIPLINE_CONFIG_FILENAME
    home_dir = os.path.expanduser("~")
    dest_file = os.path.join(home_dir, filename)
    module_dir = os.path.basename(__file__)
    source_file = os.path.join(module_dir, filename)
    shutil.copy(source_file, dest_file)
