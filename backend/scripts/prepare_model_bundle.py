"""Chuẩn bị một phiên bản model cho backend (backend_design 8.1): chép đúng 24 model + 24 metadata vào
`<dest>/<name>/` và ghi `MANIFEST.sha256`.

    python -m scripts.prepare_model_bundle --name v1-no_fill            # từ ml/ml_xgb/models vào models/xgb
    python -m scripts.prepare_model_bundle --name v1-no_fill --check    # chỉ kiểm tra bundle đã có

Thư mục phiên bản đã dùng không được sửa: nếu đích đã có mà nội dung khác thì dừng, không ghi đè.
Có manifest đã commit (`docker/models/<name>.sha256`) thì đối chiếu checksum từng file.
"""

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HORIZONS = range(3, 73, 3)
MANIFEST = "MANIFEST.sha256"


def bundle_files(horizons=HORIZONS) -> list[str]:
    """Tên 48 file của một bộ model: xgb_AQI_h{h}.json và .meta.json cho mỗi horizon."""
    return [f"xgb_AQI_h{h}{ext}" for h in horizons for ext in (".json", ".meta.json")]


def sha256_file(path: Path) -> str:
    """SHA-256 của một file (đọc từng khối)."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_text(folder: Path, names: list[str]) -> str:
    """Nội dung manifest dạng `sha256sum`: "<sha256>  <tên file>", sắp theo tên."""
    return "".join(f"{sha256_file(folder / n)}  {n}\n" for n in sorted(names))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", required=True, help="tên thư mục phiên bản, vd v1-no_fill")
    ap.add_argument("--source", type=Path, default=REPO / "ml" / "ml_xgb" / "models")
    ap.add_argument("--dest", type=Path, default=REPO / "models" / "xgb")
    ap.add_argument("--check", action="store_true", help="chỉ kiểm tra bundle ở đích")
    args = ap.parse_args(argv)

    names = bundle_files()
    target = args.dest / args.name
    committed = REPO / "docker" / "models" / f"{args.name}.sha256"

    if not args.check:
        missing = [n for n in names if not (args.source / n).is_file()]
        if missing:
            print(f"Thiếu {len(missing)} file trong {args.source}: {missing[:3]}…", file=sys.stderr)
            return 1
        expected = manifest_text(args.source, names)
        if target.exists():
            if (target / MANIFEST).is_file() and (target / MANIFEST).read_text() == expected:
                print(f"{target} đã có đúng bộ model, không chép lại.")
            else:
                print(f"{target} đã tồn tại với nội dung khác: không ghi đè (thư mục đã dùng không được sửa).",
                      file=sys.stderr)  # fmt: skip
                return 1
        else:
            target.mkdir(parents=True)
            for n in names:
                shutil.copy2(args.source / n, target / n)
            (target / MANIFEST).write_text(expected)
            print(f"Đã chép {len(names)} file vào {target}.")

    actual = manifest_text(target, names)
    if (target / MANIFEST).read_text() != actual:
        print(f"Checksum trong {target} không khớp MANIFEST.sha256.", file=sys.stderr)
        return 1
    if committed.is_file() and committed.read_text() != actual:
        print(f"Bundle khác manifest đã commit {committed.relative_to(REPO)}.", file=sys.stderr)
        return 1
    print(
        f"OK: {len(names)} file khớp checksum" + (f" và {committed.relative_to(REPO)}." if committed.is_file() else ".")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
