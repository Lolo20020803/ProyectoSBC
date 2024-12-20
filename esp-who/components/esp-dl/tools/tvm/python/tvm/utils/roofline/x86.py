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
"""Estimate peak flops and bandwidth for x86 devices"""
import functools
import re
from typing import Dict, Optional, Tuple

import numpy as np

from ... import build, get_global_func, nd, transform
from ...contrib import utils
from ...rpc.base import RPC_SESS_MASK
from ...rpc.client import RPCSession
from ...runtime import DataType, Device, num_threads
from ...script import tir as T
from ...target import Target, x86
from ...tir import PrimFunc
from . import registry


def _detect_vec_width_registers(
    target: Target, vec_width: Optional[int], num_vector_registers: Optional[int]
):
    """Get the vector width and number of vector registers for a target.

    Parameters
    ----------
    target : Target
        Target to detect vector width and registers for.
    vec_width : Optional[int]
        If None, try and detect vector width from target. Otherwise provided input is used.
    num_vector_registers : Optional[int]
        If None, try and number of vector registers from target. Otherwise provided input is used.

    Returns
    -------
    vec_width: int
        Width of a vector register on `target` in bytes.
    num_vector_registers: int
        Number of vector registers on `target`.
    """
    if vec_width is None:
        # Only implemented for x86 so far...
        if (
            str(target.kind) == "llvm"
            and target.device_name == ""
            and len(target.keys) == 1
            and target.keys[0] == "cpu"
        ):
            with target:
                vec_width = x86.get_simd_32bit_lanes() * 4  # in number of bytes
        else:
            raise RuntimeError(f"Cannot determine vector width for target {target}")
    if num_vector_registers is None:
        if target.device_name == "":  # indicates x86
            num_vector_registers = 16  # Assuming for all platforms, probably wrong on older ones
        else:
            raise RuntimeError(f"Cannot determine number of vector registers for target {target}")
    return vec_width, num_vector_registers


@functools.lru_cache(maxsize=None)
def estimate_peak_fma_vector_flops(
    target: Target,
    dev: Device,
    remote: Optional[RPCSession],
    dtype: DataType,
    vec_width: Optional[int] = None,
    num_vector_registers: Optional[int] = None,
):
    """Estimate peak flops assuming vector fma instructions and no explicit
    intrinsics. See estimate_peak_fma_flops.
    """

    @T.prim_func
    def peakflops_fma_tir(
        a: T.handle,
        vec_width: T.int32,
        iters: T.int32,
        num_vector_registers: T.int32,
        threads: T.int32,
    ) -> None:
        # pylint: disable=invalid-name, missing-function-docstring
        A = T.match_buffer(a, [threads, num_vector_registers, vec_width], dtype)
        for t in T.parallel(threads):
            for _j in range(iters):
                for l in T.unroll(num_vector_registers):
                    # We want to use as few registers as possible, so we perform
                    # all operations on the same element
                    for k in T.vectorized(vec_width):
                        A[t, l, k] = A[t, l, k] * A[t, l, k] + A[t, l, k]

    vec_width, num_vector_registers = _detect_vec_width_registers(
        target, vec_width, num_vector_registers
    )
    vec_width //= DataType(dtype).bits // 8
    iters = 1000000
    nthreads = num_threads()
    specialized = peakflops_fma_tir.specialize(
        {
            peakflops_fma_tir.params[1]: vec_width,
            peakflops_fma_tir.params[2]: iters,
            peakflops_fma_tir.params[3]: num_vector_registers,
            peakflops_fma_tir.params[4]: nthreads,
        }
    )
    with transform.PassContext(opt_level=3):
        f = build(specialized, target=target)

    # upload to remote if running over rpc
    if dev.device_type >= RPC_SESS_MASK:
        if remote is None:
            raise RuntimeError("A RPCSession must be provided when using a remote device.")
        temp = utils.tempdir()
        path = temp.relpath("peak_fma_flops.tar")
        f.export_library(path)
        remote.upload(path)
        f = remote.load_module("peak_fma_flops.tar")
        random_fill = remote.get_function("tvm.contrib.random.random_fill")
    else:
        random_fill = get_global_func("tvm.contrib.random.random_fill")
    assert random_fill, "Please make sure USE_RANDOM is ON in config.cmake"

    a = nd.empty((nthreads, num_vector_registers, vec_width), dtype=dtype, device=dev)
    random_fill(a)
    times = f.time_evaluator(f.entry_name, dev, repeat=100, number=1)(a)
    flops = 2 * vec_width * num_vector_registers * nthreads * iters  # fma is two flops
    return flops / times.min


