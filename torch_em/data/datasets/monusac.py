import os
import shutil
from glob import glob
from tqdm import tqdm
from pathlib import Path
from typing import Optional, List

import imageio.v3 as imageio

import torch_em
from . import util


URL = {
    "train": "https://drive.google.com/uc?export=download&id=1lxMZaAPSpEHLSxGA9KKMt_r-4S8dwLhq",
    "test": "https://drive.google.com/uc?export=download&id=1G54vsOdxWY1hG7dzmkeK3r0xz9s-heyQ"
}


CHECKSUM = {
    "train": "5b7cbeb34817a8f880d3fddc28391e48d3329a91bf3adcbd131ea149a725cd92",
    "test": "bcbc38f6bf8b149230c90c29f3428cc7b2b76f8acd7766ce9fc908fc896c2674"
}

# here's the description: https://drive.google.com/file/d/1kdOl3s6uQBRv0nToSIf1dPuceZunzL4N/view
ORGAN_SPLITS = {
    "train": {
        "lung": ["TCGA-55-1594", "TCGA-69-7760", "TCGA-69-A59K", "TCGA-73-4668", "TCGA-78-7220",
                 "TCGA-86-7713", "TCGA-86-8672", "TCGA-L4-A4E5", "TCGA-MP-A4SY", "TCGA-MP-A4T7"],
        "kidney": ["TCGA-5P-A9K0", "TCGA-B9-A44B", "TCGA-B9-A8YI", "TCGA-DW-7841", "TCGA-EV-5903", "TCGA-F9-A97G",
                   "TCGA-G7-A8LD", "TCGA-MH-A560", "TCGA-P4-AAVK", "TCGA-SX-A7SR", "TCGA-UZ-A9PO", "TCGA-UZ-A9PU"],
        "breast": ["TCGA-A2-A0CV", "TCGA-A2-A0ES", "TCGA-B6-A0WZ", "TCGA-BH-A18T", "TCGA-D8-A1X5",
                   "TCGA-E2-A154", "TCGA-E9-A22B", "TCGA-E9-A22G", "TCGA-EW-A6SD", "TCGA-S3-AA11"],
        "prostate": ["TCGA-EJ-5495", "TCGA-EJ-5505", "TCGA-EJ-5517", "TCGA-G9-6342", "TCGA-G9-6499",
                     "TCGA-J4-A67Q", "TCGA-J4-A67T", "TCGA-KK-A59X", "TCGA-KK-A6E0", "TCGA-KK-A7AW",
                     "TCGA-V1-A8WL", "TCGA-V1-A9O9", "TCGA-X4-A8KQ", "TCGA-YL-A9WY"]
    },
    "test": {
        "lung": ["TCGA-49-6743", "TCGA-50-6591", "TCGA-55-7570", "TCGA-55-7573",
                 "TCGA-73-4662", "TCGA-78-7152", "TCGA-MP-A4T7"],
        "kidney": ["TCGA-2Z-A9JG", "TCGA-2Z-A9JN", "TCGA-DW-7838", "TCGA-DW-7963",
                   "TCGA-F9-A8NY", "TCGA-IZ-A6M9", "TCGA-MH-A55W"],
        "breast": ["TCGA-A2-A04X", "TCGA-A2-A0ES", "TCGA-D8-A3Z6", "TCGA-E2-A108", "TCGA-EW-A6SB"],
        "prostate": ["TCGA-G9-6356", "TCGA-G9-6367", "TCGA-VP-A87E", "TCGA-VP-A87H", "TCGA-X4-A8KS", "TCGA-YL-A9WL"]
    },
}


def _download_monusac(path, download, split):
    assert split in ["train", "test"], "Please choose from train/test"

    # check if we have extracted the images and labels already
    im_path = os.path.join(path, "images", split)
    label_path = os.path.join(path, "labels", split)
    if os.path.exists(im_path) and os.path.exists(label_path):
        return

    os.makedirs(path, exist_ok=True)
    zip_path = os.path.join(path, f"monusac_{split}.zip")
    util.download_source_gdrive(zip_path, URL[split], download=download, checksum=CHECKSUM[split])

    _process_monusac(path, split)


