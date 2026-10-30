"""Image read/write. OpenCV only reads EXR when OPENCV_IO_ENABLE_OPENEXR is set
before cv2 is imported, so every module goes through here."""

from __future__ import annotations

import os

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

EXR_HALF_ZIP = [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_HALF,
                cv2.IMWRITE_EXR_COMPRESSION, cv2.IMWRITE_EXR_COMPRESSION_ZIP]


def read_image(path: str, *, keep_alpha: bool = False) -> np.ndarray:
    """Any OpenCV-readable image -> float32 RGB(A) (integers scaled to 0-1)."""
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RuntimeError(f"could not read image {path}")
    if img.dtype == np.uint8:
        img = img.astype(np.float32) / 255.0
    elif img.dtype == np.uint16:
        img = img.astype(np.float32) / 65535.0
    else:
        img = img.astype(np.float32, copy=False)
    if img.ndim == 2:
        return img[..., None].repeat(3, axis=2) if not keep_alpha else img
    if img.shape[2] == 4:
        rgb = img[..., 2::-1]
        return np.concatenate([rgb, img[..., 3:4]], axis=2) if keep_alpha else np.ascontiguousarray(rgb)
    return np.ascontiguousarray(img[..., ::-1])


def write_exr(path: str, img: np.ndarray) -> None:
    """float RGB [H,W,3] or single channel [H,W] -> half-float ZIP EXR."""
    data = img if img.ndim == 2 else img[..., ::-1]
    if not cv2.imwrite(path, np.ascontiguousarray(data, dtype=np.float32), EXR_HALF_ZIP):
        raise RuntimeError(f"could not write {path} (disk full or no permission?)")


def write_png16(path: str, mask: np.ndarray) -> None:
    img = (np.clip(mask, 0.0, 1.0) * 65535.0 + 0.5).astype(np.uint16)
    if not cv2.imwrite(path, img):
        raise RuntimeError(f"could not write {path}")


def resize(img: np.ndarray, width: int, height: int) -> np.ndarray:
    if img.shape[1] == width and img.shape[0] == height:
        return img
    interp = cv2.INTER_AREA if img.shape[1] > width else cv2.INTER_LINEAR
    return cv2.resize(img, (width, height), interpolation=interp)
