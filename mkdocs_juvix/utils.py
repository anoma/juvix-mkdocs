import hashlib
import os
import pickle
import time
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any, Iterable, Optional

from colorama import Fore, Style  # type: ignore
from mkdocs.config.defaults import MkDocsConfig

from mkdocs_juvix.logger import PrefixedLogger, log

EXCLUDED_DIRS = {
    ".git",
    ".hooks",
    "env",
    "venv",
    ".github",
    ".juvix_build",
    ".vscode",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
    "build",
    "dist",
    ".idea",
}


def is_juvix_markdown_file(filepath: Path) -> bool:
    return filepath.as_posix().endswith(".juvix.md")


def is_pure_juvix_file(filepath: Path) -> bool:
    return filepath.as_posix().endswith(".juvix")


def is_isabelle_file(filepath: Path) -> bool:
    return filepath.as_posix().endswith(".thy")


def is_juvix_file(filepath: Path) -> bool:
    return is_juvix_markdown_file(filepath) or is_pure_juvix_file(filepath)


def is_excluded(entry):
    return (
        entry.name in EXCLUDED_DIRS
        or entry.name.startswith(".")
        or entry.name.endswith("~")
        or entry.name.endswith(".pyc")
    )


def get_filtered_subdirs(base_dir):
    for entry in os.scandir(base_dir):
        if entry.is_dir() and not is_excluded(entry):
            yield entry.path
            yield from get_filtered_subdirs(entry.path)


def get_all_subdirs(dir_path):
    try:
        for entry in os.scandir(dir_path):
            if entry.is_dir() and not is_excluded(entry):
                yield entry.path
                yield from get_all_subdirs(entry.path)
    except PermissionError:
        log.warning(f"Permission denied: {dir_path}")
    except OSError as e:
        log.error(f"Error accessing {dir_path}: {e}")


def find_file_in_subdirs(
    base_dir: Path, subdirs: Iterable[Path], filepath: Path
) -> Optional[str]:
    full_path = base_dir / filepath
    if full_path.exists():
        return full_path.absolute().as_posix()
    subdirs = [base_dir / "images"] + list(set(subdirs))
    for subdir in subdirs:
        full_path = Path(subdir) / filepath.name
        if full_path.exists():
            if full_path.is_file():
                return full_path.absolute().as_posix()
            else:
                log.error(f"Found directory {full_path} instead of file")
    return None


def fix_site_url(config: MkDocsConfig) -> MkDocsConfig:
    site_url = os.getenv("SITE_URL")
    if site_url:
        config["site_url"] = site_url
    # Ensure site_url ends with a slash
    if not config.get("site_url", None):
        config["site_url"] = ""
    if not config["site_url"].endswith("/"):
        config["site_url"] += "/"

    log.debug(f"site_url: {config['site_url']}")
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


def hash_object(obj: Any) -> str:
    return hashlib.sha256(pickle.dumps(obj)).hexdigest()


def hash_content_of(filepath: Path) -> str:
    """Compute the SHA-256 hash of a file."""
    hash_obj = hashlib.sha256()
    hash_file_hash_obj(hash_obj, filepath.absolute())
    return hash_obj.hexdigest()


@lru_cache(maxsize=128)
def get_filepath_for_cached_hash_for(
    filepath: Path, hash_dir: Optional[Path] = None
) -> Path:
    """
    Get the filepath for the cached hash of a file.
    """
    file_abspath = filepath.absolute()
    hash_filename = hashlib.sha256(file_abspath.as_posix().encode("utf-8")).hexdigest()

    if hash_dir is None:
        return Path(hash_filename)

    return hash_dir / hash_filename


def time_spent(
    log: PrefixedLogger,
    message: Optional[Any] = None,
    print_result: bool = False,
):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            result = None
            exception = None
            if message:
                log_message = f"{Fore.YELLOW}{message} ...{Style.RESET_ALL}"
                if os.getenv("DEBUG", False):
                    log.info(log_message)
            try:
                result = func(*args, **kwargs)
            except Exception as e:
                exception = e

            end_time = time.time()
            elapsed_time = end_time - start_time
            log_message = (
                f"done in {Fore.BLUE}{elapsed_time:.3f} seconds{Style.RESET_ALL}"
            )
            if print_result and result:
                log_message = f"`{func.__name__} =>` {result} - {log_message}"
            if not print_result:
                log_message = f"`{func.__name__}` - {log_message}"
            if os.getenv("DEBUG", False):
                log.info(log_message)
            if exception:
                raise exception
            return result

        return wrapper

    return decorator
