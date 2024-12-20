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
# pylint: disable=invalid-name, too-many-arguments, too-many-nested-blocks, unused-argument
"""STFT operator"""
from math import pi
import tvm
from tvm import te, tir
from ..utils import ceil_div


def _get_max_threads(batch_row):
    max_threads = tvm.target.Target.current(allow_none=False).max_num_threads
    return tir.min(batch_row, max_threads)


def stft(
    data,
    n_fft,
    hop_length,
    win_length,
    window,
    normalized,
    onesided,
    output_shape,
):
    """
    The STFT computes the Fourier transform of short overlapping windows of the input.
    This gives frequency components of the signal as they change over time.
    Parameters
    ----------
    data : relay.Expr
        Either a 1-D tensor or a 2-D batch tensor.
    n_fft : int
        The size of Fourier transform
    hop_length : int
        The distance between neighboring sliding window frames
    win_length : int
        The size of window frame and STFT filter
    window : relay.Expr
        A 1-D tensor window frame
    normalized : bool
        Whether to return the normalized STFT results
    onesided : bool
        Whether to return onesided result or fill with conjugate symmetry
    Returns
    -------
    output : relay.Expr
        Tensor containing the STFT result
    Examples
    --------
    .. code-block:: python

        data = [1, 2, 3, 4, 5, 6]
        window = [4, 3, 2]
        [n_fft, hop_length, win_length, normalized, onesided] = [3, 3, 3, False, True]
        relay.stft(data, n_fft, hop_length, win_length, window, normalized, onesided)
        -> [[[15.0000,  0.0000], [34.0000,  0.0000]], [[ 4.5000,  0.8660], [ 1.0000, -1.7321]]]
    """

    def gen_ir(
        data_ptr,
        n_fft,
        hop_length,
        win_length,
        window_ptr,
        normalized,
        onesided,
        output_ptr,
    ):
        ib = tir.ir_builder.create()
        data = ib.buffer_ptr(data_ptr)
        window = ib.buffer_ptr(window_ptr)
        output = ib.buffer_ptr(output_ptr)
        max_threads = _get_max_threads(output_ptr.shape[0] * output_ptr.shape[1])
        output_size = output_ptr.shape[0] * output_ptr.shape[1] * output_ptr.shape[2]
        with ib.new_scope():
            nthread_tx = max_threads
            nthread_bx = ceil_div(output_size, max_threads)
            tx = te.thread_axis("threadIdx.x")
            bx = te.thread_axis("blockIdx.x")
            ib.scope_attr(tx, "thread_extent", nthread_tx)
            ib.scope_attr(bx, "thread_extent", nthread_bx)
            tid = bx * max_threads + tx

            with ib.if_scope(tid < output_size):
                matrix_size = output_ptr.shape[1] * output_ptr.shape[2]
                batch = tir.floordiv(tid, matrix_size)
                row = tir.floordiv(tir.indexmod(tid, matrix_size), output_ptr.shape[2])
                col = tir.indexmod(tir.indexmod(tid, matrix_size), output_ptr.shape[2])
                output[batch, row, col, 0] = tir.Cast(data_ptr.dtype, 0)
                output[batch, row, col, 1] = tir.Cast(data_ptr.dtype, 0)
                with ib.for_range(0, win_length) as wlen:
                    output[batch, row, col, 0] += (
                        window[wlen]
                        * data[batch, col * hop_length + wlen]
                        * tir.cos(2 * pi * row * wlen / win_length)
                    )
                    output[batch, row, col, 1] -= (
                        window[wlen]
                        * data[batch, col * hop_length + wlen]
                        * tir.sin(2 * pi * row * wlen / win_length)
                    )
                with ib.if_scope(normalized):
                    output[batch, row, col, 0] /= tir.sqrt(tir.const(n_fft, "float32"))
                    output[batch, row, col, 1] /= tir.sqrt(tir.const(n_fft, "float32"))

        return ib.get()

    output_buf = tir.decl_buffer(output_shape, data.dtype, "output_buf")

    return te.extern(
        output_shape,
        [data, window],
        lambda ins, outs: gen_ir(
            ins[0], n_fft, hop_length, win_length, ins[1], normalized, onesided, outs[0]
        ),
        dtype=[data.dtype],
        out_buffers=[output_buf],
        name="stft_cuda",
        tag="stft_cuda",
    )


