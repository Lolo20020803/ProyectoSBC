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
"""QNN legalization transforms that help eliminate sparse channels.

Some models (like MobileNetV1 when fine-tuned) have output channels in their kernels which are
completely full of zeros. Sometimes these can be optimized away by the C compiler, but this does not
happen when complex schedules (like the ACLE tensordot convolutions) are used.

Instead, we will remove these channels by replacing blocks of operators with equivalent "denser"
ones during legalization. This is harder than it looks - while the outputs of channels with all-zero
kernels do not depend on the input data, they are usually not zero. We work around this by computing
how these constant values affect subsequent operators, and "folding" these effects into a bias_add.

It would eventually be nice to have a generalized, cross-target solution for removing zero channels,
as there is no downside. This may be possible with Relax, but I'm unsure.
"""

import numpy as np
from scipy.signal import convolve2d
from tvm.topi.utils import get_const_tuple
from tvm import nd, relay
from .qnn_alter_op import prev_ops_match, edit_attrs
from ..nn import bias_add_legalize


def _compute_fixed_conv2d_outputs(requantize_op):
    """Compute all conv2d output values that do not depend on the layer input.

    Parameters
    ----------
    requantize_op : relay.expr.Call
        A qnn.requantize Relay operator, which must be preceeded by a nn.bias_add op and a
        qnn.conv2d operator. The qnn.conv2d operator must have groups==1. All arguments to all three
        operators, besides the main tensor, must be constants.

    Returns
    -------
    fixed_outputs : Dict[int, int]
        A dictionary showing which of the conv2d -> bias_add -> requantize output channels are
        "fixed" - i.e. those that do not depend on the input tensor. Each key in the dictionary is
        an output channel index, and each value is the value that all entries in that output channel
        will have. If the block has no fixed output channels, this dictionary will be empty.
    """

    bias_add_op = requantize_op.args[0]
    conv2d_op = bias_add_op.args[0]

    assert conv2d_op.attrs.kernel_layout.isalpha()
    assert conv2d_op.attrs.groups == 1
    kernel = conv2d_op.args[1].data.numpy()
    oc_axis = conv2d_op.attrs.kernel_layout.index("O")

    num_channels = kernel.shape[oc_axis]
    rq_input_scale = requantize_op.args[1].data.numpy()
    rq_output_scale = requantize_op.args[3].data.numpy().item()
    rq_output_zero_point = requantize_op.args[4].data.numpy().item()
    bias_data = bias_add_op.args[1].data.numpy()

    fixed_outputs = {}

    for i in range(num_channels):
        if np.any(np.take(kernel, i, axis=oc_axis)):
            continue
        scale = rq_input_scale[i] / rq_output_scale
        channel_constant = round(bias_data[i] * scale + rq_output_zero_point)
        clipped = min(127, max(-128, channel_constant))
        fixed_outputs[i] = clipped

    return fixed_outputs


