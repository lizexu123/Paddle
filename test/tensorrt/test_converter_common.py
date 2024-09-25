# Copyright (c) 2024 PaddlePaddle Authors. All Rights Reserved.
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

import unittest

import numpy as np
from tensorrt_test_base import TensorRTBaseTest

import paddle
from paddle import _C_ops


def upsample_wrapper(x):
    upsample = paddle.nn.Upsample(size=[12, 12], mode="bilinear")
    return upsample(x)


def bilinear_python_api(x, OutSize, SizeTensor, Scale, attrs):
    if OutSize is not None:
        OutSize = paddle.to_tensor(OutSize)
    if SizeTensor is not None:
        SizeTensor = paddle.to_tensor(SizeTensor)
    if Scale is not None:
        Scale = paddle.to_tensor(Scale)
    return _C_ops.bilinear_interp(
        x,
        OutSize,
        SizeTensor,
        Scale,
        attrs['data_layout'],
        attrs['out_d'],
        attrs['out_h'],
        attrs['out_w'],
        attrs['scale'] if 'scale' in attrs else [],
        attrs['interp_method'],
        attrs['align_corners'],
        attrs['align_mode'],
    )


class TestBilinearScaleTRTPattern(TensorRTBaseTest):
    def setUp(self):
        self.python_api = bilinear_python_api
        self.api_args = {
            "x": np.random.random([2, 3, 6, 10]).astype("float32"),
            "OutSize": None,
            "SizeTensor": None,
            "Scale": None,
            "attrs": {
                "data_layout": "NCHW",
                "scale": [2.0, 2.0],
                "out_h": 12,
                "out_w": 12,
                "out_d": -1,
                "interp_method": "bilinear",
                "align_corners": False,
                "align_mode": 0,
            },
        }
        self.program_config = {"feed_list": ["x"]}
        self.min_shape = {"x": [2, 3, 6, 10]}
        self.max_shape = {"x": [12, 3, 6, 10]}

    def test_trt_result(self):
        self.check_trt_result()


class TestBilinearNHWCTRTPattern(TensorRTBaseTest):
    def setUp(self):
        self.python_api = bilinear_python_api
        self.api_args = {
            "x": np.random.random([2, 3, 6, 10]).astype("float32"),
            "OutSize": np.array([12, 12], dtype="int32"),
            "SizeTensor": None,
            "Scale": None,
            "attrs": {
                "data_layout": "NHWC",
                "scale": [2.0, 2.0],
                "out_h": 12,
                "out_w": 12,
                "out_d": -1,
                "interp_method": "bilinear",
                "align_corners": False,
                "align_mode": 0,
            },
        }
        self.program_config = {"feed_list": ["x", "OutSize"]}
        self.min_shape = {"x": [2, 3, 6, 10]}
        self.max_shape = {"x": [12, 3, 6, 10]}

    def test_trt_result(self):
        self.check_trt_result()


class TestBilinearTRTPattern(TensorRTBaseTest):
    def setUp(self):
        self.python_api = upsample_wrapper
        self.api_args = {"x": np.random.random([2, 3, 6, 10]).astype("float32")}
        self.program_config = {"feed_list": ["x"]}
        self.min_shape = {"x": [2, 3, 6, 10]}
        self.max_shape = {"x": [12, 3, 6, 10]}

    def test_trt_result(self):
        self.check_trt_result()


if __name__ == '__main__':
    unittest.main()
