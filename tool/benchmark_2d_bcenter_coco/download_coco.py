"""COCO val2017 다운로드.

사용법:
    python download_coco.py --root ./data                # annotations만 (241MB)
    python download_coco.py --root ./data --full-images  # val2017 전체 이미지 포함 (~1GB)

전체 이미지 없이도 filter_coco.py의 --download-images 옵션으로
필터된 이미지만 개별 다운로드할 수 있으므로, 기본은 annotations만 받는다.
"""
import argparse
import urllib.request
import zipfile
from pathlib import Path

ANN_URL = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
IMG_URL = "http://images.cocodataset.org/zips/val2017.zip"


def download(url: str, dst: Path):
    if dst.exists():
        print(f"[skip] {dst} 이미 존재")
        return
    print(f"[down] {url} -> {dst}")

    def hook(n, size, total):
        done = n * size / max(total, 1)
        print(f"\r  {done / 1e6:8.1f}MB / {total / 1e6:.1f}MB", end="")

    urllib.request.urlretrieve(url, dst, reporthook=hook)
    print()


def extract(zip_path: Path, root: Path):
    print(f"[extract] {zip_path}")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(root)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="./data", help="데이터 저장 루트")
    ap.add_argument("--full-images", action="store_true", help="val2017 전체 이미지(~1GB)도 다운로드")
    args = ap.parse_args()

    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)

    ann_zip = root / "annotations_trainval2017.zip"
    download(ANN_URL, ann_zip)
    if not (root / "annotations" / "instances_val2017.json").exists():
        extract(ann_zip, root)

    if args.full_images:
        img_zip = root / "val2017.zip"
        download(IMG_URL, img_zip)
        if not (root / "val2017").exists():
            extract(img_zip, root)

    print("[done]")
    print(f"  annotations: {root / 'annotations' / 'instances_val2017.json'}")
    if args.full_images:
        print(f"  images:      {root / 'val2017'}")


if __name__ == "__main__":
    main()