def _compute_fixed_depthwise_outputs(requantize_op, fixed_channel_inputs):
    """Compute all depthwise conv2d output values that do not depend on the PREVIOUS layer input.

    We take as input a requantize operator, and a dictionary of which inputs to our depthwise
    operator are fixed and what values they are fixed to. However, a fixed input to one channel
    of our depthwise operator does NOT guarantee we can remove the output, because of padding.
    This function checks if the padding makes a difference in the outputs, and if not, removes
    the channels from the depthwise_conv2d.

    Parameters
    ----------
    requantize_op : relay.expr.Call
        A qnn.requantize Relay operator, which must be preceeded by a nn.bias_add op and a
        qnn.conv2d operator. The qnn.conv2d operator must be depthwise. All arguments to all three
        operators, besides the main tensor, must be constants.

    fixed_channel_inputs : Dict[int, int]
        A dictionary showing which input channels to the qnn.conv2d operator have fixed values, and
        what those values are fixed to. Can be empty. Usually, this will be generated by
        _compute_fixed_conv2d_outputs.

    Returns
    -------
    fixed_outputs : Dict[int, int]
        A dictionary showing which of the conv2d -> bias_add -> requantize output channels are
        "fixed" - i.e. those that do not depend on the input tensor. Each key in the dictionary is
        an output channel index, and each value is the value that all entries in that output channel
        will have. If the block has no fixed output channels, this dictionary will be empty.
    """

    bias_add_op = requantize_op.args[0]
    depthwise_op = bias_add_op.args[0]

    assert depthwise_op.attrs.kernel_layout.isalpha()
    assert depthwise_op.attrs.groups > 1
    kernel = depthwise_op.args[1].data.numpy()
    oc_axis = depthwise_op.attrs.kernel_layout.index("O")

    conv_input_zero_point = depthwise_op.args[2].data.numpy().item()
    rq_input_scale = requantize_op.args[1].data.numpy()
    rq_output_scale = requantize_op.args[3].data.numpy().item()
    rq_output_zero_point = requantize_op.args[4].data.numpy().item()
    bias_data = bias_add_op.args[1].data.numpy()

    kernel_size = get_const_tuple(depthwise_op.attrs.kernel_size)
    fixed_outputs = {}

    for i, fixed_input in fixed_channel_inputs.items():
        input_array = np.full(kernel_size, fixed_input, dtype="int32") - conv_input_zero_point
        kernel_channel = np.take(kernel, i, axis=oc_axis).reshape(kernel_size)
        scale = rq_input_scale[i] / rq_output_scale

        convolved = convolve2d(input_array, kernel_channel, mode="same")
        rounded = np.around((convolved + bias_data[i]) * scale).astype("int32")
        clipped = np.clip(rounded + rq_output_zero_point, -128, 127)

        # We require the ENTIRE padded convolution to all have the same clipped value before we do
        # a replacement. This is excessive - we only have to check for the padding that will
        # actually be performed on the depthwise convolution, which is often less. If we felt even
        # more ambitious, we could do the replacement for "close enough" looking convolution
        # outputs, which in theory could reduce accuracy but in practice does not. Doing this would
        # yield a ~0.5% speed gain on MobileNetV1, and nothing on other models.

        if np.all(clipped == clipped[0, 0]):
            fixed_outputs[i] = clipped[0, 0]

    # TODO @guberti look for all-zero entries in the depthwise kernel. I don't think these really
    # occur in practice, but it would be nice for theoretical completeness.

    return fixed_outputs


def _excise_conv2d_channels(empty_channels, input_op, requantize_op, is_depthwise=False):
    bias_add_op = requantize_op.args[0]
    conv2d_op = bias_add_op.args[0]
    axis = conv2d_op.attrs.kernel_layout.index("O")

    kernel_data = np.delete(conv2d_op.args[1].data.numpy(), empty_channels, axis=axis)
    bias_data = np.delete(bias_add_op.args[1].data.numpy(), empty_channels)
    in_scale_data = np.delete(conv2d_op.args[5].data.numpy(), empty_channels)
    out_scale_data = np.delete(requantize_op.args[1].data.numpy(), empty_channels)
    num_channels = kernel_data.shape[axis]
    if is_depthwise:
        num_groups = num_channels
    else:
        num_groups = 1

    return relay.qnn.op.requantize(
        relay.nn.bias_add(
            relay.qnn.op.conv2d(
                input_op,
                relay.Constant(nd.array(kernel_data)),
                *conv2d_op.args[2:5],
                relay.Constant(nd.array(in_scale_data)),
                **edit_attrs(conv2d_op.attrs, channels=num_channels, groups=num_groups),
            ),
            relay.Constant(nd.array(bias_data)),
            **bias_add_op.attrs,
        ),
        relay.Constant(nd.array(out_scale_data)),
        *requantize_op.args[2:],
        **requantize_op.attrs,
    )