def _process_monusac(path, split):
    util.unzip(os.path.join(path, f"monusac_{split}.zip"), path)

    # assorting the images into expected dir;
    # converting the label xml files to numpy arrays (of same dimension as input images) in the expected dir
    root_img_save_dir = os.path.join(path, "images", split)
    root_label_save_dir = os.path.join(path, "labels", split)

    os.makedirs(root_img_save_dir, exist_ok=True)
    os.makedirs(root_label_save_dir, exist_ok=True)

    all_patient_dir = sorted(glob(os.path.join(path, "MoNuSAC*", "*")))

    for patient_dir in tqdm(all_patient_dir, desc=f"Converting {split} inputs for all patients"):
        all_img_dir = sorted(glob(os.path.join(patient_dir, "*.tif")))
        all_xml_label_dir = sorted(glob(os.path.join(patient_dir, "*.xml")))

        if len(all_img_dir) != len(all_xml_label_dir):
            _convert_missing_tif_from_svs(patient_dir)
            all_img_dir = sorted(glob(os.path.join(patient_dir, "*.tif")))

        assert len(all_img_dir) == len(all_xml_label_dir)

        for img_path, xml_label_path in zip(all_img_dir, all_xml_label_dir):
            desired_label_shape = imageio.imread(img_path).shape[:-1]

            img_id = os.path.split(img_path)[-1]
            dst = os.path.join(root_img_save_dir, img_id)
            shutil.move(src=img_path, dst=dst)

            _label = util.generate_labeled_array_from_xml(shape=desired_label_shape, xml_file=xml_label_path)
            _fileid = img_id.split(".")[0]
            imageio.imwrite(os.path.join(root_label_save_dir, f"{_fileid}.tif"), _label)

    shutil.rmtree(glob(os.path.join(path, "MoNuSAC*"))[0])


def _convert_missing_tif_from_svs(patient_dir):
    """This function activates when we see some missing tiff inputs (and converts svs to tiff)

    Cause: Happens only in the test split, maybe while converting the data, some were missed
    Fix: We have the original svs scans. We convert the svs scans to tiff
    """
    all_svs_dir = sorted(glob(os.path.join(patient_dir, "*.svs")))
    for svs_path in all_svs_dir:
        save_tif_path = os.path.splitext(svs_path)[0] + ".tif"
        if not os.path.exists(save_tif_path):
            img_array = util.convert_svs_to_tiff(svs_path)
            imageio.imwrite(save_tif_path, img_array)


def get_patient_id(path, split_wrt="-01Z-00-"):
    """Gets us the patient id in the expected format
    Input Names: "TCGA-<XX>-<XXXX>-01z-00-DX<X>-(<X>, <00X>).tif" (example: TCGA-2Z-A9JG-01Z-00-DX1_1.tif)
    Expected: "TCGA-<XX>-<XXXX>"                                  (example: TCGA-2Z-A9JG)
    """
    patient_image_id = Path(path).stem
    patient_id = patient_image_id.split(split_wrt)[0]
    return patient_id


def get_monusac_dataset(
    path, patch_shape, split, organ_type: Optional[List[str]] = None, download=False,
    offsets=None, boundaries=False, binary=False, **kwargs
):
    """Dataset from https://monusac-2020.grand-challenge.org/Data/
    """
    _download_monusac(path, download, split)

    image_paths = sorted(glob(os.path.join(path, "images", split, "*")))
    label_paths = sorted(glob(os.path.join(path, "labels", split, "*")))

    if organ_type is not None:
        # get all patients for multiple organ selection
        all_organ_splits = sum([ORGAN_SPLITS[split][o] for o in organ_type], [])

        image_paths = [_path for _path in image_paths if get_patient_id(_path) in all_organ_splits]
        label_paths = [_path for _path in label_paths if get_patient_id(_path) in all_organ_splits]

    kwargs, _ = util.add_instance_label_transform(
        kwargs, add_binary_target=True, binary=binary, boundaries=boundaries, offsets=offsets
    )
    return torch_em.default_segmentation_dataset(
        image_paths, None, label_paths, None, patch_shape, is_seg_dataset=False, **kwargs
    )


def get_monusac_loader(
    path, patch_shape, split, batch_size, organ_type=None, download=False,
    offsets=None, boundaries=False, binary=False, **kwargs
):
    ds_kwargs, loader_kwargs = util.split_kwargs(
        torch_em.default_segmentation_dataset, **kwargs
    )
    dataset = get_monusac_dataset(
        path, patch_shape, split, organ_type=organ_type, download=download,
        offsets=offsets, boundaries=boundaries, binary=binary, **ds_kwargs
    )
    loader = torch_em.get_data_loader(dataset, batch_size, **loader_kwargs)
    return loader
