import torch
import torch_em
from torch_em.model import UNet2d
from torch_em.data.datasets import get_dsb_loader

OFFSETS = [
    [-1, 0], [0, -1],
    [-3, 0], [0, -3],
    [-9, 0], [0, -9],
    [-27, 0], [0, -27]
]


def train_affinities(args):
    n_out = len(OFFSETS) + 1
    model = UNet2d(in_channels=1, out_channels=n_out, initial_features=64,
                   final_activation="Sigmoid")

    patch_shape = (1, 256, 256)
    train_loader = get_dsb_loader(
        args.input, patch_shape, split="train",
        download=True, offsets=OFFSETS, batch_size=args.batch_size
    )
    val_loader = get_dsb_loader(
        args.input, patch_shape, split="test",
        offsets=OFFSETS, batch_size=args.batch_size
    )

    loss = torch_em.loss.LossWrapper(
        torch_em.loss.DiceLoss(),
        transform=torch_em.loss.ApplyAndRemoveMask()
    )

    # the trainer object that handles the training details
    # the model checkpoints will be saved in "checkpoints/dsb-boundary-model"
    # the tensorboard logs will be saved in "logs/dsb-boundary-model"
    trainer = torch_em.default_segmentation_trainer(
        name="dsb-affinity-model",
        model=model,
        train_loader=train_loader,
        val_loader=val_loader,
        loss=loss,
        metric=loss,
        learning_rate=1e-4,
        device=torch.device('cuda'),
        mixed_precision=True,
        log_image_interval=50
    )
    trainer.fit(iterations=args.n_iterations)


if __name__ == '__main__':
    parser = torch_em.util.parser_helper(
        default_batch_size=8
    )
    args = parser.parse_args()
    train_affinities(args)
