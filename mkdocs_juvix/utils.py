import hashlib
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from mkdocs.config.defaults import MkDocsConfig

log = logging.getLogger("mkdocs")


def fix_site_url(config: MkDocsConfig) -> MkDocsConfig:
    site_url = os.getenv("SITE_URL")

    if site_url:
        config["site_url"] = site_url
    else:
        log.info("SITE_URL environment variable not set")

        mike_docs_version = os.getenv("MIKE_DOCS_VERSION")
        if mike_docs_version:
            log.info(
                f"Using MIKE_DOCS_VERSION environment variable: {mike_docs_version}"
            )
            config["docs_version"] = mike_docs_version

    # Ensure site_url ends with a slash
    if not config["site_url"].endswith("/"):
        config["site_url"] += "/"

    log.info(f"site_url: {config['site_url']}")

    os.environ["SITE_URL"] = config["site_url"]
    return config


def compute_sha_over_folder(_folder_path: Path) -> str:
    """Compute the SHA-256 hash of a folder's structure and contents."""
    folder_path = _folder_path.absolute()
    sha_hash = hashlib.sha256()

    for item in sorted(folder_path.glob("**/*")):
        relative_path = item.relative_to(folder_path).as_posix()
        sha_hash.update(relative_path.encode("utf-8"))

        if item.is_file():
            hash_file_hash_obj(sha_hash, item)

    return sha_hash.hexdigest()


def hash_file_hash_obj(hash_obj, filepath: Path):
    """Update the hash object with the contents of a file."""
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_obj.update(chunk)


def hash_file(_filepath: Path) -> str:
    """Compute the SHA-256 hash of a file."""
    filepath = _filepath.absolute()
    hash_obj = hashlib.sha256()
    hash_file_hash_obj(hash_obj, filepath)
    return hash_obj.hexdigest()


@lru_cache(maxsize=128)
def compute_hash_filepath(filepath: Path, hash_dir: Optional[Path] = None) -> Path:
    hash_filename = hashlib.sha256(
        filepath.absolute().as_posix().encode("utf-8")
    ).hexdigest()

    if hash_dir is None:
        return Path(hash_filename)

    return hash_dir / hash_filename