def _excise_avg_pool_channels(empty_channels, input_op, first_reshape_op, axis=1):
    outer_cast = first_reshape_op.args[0].args[0]
    avg_pool = outer_cast.args[0]
    inner_cast = avg_pool.args[0]

    new_shape = list(get_const_tuple(first_reshape_op.attrs.newshape))
    new_shape[axis] -= len(empty_channels)

    return relay.reshape(
        relay.cast(
            relay.nn.avg_pool2d(relay.cast(input_op, **inner_cast.attrs), **avg_pool.attrs),
            **outer_cast.attrs,
        ),
        **edit_attrs(first_reshape_op.attrs, newshape=new_shape),
    )


def _fold_into_conv_bias(fixed_inputs, conv2d_op, input_op):
    assert not any(get_const_tuple(conv2d_op.attrs.padding))
    in_axis = conv2d_op.attrs.kernel_layout.index("I")
    out_axis = conv2d_op.attrs.kernel_layout.index("O")

    kernel = conv2d_op.args[1].data.numpy()
    zero_point = conv2d_op.args[2].data.numpy().item()

    extra_bias = np.zeros((kernel.shape[out_axis],), dtype="int32")

    # For every output channel
    for i in range(kernel.shape[out_axis]):
        out_kernel_slice = np.expand_dims(np.take(kernel, i, axis=out_axis), axis=out_axis)

        # For every input channel that is being removed:
        for j, val in fixed_inputs.items():
            kernel_slice = np.take(out_kernel_slice, j, axis=in_axis)
            accumulator = np.sum(kernel_slice * (val - zero_point))
            extra_bias[i] += accumulator

    stripped_kernel = np.delete(kernel, tuple(fixed_inputs.keys()), axis=in_axis)
    new_conv = relay.qnn.op.conv2d(
        input_op,
        relay.Constant(nd.array(stripped_kernel)),
        *conv2d_op.args[2:],
        **conv2d_op.attrs,
    )

    return new_conv, extra_bias


def _fold_into_dense_bias(fixed_inputs, dense_op, input_op, channel_axis=1):
    weights = dense_op.args[1].data.numpy()
    assert channel_axis < 2
    assert len(weights.shape) == 2
    zero_point = dense_op.args[2].data.numpy().item()

    extra_bias = np.zeros((weights.shape[1 - channel_axis],), dtype="int32")

    # For every output channel
    for i in range(weights.shape[1 - channel_axis]):
        out_weights_slice = np.take(weights, i, axis=1 - channel_axis)

        # For every input channel that is being removed:
        for j, val in fixed_inputs.items():
            weight = out_weights_slice[j]
            extra_bias[i] += (val - zero_point) * weight

    stripped_weights = np.delete(weights, tuple(fixed_inputs.keys()), axis=channel_axis)
    new_dense = relay.qnn.op.dense(
        input_op,
        relay.Constant(nd.array(stripped_weights)),
        *dense_op.args[2:],
        **dense_op.attrs,
    )

    return new_dense, extra_bias


def _densify_conv_depthwise_conv_pattern(attrs, inputs):
    """Rewrites a regular -> depthwise -> regular convolution pattern to excise empty out channels.

    Should be called as part of legalization (before dtypes and layouts are rewritten) and with the
    BIAS ADD OPERATOR'S (the one we'll use to "fold in" our constants) `attrs` and `inputs`. The
    last regular conv2d operator must be unpadded.
    """
    current_conv = inputs[0]
    depthwise_requantize = current_conv.args[0]
    top_requantize = depthwise_requantize.args[0].args[0].args[0]
    top_conv2d = top_requantize.args[0].args[0]

    fixed_conv2d_outputs = _compute_fixed_conv2d_outputs(top_requantize)
    fixed_dw_outputs = _compute_fixed_depthwise_outputs(depthwise_requantize, fixed_conv2d_outputs)

    # Ensure number of channels is divisible by two
    if len(fixed_dw_outputs) % 2 > 0:
        fixed_dw_outputs.popitem()

    if not fixed_dw_outputs:
        return None

    unneeded_channels = tuple(fixed_dw_outputs.keys())
    new_top_conv2d = _excise_conv2d_channels(unneeded_channels, top_conv2d.args[0], top_requantize)
    new_dw_conv2d = _excise_conv2d_channels(
        unneeded_channels, new_top_conv2d, depthwise_requantize, is_depthwise=True
    )
    new_conv, extra_bias = _fold_into_conv_bias(fixed_dw_outputs, current_conv, new_dw_conv2d)

    new_bias = inputs[1].data.numpy() + extra_bias
    new_op = relay.nn.bias_add(new_conv, relay.Constant(nd.array(new_bias)), **attrs)
    return new_op


