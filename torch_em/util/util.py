import os
import warnings

import numpy as np
import torch
import torch_em

# this is a fairly brittle way to check if a module is compiled.
# would be good to find a better solution, ideall something like
# model.is_compiled()
try:
    from torch._dynamo.eval_frame import OptimizedModule
except ImportError:
    OptimizedModule = None

# torch doesn't support most unsigned types,
# so we map them to their signed equivalent
DTYPE_MAP = {
    np.dtype("uint16"): np.int16,
    np.dtype("uint32"): np.int32,
    np.dtype("uint64"): np.int64
}


def auto_compile(model, compile_model, default_compile=True):
    """Model compilation for pytorch >= 2

    Parameters:
        model [torch.nn.Module] - the model
        compile_model [None, bool, str] - whether to comile the model.
            If None, it will not be compiled for torch < 2, and for torch > 2 the behavior
            specificed by 'default_compile' will be used. If a string is given it will be
            intepreted as the compile mode (torch.compile(model, mode=compile_model)) (default: None)
        default_compile [bool] - the default compilation behavior for torch 2
    """
    torch_major = int(torch.__version__.split(".")[0])

    if compile_model is None:
        if torch_major < 2:
            compile_model = False
        elif isinstance(model, OptimizedModule):  # model is already compiled
            compile_model = False
        else:
            compile_model = default_compile

    if compile_model:
        if torch_major < 2:
            raise RuntimeError("Model compilation is only supported for pytorch 2")
        print("Compiling pytorch model ...")
        if isinstance(compile_model, str):
            model = torch.compile(model, mode=compile_model)
        else:
            model = torch.compile(model)

    return model


def ensure_tensor(tensor, dtype=None):

    if isinstance(tensor, np.ndarray):
        if np.dtype(tensor.dtype) in DTYPE_MAP:
            tensor = tensor.astype(DTYPE_MAP[tensor.dtype])
        tensor = torch.from_numpy(tensor)

    assert torch.is_tensor(tensor), f"Cannot convert {type(tensor)} to torch"
    if dtype is not None:
        tensor = tensor.to(dtype=dtype)
    return tensor


def ensure_tensor_with_channels(tensor, ndim, dtype=None):
    assert ndim in (2, 3, 4), f"{ndim}"
    tensor = ensure_tensor(tensor, dtype)
    if ndim == 2:
        assert tensor.ndim in (2, 3, 4, 5), f"{tensor.ndim}"
        if tensor.ndim == 2:
            tensor = tensor[None]
        elif tensor.ndim == 4:
            assert tensor.shape[0] == 1, f"{tensor.shape}"
            tensor = tensor[0]
        elif tensor.ndim == 5:
            assert tensor.shape[:2] == (1, 1), f"{tensor.shape}"
            tensor = tensor[0, 0]
    elif ndim == 3:
        assert tensor.ndim in (3, 4, 5), f"{tensor.ndim}"
        if tensor.ndim == 3:
            tensor = tensor[None]
        elif tensor.ndim == 5:
            assert tensor.shape[0] == 1, f"{tensor.shape}"
            tensor = tensor[0]
    else:
        assert tensor.ndim in (4, 5), f"{tensor.ndim}"
        if tensor.ndim == 5:
            assert tensor.shape[0] == 1, f"{tensor.shape}"
            tensor = tensor[0]
    return tensor


def ensure_array(array, dtype=None):
    if torch.is_tensor(array):
        array = array.detach().cpu().numpy()
    assert isinstance(array, np.ndarray), f"Cannot convert {type(array)} to numpy"
    if dtype is not None:
        array = np.require(array, dtype=dtype)
    return array


def ensure_spatial_array(array, ndim, dtype=None):
    assert ndim in (2, 3)
    array = ensure_array(array, dtype)
    if ndim == 2:
        assert array.ndim in (2, 3, 4, 5), str(array.ndim)
        if array.ndim == 3:
            assert array.shape[0] == 1
            array = array[0]
        elif array.ndim == 4:
            assert array.shape[:2] == (1, 1)
            array = array[0, 0]
        elif array.ndim == 5:
            assert array.shape[:3] == (1, 1, 1)
            array = array[0, 0, 0]
    else:
        assert array.ndim in (3, 4, 5), str(array.ndim)
        if array.ndim == 4:
            assert array.shape[0] == 1, f"{array.shape}"
            array = array[0]
        elif array.ndim == 5:
            assert array.shape[:2] == (1, 1)
            array = array[0, 0]
    return array


def get_constructor_arguments(obj):

    # all relevant torch_em classes have 'init_kwargs' to
    # directly recover the init call
    if hasattr(obj, "init_kwargs"):
        return getattr(obj, "init_kwargs")

    def _get_args(obj, param_names):
        return {name: getattr(obj, name) for name in param_names}

    # we don't need to find the constructor arguments for optimizers or schedulers
    # because we deserialize the state later
    if isinstance(obj, (torch.optim.Optimizer,
                        torch.optim.lr_scheduler._LRScheduler,
                        # ReduceLROnPlateau does not inherit from _LRScheduler
                        torch.optim.lr_scheduler.ReduceLROnPlateau)):
        return {}

    # recover the arguments for torch dataloader
    elif isinstance(obj, torch.utils.data.DataLoader):
        # These are all the "simple" arguements.
        # "sampler", "batch_sampler" and "worker_init_fn" are more complicated
        # and generally not used in torch_em
        return _get_args(obj, ["batch_size", "shuffle", "num_workers",
                               "pin_memory", "drop_last", "persistent_workers",
                               "prefetch_factor", "timeout"])

    # TODO support common torch losses (e.g. CrossEntropy, BCE)

    warnings.warn(
        f"Constructor arguments for {type(obj)} cannot be deduced." +
        "For this object, empty constructor arguments will be used." +
        "Hence, the trainer can probably not be correctly deserialized via 'DefaultTrainer.from_checkpoint'."
    )
    return {}


def get_trainer(checkpoint, name="best", device=None):
    """Load trainer from a checkpoint.
    """
    # try to load from file
    if isinstance(checkpoint, str):
        assert os.path.exists(checkpoint), checkpoint
        trainer = torch_em.trainer.DefaultTrainer.from_checkpoint(checkpoint,
                                                                  name=name,
                                                                  device=device)
    else:
        trainer = checkpoint
    assert isinstance(trainer, torch_em.trainer.DefaultTrainer)
    return trainer


def get_normalizer(trainer):
    dataset = trainer.train_loader.dataset
    while isinstance(dataset, torch_em.data.concat_dataset.ConcatDataset):
        dataset = dataset.datasets[0]
    preprocessor = dataset.raw_transform

    if hasattr(preprocessor, "normalizer"):
        return preprocessor.normalizer
    else:
        return preprocessor


def model_is_equal(model1, model2):
    for p1, p2 in zip(model1.parameters(), model2.parameters()):
        if p1.data.ne(p2.data).sum() > 0:
            return False
    return True
