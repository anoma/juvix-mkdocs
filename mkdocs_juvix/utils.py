import hashlib
import logging
import os
from functools import lru_cache
from pathlib import Path
import pickle
from typing import Any, Iterable, Optional

from mkdocs.config.defaults import MkDocsConfig
import trio

log = logging.getLogger("mkdocs")
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
    subdirs = [base_dir / "images"] + list(subdirs)
    for subdir in subdirs:
        full_path = Path(subdir) / filepath.name
        if full_path.exists():
            return full_path.absolute().as_posix()
    return None


def fix_site_url(config: MkDocsConfig) -> MkDocsConfig:
    site_url = os.getenv("SITE_URL")

    if site_url:
        config["site_url"] = site_url
    else:
        mike_docs_version = os.getenv("MIKE_DOCS_VERSION")
        if mike_docs_version:
            log.debug(
                f"Using MIKE_DOCS_VERSION environment variable: {mike_docs_version}"
            )
            config["docs_version"] = mike_docs_version

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
def get_filepath_for_cached_hash_for(filepath: Path, hash_dir: Optional[Path] = None) -> Path:
    """
    Get the filepath for the cached hash of a file.
    """
    file_abspath = filepath.absolute()
    hash_filename = hashlib.sha256(
        file_abspath.as_posix().encode("utf-8")
    ).hexdigest()

    if hash_dir is None:
        return Path(hash_filename)

    return hash_dir / hash_filename

class Tracer(trio.abc.Instrument):
    def before_run(self):
        print("!!! run started")

    def _print_with_task(self, msg, task):
        # repr(task) is perhaps more useful than task.name in general,
        # but in context of a tutorial the extra noise is unhelpful.
        print(f"{msg}: {task.name}")

    def task_spawned(self, task):
        self._print_with_task("### new task spawned", task)

    def task_scheduled(self, task):
        self._print_with_task("### task scheduled", task)

    def before_task_step(self, task):
        self._print_with_task(">>> about to run one step of task", task)

    def after_task_step(self, task):
        self._print_with_task("<<< task step finished", task)

    def task_exited(self, task):
        self._print_with_task("### task exited", task)

    def before_io_wait(self, timeout):
        if timeout:
            print(f"### waiting for I/O for up to {timeout} seconds")
        else:
            print("### doing a quick check for I/O")
        self._sleep_time = trio.current_time()

    def after_io_wait(self, timeout):
        duration = trio.current_time() - self._sleep_time
        print(f"### finished I/O check (took {duration} seconds)")

    def after_run(self):
        print("!!! run finished")