def dft(
    re_data: te.Tensor,
    im_data: te.Tensor,
    inverse: tir.IntImm,
):
    """
    Computes the discrete Fourier transform of input (calculation along the last axis).
    This gives frequency components of the signal as they change over time.

    Parameters
    ----------
    re_data : relay.Expr
        N-D tensor, real part of the input signal.

    im_data : relay.Expr
        N-D tensor, imaginary part of the input signal.
        If the signal is real, then the values of this tensor are zeros.

    inverse : bool
        Whether to perform the inverse discrete fourier transform.

    Returns
    -------
    re_output : relay.Expr
        The Fourier Transform of the input (Real part).
    im_output : relay.Expr
        The Fourier Transform of the input (Imaginary part).
    """

    def gen_ir(
        re_data_buf,
        im_data_buf,
        re_output_buf,
        im_output_buf,
    ):
        ib = tir.ir_builder.create()
        re_data_ptr = ib.buffer_ptr(re_data_buf)
        im_data_ptr = ib.buffer_ptr(im_data_buf)
        re_output_ptr = ib.buffer_ptr(re_output_buf)
        im_output_ptr = ib.buffer_ptr(im_output_buf)

        shape = re_data.shape
        n_fft = shape[len(shape) - 1]
        base_range = 1
        for i in range(len(shape) - 1):
            base_range *= shape[i]

        sign = -1 if inverse else 1
        factor = 1.0 / n_fft if inverse else 1.0

        max_threads = _get_max_threads(base_range)
        with ib.new_scope():
            nthread_tx = max_threads
            nthread_bx = ceil_div(base_range, max_threads)
            tx = te.thread_axis("threadIdx.x")
            bx = te.thread_axis("blockIdx.x")
            ib.scope_attr(tx, "thread_extent", nthread_tx)
            ib.scope_attr(bx, "thread_extent", nthread_bx)

            tid = bx * max_threads + tx
            with ib.if_scope(tid < base_range):
                base_idx = tid * n_fft
                with ib.for_range(0, n_fft) as n:
                    n_idx = base_idx + n
                    re_output_ptr[n_idx] = tir.Cast(re_output_ptr.dtype, 0)
                    im_output_ptr[n_idx] = tir.Cast(im_output_ptr.dtype, 0)
                    _w = sign * -2 * pi * n / n_fft
                    with ib.for_range(0, n_fft) as k:
                        k_idx = base_idx + k
                        w = _w * k
                        cos_w = tir.Cast(re_output_ptr.dtype, tir.cos(w))
                        sin_w = tir.Cast(re_output_ptr.dtype, tir.sin(w))
                        re_output_ptr[n_idx] += (
                            re_data_ptr[k_idx] * cos_w - im_data_ptr[k_idx] * sin_w
                        )
                        im_output_ptr[n_idx] += (
                            re_data_ptr[k_idx] * sin_w + im_data_ptr[k_idx] * cos_w
                        )

                    re_output_ptr[n_idx] *= tir.Cast(re_output_ptr.dtype, factor)
                    im_output_ptr[n_idx] *= tir.Cast(im_output_ptr.dtype, factor)

        return ib.get()

    output_shape = [re_data.shape] * 2

    return te.extern(
        shape=output_shape,
        inputs=[re_data, im_data],
        fcompute=lambda ins, outs: gen_ir(ins[0], ins[1], outs[0], outs[1]),
        dtype=[re_data.dtype, im_data.dtype],
        name="dft_cuda",
        tag="dft_cuda",
    )
