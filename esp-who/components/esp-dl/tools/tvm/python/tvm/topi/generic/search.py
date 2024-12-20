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
# pylint: disable=invalid-name, no-member
"""Generic search operators"""
from __future__ import absolute_import as _abs
from .default import default_schedule as _default_schedule


def schedule_argwhere(outs):
    """Schedule for argwhere operator.

    Parameters
    ----------
    outs: Array of Tensor
      The computation graph description of argwhere.

    Returns
    -------
    s: Schedule
      The computation schedule for the op.
    """
    return _default_schedule(outs, False)


def schedule_sparse_fill_empty_rows(outs):
    return _default_schedule(outs, False)


def schedule_unique(outs):
    """Schedule for unique operator.

    Parameters
    ----------
    outs: Array of Tensor
      The computation graph description of unique.

    Returns
    -------
    s: Schedule
      The computation schedule for the op.
    """
    return _default_schedule(outs, False)
