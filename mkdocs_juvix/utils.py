import hashlib
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urljoin

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.utils import get_markdown_title

log = logging.getLogger("mkdocs")


def fix_site_url(config: MkDocsConfig) -> MkDocsConfig:

    if os.environ.get("SITE_URL"):
        config["site_url"] = os.environ["SITE_URL"]
        if not config["site_url"].endswith("/"):
            config["site_url"] += "/"
        return config

    log.info("SITE_URL environment variable not set")

    version = os.environ.get("MIKE_DOCS_VERSION")

    if version:
        log.info(f"Using MIKE_DOCS_VERSION environment variable: {version}")

    if not config["site_url"].endswith("/"):
        config["site_url"] += "/"

    log.info(f"site_url: {config['site_url']}")
    config["docs_version"] = version

    log.info(f"Set site_url to {config['site_url']}")
    os.environ["SITE_URL"] = config["site_url"]
    return config


def compute_sha_over_folder(_folder_path: Path) -> str:
    """Compute the sha with respect to the structure of a folder."""

    folder_path = _folder_path.absolute().as_posix()
    sha_hash: hashlib._Hash = hashlib.sha256()
    for root, dirs, files in os.walk(folder_path):
        for names in sorted(dirs):
            sha_hash.update(names.encode("utf-8"))
        for filename in sorted(files):
            file_path = os.path.join(root, filename)
            sha_hash.update(file_path.encode("utf-8"))
            hash_file_hash_obj(sha_hash, Path(file_path))
    return sha_hash.hexdigest()


def hash_file_hash_obj(hash_obj, filepath: Path):
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            hash_obj.update(chunk)


def hash_file(_filepath: Path):
    filepath = _filepath.absolute()
    _hash_obj = hashlib.sha256()
    hash_file_hash_obj(_hash_obj, filepath)
    return _hash_obj.hexdigest()


@lru_cache(maxsize=128)
def compute_hash_filepath(_filepath: Path, hash_dir: Optional[Path] = None) -> Path:
    """
    Computes the hash file path location for the given file path.
    """
    hash_obj = hashlib.sha256()
    filepath = _filepath.absolute()
    hash_obj.update(filepath.as_posix().encode("utf8"))
    hash_filename = hash_obj.hexdigest()
    if hash_dir is None:
        return Path(hash_filename)
    return hash_dir.joinpath(hash_filename)
