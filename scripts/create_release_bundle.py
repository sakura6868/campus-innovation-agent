"""生成不含运行数据与密钥的参赛源码归档包，并写出 SHA-256 清单。

用法：
    python scripts/create_release_bundle.py
    python scripts/create_release_bundle.py --output-dir /tmp/release --version v0.5
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INCLUDE_DIRS = (
    "src",
    "frontend",
    "docs",
    "evals",
    "submission",
    "tests",
    "scripts",
    "data/ground_truth",
    "demo",
)
DEFAULT_INCLUDE_FILES = (
    "README.md",
    "参赛作品说明.md",
    "requirements.txt",
    "Dockerfile",
    "compose.yaml",
    "render.yaml",
    "start.ps1",
    "start.sh",
    ".env.example",
    ".gitignore",
)
EXCLUDED_PARTS = {
    "__pycache__", ".git", ".github", "venv", "venv312", "design-concepts", "backups", "tmp", "voice-previews"
}
EXCLUDED_SUFFIXES = {".db", ".sqlite3", ".pyc", ".pyo", ".zip"}
EXCLUDED_NAMES = {".env", "campus_agent.db"}


def should_include(path: Path) -> bool:
    """只保留可复现的源码、文档和 Ground Truth，不打包运行产物或密钥。"""
    relative = path.relative_to(PROJECT_ROOT)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if path.name in EXCLUDED_NAMES or path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    relative = path.relative_to(PROJECT_ROOT)
    if relative.parts and relative.parts[0] == "demo" and path.suffix.lower() in {".mp4", ".mov", ".webm"}:
        return False
    return path.is_file()


def collect_files() -> list[Path]:
    files: list[Path] = []
    for name in DEFAULT_INCLUDE_FILES:
        candidate = PROJECT_ROOT / name
        if candidate.is_file() and should_include(candidate):
            files.append(candidate)
    for name in DEFAULT_INCLUDE_DIRS:
        directory = PROJECT_ROOT / name
        if directory.is_dir():
            files.extend(path for path in directory.rglob("*") if should_include(path))
    return sorted(set(files), key=lambda path: path.relative_to(PROJECT_ROOT).as_posix())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="生成校园科创导航智能体参赛源码包")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "backups"), help="归档输出目录")
    parser.add_argument("--version", default="v0.5", help="归档文件名中的版本号")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bundle_name = f"campus-innovation-agent-{args.version}-{stamp}"
    archive_path = output_dir / f"{bundle_name}.zip"
    manifest_path = output_dir / f"{bundle_name}.sha256"
    archive_root = PurePosixPath(bundle_name)
    files = collect_files()

    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(PROJECT_ROOT).as_posix()
            archive.write(path, (archive_root / relative).as_posix())

    manifest_lines = [f"{sha256_file(archive_path)}  {archive_path.name}", "", "# archive members"]
    manifest_lines.extend(
        f"{sha256_file(path)}  {path.relative_to(PROJECT_ROOT).as_posix()}" for path in files
    )
    manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    print(f"archive: {archive_path}")
    print(f"sha256:  {manifest_path}")
    print(f"files:   {len(files)}")


if __name__ == "__main__":
    main()
