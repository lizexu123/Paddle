# Copyright (c) 2024 PaddlePaddle Authors. All Rights Reserved
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

import numpy as np

import paddle
from paddle.tensorrt.converter import PaddleToTensorRTConverter
from paddle.tensorrt.util import (
    run_pir_pass,
    warmup_shape_infer,
    warmup_shape_infer_v2,
)


class TensorRTConfig:
    """
    TensorRT config.
    """

    def __init__(
        self,
        program=None,
        use_tensorrt=None,
        workspace_size=None,
        min_subgraph_size=None,
        precision_mode=None,
        tensorrt_use_cuda_graph=None,
        tensorrt_with_interleaved=None,
        trt_mark_output=None,
        trt_output_tensor_names=None,
        trt_parameters_run_fp16=None,
        trt_parameters_run_int8=None,
        trt_parameters_run_bfp16=None,
        tensorrt_transformer_posid=None,
        tensorrt_transformer_maskid=None,
        min_input_shape=None,
        max_input_shape=None,
        optim_input_shape=None,
        input_data_type=None,
        input_range=None,
        trt_disabled_ops=None,
        disable_trt_plugin_fp16=None,
        trt_use_inspector=None,
        trt_inspector_serialize=None,
        trt_use_explicit_quantization=None,
        trt_optimization_level=None,
        collect_shape_range_info=None,
        enable_memory_optim=None,
        trt_engine_memory_sharing=None,
        trt_ops_run_float=None,
        save_model_dir=None,
        save_model_prefix=None,
        is_save_program=True,
        input_min_data=None,
        input_max_data=None,
        input_optim_data=None,
        use_executor=None,
    ):
        self.program = program
        self.use_tensorrt = use_tensorrt
        self.workspace_size = workspace_size
        self.min_subgraph_size = min_subgraph_size
        self.precision_mode = precision_mode
        self.tensorrt_use_cuda_graph = tensorrt_use_cuda_graph
        self.tensorrt_with_interleaved = tensorrt_with_interleaved
        self.trt_mark_output = trt_mark_output
        self.trt_output_tensor_names = trt_output_tensor_names
        self.trt_parameters_run_fp16 = trt_parameters_run_fp16
        self.trt_parameters_run_int8 = trt_parameters_run_int8
        self.trt_parameters_run_bfp16 = trt_parameters_run_bfp16
        self.tensorrt_transformer_posid = tensorrt_transformer_posid
        self.tensorrt_transformer_maskid = tensorrt_transformer_maskid
        self.min_input_shape = min_input_shape
        self.max_input_shape = max_input_shape
        self.optim_input_shape = optim_input_shape
        self.input_data_type = input_data_type
        self.input_range = input_range
        self.trt_disabled_ops = trt_disabled_ops
        self.disable_trt_plugin_fp16 = disable_trt_plugin_fp16
        self.trt_use_inspector = trt_use_inspector
        self.trt_inspector_serialize = trt_inspector_serialize
        self.trt_use_explicit_quantization = trt_use_explicit_quantization
        self.trt_optimization_level = trt_optimization_level
        self.collect_shape_range_info = collect_shape_range_info
        self.enable_memory_optim = enable_memory_optim
        self.trt_engine_memory_sharing = trt_engine_memory_sharing
        self.trt_ops_run_float = trt_ops_run_float
        self.is_save_program = is_save_program
        self.input_min_data = input_min_data
        self.input_max_data = input_max_data
        self.input_optim_data = input_optim_data
        if not self.is_save_program:
            self.save_model_dir = None
            self.save_model_prefix = None

    def forbid_op_lower_trt(self, program, trt_disabled_ops):
        for op in program.global_block().ops:
            if op.name() == trt_disabled_ops:
                op.set_bool_attr("__l_trt__", False)

    def generate_input_data(self):

        if self.min_input_shape is None or self.max_input_shape is None:
            raise ValueError(
                "min_input_shape and max_input_shape must be provided and cannot be None."
            )

        if self.input_data_type:
            self.input_min_data = np.ones(self.min_input_shape).astype(
                self.input_data_type
            )
            self.input_max_data = np.ones(self.max_input_shape).astype(
                self.input_data_type
            )

        elif self.input_data_type and self.input_range:
            low, high = self.input_range
            self.input_min_data = np.random.uniform(
                low, high, size=self.min_input_shape
            ).astype(self.input_data_type)
            self.input_max_data = np.random.uniform(
                low, high, size=self.max_input_shape
            ).astype(self.input_data_type)

        else:
            self.input_min_data = np.ones(self.min_input_shape).astype(
                'float32'
            )
            self.input_max_data = np.ones(self.max_input_shape).astype(
                'float32'
            )