@registry.estimate_peak_flops.register("cpu")
def estimate_peak_fma_flops(
    func: PrimFunc,
    features: Dict[str, np.ndarray],
    target: Target,
    dev: Device,
    remote: Optional[RPCSession],
    vec_width: Optional[int] = None,
    num_vector_registers: Optional[int] = None,
) -> Tuple[float, float, str]:
    """
    Estimate the maximum number of FLOP/s this target/device combo is capable
    of reaching by running a test program. This assumes vectorized FMA
    (fused-multiply-add) instructions.


    Parameters
    ----------
    func : PrimFunc
        Function to estimate peak flops for. Used to check if a specific kind
        intrinsic or dtype could be used with this function.
    features : Dict[str, np.ndarry]
        Features extracted from `func`. Used to check if a specific kind
        intrinsic or dtype could be used with this function.
    target : Target
        Target to run on. This should be as specific to the actual hardware as
        possible to make sure that LLVM generates the best vector code.
    dev : Device
        Device to run on.
    remote : Optional[RPCSession]
      Remote session used to upload artifacts for runtime evaluation. Must be
      the same session used to create `dev`.
    vec_width : Optional[int]
        Vector width of SIMD units on the underlying hardware. Will try to
        infer if no value is provided.
    num_vector_registers : Optional[int]
        Number of vector registers on the underlying hardware. Will try to
        infer if no value is provided.

    Returns
    -------
    flops : float
        Estimated number of flops used by `func`.
    peak_flops : float
        Approximate sustained FLOP/s of this target/device combo assuming
        vectorized FMA instructions. Each FMA operation counts as two FLOPs.
    name : str
        Dtype/intrinsic used by `func` to achieve peak flops.
    """
    # assume that the first argument's dtype is the one we want
    dtype = list(func.buffer_map.values())[0].dtype
    if "int" in dtype:
        flops = np.sum(
            features["int_addsub"]
            + features["int_mul"]
            + features["int_mad"] * 2
            + features["int_divmod"]
        )
    else:
        flops = np.sum(
            features["float_addsub"]
            + features["float_mul"]
            + features["float_mad"] * 2
            + features["float_divmod"]
        )
    peak_flops = estimate_peak_fma_vector_flops(
        target, dev, remote, dtype, vec_width, num_vector_registers
    )
    return flops, peak_flops, f"{dtype} FMA"


@T.prim_func
def peak_bandwidth_tir(a: T.handle, b: T.handle, threads: T.int32, vec_width: T.int32) -> None:
    # pylint: disable=invalid-name, missing-function-docstring
    N = T.int32()
    A = T.match_buffer(a, [threads, N, 4, vec_width], "float32")
    B = T.match_buffer(b, [threads, 4, vec_width], "float32")
    # Parallelism is necessary to hit all cores/nodes
    for i in T.parallel(threads):
        for k in T.serial(N):
            for l in T.unroll(4):
                # vectorized load is necessary to hit peak bandwidth
                for j in T.vectorized(vec_width):
                    # += is necessary to introduce a data dependency for all
                    # elements of A, preventing the backend from removing the
                    # `k` loop and setting `k` to the loop extent.
                    B[i, l, j] += A[i, k, l, j]


