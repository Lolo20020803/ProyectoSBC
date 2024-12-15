# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

# pylint: disable=redefined-builtin, wildcard-import
"""Qualcomm Adreno GPU specific declaration and schedules."""
from .conv2d_nchw import *
from .depthwise_conv2d_nchw import *
from .conv2d_nhwc import *
from .depthwise_conv2d_nhwc import *
from .pooling import *
from .conv2d_alter_op import *
from .conv2d_nchw_winograd import *
from .conv2d_nhwc_winograd import *
from .injective import schedule_injective
from .reduction import *
