import os
import time
import paddle
import paddle.fluid as fluid
import paddle.static as static
from paddleslim.prune import Pruner
from paddleslim.core import GraphWrapper
import numpy as np
__all__ = ["get_sparse_model", "get_prune_model"]


def get_sparse_model(model_file, param_file, ratio, save_path):
    """
    Using the unstructured sparse algorithm to compress the network. 
    This interface is only used to evaluate the latency of the compressed network, and does not consider the loss of accuracy.
    Args:
        model_file(str), param_file(str): The inference model to be pruned.
        ratio(float): The ratio to prune the model.
        save_path(str): The save path of pruned model.
    """
    assert os.path.exists(model_file), f'{model_file} does not exist.'
    assert os.path.exists(
        param_file) or param_file is None, f'{param_file} does not exist.'
    paddle.enable_static()

    SKIP = ['image', 'feed', 'pool2d_0.tmp_0']

    folder = os.path.dirname(model_file)
    model_name = model_file.split('/')[-1]
    if param_file is None:
        param_name = None
    else:
        param_name = param_file.split('/')[-1]

    main_prog = static.Program()
    startup_prog = static.Program()
    exe = paddle.static.Executor(paddle.CPUPlace())
    exe.run(startup_prog)

    [inference_program, feed_target_names, fetch_targets] = (
        fluid.io.load_inference_model(
            folder, exe, model_filename=model_name, params_filename=param_name))
    thresholds = {}

    graph = GraphWrapper(inference_program)
    for op in graph.ops():
        for inp in op.all_inputs():
            name = inp.name()
            if inp.name() in SKIP: continue
            if 'tmp' in inp.name(): continue
            # 1x1_conv
            cond_conv = len(inp._var.shape) == 4 and inp._var.shape[
                2] == 1 and inp._var.shape[3] == 1
            cond_fc = False

            if cond_fc or cond_conv:
                array = np.array(paddle.static.global_scope().find_var(name)
                                 .get_tensor())
                flatten = np.abs(array.flatten())
                index = min(len(flatten) - 1, int(ratio * len(flatten)))
                ind = np.unravel_index(
                    np.argsort(
                        flatten, axis=None), flatten.shape)
                thresholds[name] = ind[0][:index]

    for op in graph.ops():
        for inp in op.all_inputs():
            name = inp.name()
            if name in SKIP: continue
            if 'tmp' in inp.name(): continue

            cond_conv = (len(inp._var.shape) == 4 and inp._var.shape[2] == 1 and
                         inp._var.shape[3] == 1)
            cond_fc = False

            # only support 1x1_conv now
            if not (cond_conv or cond_fc): continue
            array = np.array(paddle.static.global_scope().find_var(name)
                             .get_tensor())
            if thresholds.get(name) is not None:
                np.put(array, thresholds.get(name), 0)
            assert (abs(1 - np.count_nonzero(array) / array.size - ratio) < 1e-2
                    ), 'The model sparsity is abnormal.'
            paddle.static.global_scope().find_var(name).get_tensor().set(
                array, paddle.CPUPlace())

    fluid.io.save_inference_model(
        save_path,
        feeded_var_names=feed_target_names,
        target_vars=fetch_targets,
        executor=exe,
        main_program=inference_program,
        model_filename=model_name,
        params_filename=param_name)
    print("The pruned model is saved in: ", save_path)


def get_prune_model(model_file, param_file, ratio, save_path):
    """
    Using the structured pruning algorithm to compress the network. 
    This interface is only used to evaluate the latency of the compressed network, and does not consider the loss of accuracy.
    Args:
        model_file(str), param_file(str): The inference model to be pruned.
        ratio(float): The ratio to prune the model.
        save_path(str): The save path of pruned model.
    """

    assert os.path.exists(model_file), f'{model_file} does not exist.'
    assert os.path.exists(
        param_file) or param_file is None, f'{param_file} does not exist.'
    paddle.enable_static()

    SKIP = ['image', 'feed', 'pool2d_0.tmp_0']

    folder = os.path.dirname(model_file)
    model_name = model_file.split('/')[-1]
    if param_file is None:
        param_name = None
    else:
        param_name = param_file.split('/')[-1]

    main_prog = static.Program()
    startup_prog = static.Program()
    place = paddle.CPUPlace()
    exe = paddle.static.Executor()
    scope = static.global_scope()
    exe.run(startup_prog)

    [inference_program, feed_target_names, fetch_targets] = (
        fluid.io.load_inference_model(
            folder, exe, model_filename=model_name, params_filename=param_name))

    prune_params = []
    graph = GraphWrapper(inference_program)
    for op in graph.ops():
        for inp in op.all_inputs():
            name = inp.name()
            if inp.name() in SKIP: continue
            if 'tmp' in inp.name(): continue
            cond_conv = len(inp._var.shape) == 4 and 'conv' in name
            # only prune conv
            if cond_conv:
                prune_params.append(name)

    # drop last conv
    prune_params.pop()
    ratios = [ratio] * len(prune_params)

    pruner = Pruner()
    main_program, _, _ = pruner.prune(
        inference_program,
        scope,
        params=prune_params,
        ratios=ratios,
        place=place,
        lazy=False,
        only_graph=False,
        param_backup=None,
        param_shape_backup=None)

    fluid.io.save_inference_model(
        save_path,
        feeded_var_names=feed_target_names,
        target_vars=fetch_targets,
        executor=exe,
        main_program=main_program,
        model_filename=model_name,
        params_filename=param_name)