@functools.lru_cache(maxsize=None)
def estimate_peak_bandwidth_dram(
    target: Target,
    dev: Device,
    remote: Optional[RPCSession],
    vec_width: Optional[int] = None,
) -> float:
    """Estimate peak bandwidth for DRAM. See estimate_peak_bandwidth."""
    vec_width, _ = _detect_vec_width_registers(target, vec_width, 1)
    specialized = peak_bandwidth_tir.specialize(
        {
            peak_bandwidth_tir.params[3]: vec_width,
        }
    )
    with transform.PassContext(opt_level=3):
        f = build(specialized, target=target)

    # upload to remote if running over rpc
    if dev.device_type >= RPC_SESS_MASK:
        if remote is None:
            raise RuntimeError("A RPCSession must be provided when using a remote device.")
        temp = utils.tempdir()
        path = temp.relpath("peak_bandwidth.tar")
        f.export_library(path)
        remote.upload(path)
        f = remote.load_module("peak_bandwidth.tar")
        random_fill = remote.get_function("tvm.contrib.random.random_fill")
    else:
        random_fill = get_global_func("tvm.contrib.random.random_fill")
    assert random_fill, "Please make sure USE_RANDOM is ON in config.cmake"

    threads = num_threads()
    # Data size needs to be larger than last level of cache. We don't have a
    # way of getting cache sizes, so this number should give us a large enough
    # size.
    size = 10**8 // (4 * threads * vec_width)
    a = nd.empty((threads, size, 4, vec_width), dtype="float32", device=dev)
    random_fill(a)
    b = nd.empty((threads, 4, vec_width), dtype="float32", device=dev)
    random_fill(b)
    times = f.time_evaluator(f.entry_name, dev, repeat=10, number=1)(a, b, threads)
    return a.numpy().size * 4 / times.min  # 4 bytes per float32


@registry.estimate_peak_bandwidth.register("cpu")
def estimate_peak_bandwidth(
    func: PrimFunc,  # pylint: disable=unused-argument
    features: Dict[str, np.ndarray],
    target: Target,
    dev: Device,
    remote: Optional[RPCSession],
    vec_width: Optional[int] = None,
) -> Tuple[float, float, str]:
    """Estimate peak memory bandwidth of a target/device combo.

    Peak bandwidth is estimated by running a small experiment on the underlying
    hardware. The peak bandwidth measurement assumes that vector instructions
    are being used to load the data.

    Parameters
    ----------
    func : PrimFunc
        Function to estimate peak bandwidth for. Used to check if a specific
        kind of memory could be used with this function.
    features : Dict[str, np.ndarry]
        Features extracted from `func`. Used to check if a specific kind of
        memory could be used with this function.
    target : Target
        Target to use for measurement. This target should be as specific to the
        underlying hardware as possible.
    dev : Device
        Device to measure peak bandwidth on.
    remote : Optional[RPCSession]
      Remote session used to upload artifacts for runtime evaluation. Must be
      the same session used to create `dev`.
    vec_width : Optional[int]
        Vector unit width, determined from target if not supplied.

    Returns
    -------
    loaded_bytes : float
        Estimated bytes loaded by `func`.
    peak_bandwidth : float
        Peak memory bandwidth in bytes/seconds.
    name : str
        Name of the memory being used.
    """
    # Ideally we'd be able to use this code to measure peak bandwidth of the
    # different cache levels. If we could just generate load commands, then we
    # could use those in a tight loop. Instead we need some code that is
    # limited on the cache bandwidth. With the L1 cache we need an operation
    # that has a very low arithmetic intensity and we haven't come up with one
    # yet.
    peak_bandwidth = estimate_peak_bandwidth_dram(target, dev, remote, vec_width)
    loaded_bytes = sum(
        [np.sum(x) for (k, x) in features.items() if re.match(r"^B[0-9]+\.bytes$", k) is not None]
    )
    return loaded_bytes, peak_bandwidth, "DRAM"