def converter_trt_program(program, trt_config, scope):
    if not isinstance(program, paddle.base.libpaddle.pir.Program):
        raise TypeError(
            f"program type must be paddle.base.libpaddle.pir.Program, but received {type(program)}"
        )

    output_var = []
    feed_name = []

    for op in program.global_block().ops:
        if op.name() == "pd_op.fetch":
            for operand in op.operands():
                source = operand.source()
                output_var.append(source)
            print(f"Found fetch op. Output var updated: {output_var}")
        if op.name() == "pd_op.data" or op.name() == "pd_op.feed":
            param_name = op.attrs()["name"]
            feed_name.append(param_name)
            print(f"Found data/feed op. Feed name updated: {feed_name}")

    print("Creating PIR Guard.")
    with paddle.pir_utils.IrGuard():
        input_data_min_shape = trt_config.input_min_data
        input_data_max_shape = trt_config.input_max_data

        print(
            f"Input data shapes - Min: {input_data_min_shape}, Max: {input_data_max_shape}"
        )

        print("output_var", output_var)
        program_with_output = program.list_vars()[-1]
        print("program_with_output", program_with_output)
        # Step2: run warmup for collecting shape
        if trt_config.is_save_program:
            warmup_shape_infer_v2(
                program,
                min_shape_feed={feed_name[0]: input_data_min_shape},
                max_shape_feed={feed_name[0]: input_data_max_shape},
                fetch_var_list=program_with_output,
            )
        else:
            warmup_shape_infer(
                program,
                min_shape_feed={"input_ids": input_data_min_shape},
                max_shape_feed={"input_ids": input_data_max_shape},
            )

        if not trt_config.is_save_program:
            program_with_pir = run_pir_pass(
                program, partition_mode=False, use_executor=True
            )
        # Step3: run pir pass (including trt_op_marker_pass)

        program_with_pir = run_pir_pass(program, partition_mode=True)
        trt_output_var = []

        print("Processing program_with_pir global block ops.")
        for op in program_with_pir.global_block().ops:
            if op.name() == "pd_op.fetch":
                for operand in op.operands():
                    source = operand.source()
                    trt_output_var.append(source)
                print(
                    f"Found fetch op in program_with_pir. TRT output var updated: {trt_output_var}"
                )

        # Step4: run TRTConverter (would lower group_op into tensorrt_engine_op)
        print("Running TRTConverter.")
        print("program_with_pir", program_with_pir)
        converter = PaddleToTensorRTConverter(program_with_pir, scope)
        converter.convert_program_to_trt()
        print("Conversion to TRT complete.")

        # Save PIR program as JSON,using predictor.run requires setting is_save_program to True
        if trt_config.is_save_program:
            input_values = []
            input_values.extend(
                result
                for op in program_with_pir.global_block().ops
                if op.name() == "pd_op.data" or op.name() == "pd_op.feed"
                for result in op.results()
            )
            place = paddle.CUDAPlace(0)
            exe = paddle.static.Executor(place)
            trt_save_path = os.path.join(
                trt_config.save_model_dir, trt_config.save_model_prefix
            )
            print(f"Saving inference model to {trt_save_path}.")
            paddle.static.save_inference_model(
                trt_save_path,
                input_values,
                trt_output_var,
                exe,
                program=program_with_pir,
            )
            print("Model saved.")

        return program_with_pir, output_var, trt_output_var


def get_trt_program(model_dir, prefix, trt_config, load_json=True):
    scope = paddle.static.global_scope()
    place = paddle.CUDAPlace(0)
    exe = paddle.static.Executor(place)

    # Check if we should use PIR API
    if load_json:
        # Use PIR API context manager if required
        model_filename = os.path.join(model_dir, prefix + ".json")
        params_filename = os.path.join(model_dir, prefix + ".pdiparams")
    else:
        model_filename = os.path.join(model_dir, prefix + ".pdmodel")
        params_filename = os.path.join(model_dir, prefix + ".pdiparams")

    with paddle.pir_utils.IrGuard():
        # Load the model
        [program, feed_target_names, fetch_targets] = (
            paddle.static.io.load_inference_model(
                model_dir,
                executor=exe,
                model_filename=model_filename,
                params_filename=params_filename,
            )
        )

    program_with_trt, _, _ = converter_trt_program(program, trt_config, scope)
    return program_with_trt