def _densify_conv_pool_dense_pattern(attrs, inputs):
    """Rewrites a regular conv -> pool -> dense pattern to excise empty out channels from the conv.

    Should be called as part of legalization (before dtypes and layouts are rewritten) and with the
    BIAS ADD operator's `attrs` and `inputs` (the one we'll use to "fold in" our constants). The
    average pool operator must reduce the height and width dimensions to 1x1.
    """
    first_reshape = inputs[0].args[0]
    top_requantize = first_reshape.args[0].args[0].args[0].args[0].args[0]
    top_conv2d = top_requantize.args[0].args[0]

    fixed_conv2d_outputs = _compute_fixed_conv2d_outputs(top_requantize)

    # Ensure number of channels is divisible by two
    if len(fixed_conv2d_outputs) % 2 > 0:
        fixed_dw_outputs.popitem()

    if not fixed_conv2d_outputs:
        return None

    unneeded_channels = tuple(fixed_conv2d_outputs.keys())
    new_top_conv2d = _excise_conv2d_channels(unneeded_channels, top_conv2d.args[0], top_requantize)
    new_avg_pool = _excise_avg_pool_channels(unneeded_channels, new_top_conv2d, first_reshape)
    new_conv, extra_bias = _fold_into_dense_bias(fixed_conv2d_outputs, inputs[0], new_avg_pool)

    new_bias = inputs[1].data.numpy() + extra_bias
    new_op = relay.nn.bias_add(new_conv, relay.Constant(nd.array(new_bias)), **attrs)
    return new_op


@bias_add_legalize.register(["arm_cpu"])
def legalize_bias_add(attrs, inputs, _tinfos):
    """Remove empty convolution channels when possible, and "fold" them into the bias add.

    TODO @guberti: these rewrites are always beneficial and will improve performance cross-platform,
    should we enable them for all platforms, not just arm_cpu?
    """

    if prev_ops_match(
        inputs[0],
        (
            "qnn.conv2d",
            "qnn.requantize",
            "nn.bias_add",
            "qnn.conv2d",
            "qnn.requantize",
            "nn.bias_add",
            "qnn.conv2d",
        ),
    ):
        current_conv = inputs[0]
        depthwise_conv2d = current_conv.args[0].args[0].args[0]
        top_conv2d = depthwise_conv2d.args[0].args[0].args[0]
        if (
            not any(get_const_tuple(current_conv.attrs.padding))
            and current_conv.attrs.groups == 1
            and depthwise_conv2d.attrs.groups > 1
            and top_conv2d.attrs.groups == 1
        ):
            return _densify_conv_depthwise_conv_pattern(attrs, inputs)

    if prev_ops_match(
        inputs[0],
        (
            "qnn.dense",
            "reshape",
            "reshape",
            "cast",
            "nn.avg_pool2d",
            "cast",
            "qnn.requantize",
            "nn.bias_add",
            "qnn.conv2d",
        ),
    ):
        avg_pool = inputs[0].args[0].args[0].args[0].args[0]
        top_requantize = avg_pool.args[0].args[0]
        top_conv2d = top_requantize.args[0].args[0]
        if top_conv2d.attrs.groups == 1:
            return _densify_conv_pool_dense_pattern(attrs, inputs)

    return None
