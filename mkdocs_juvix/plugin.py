import json
import logging
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import pathspec
from mkdocs.config.defaults import MkDocsConfig
from mkdocs.plugins import BasePlugin
from mkdocs.structure.files import Files
from mkdocs.structure.pages import Page
from watchdog.events import FileSystemEvent

from mkdocs_juvix.utils import (
    compute_hash_filepath,
    compute_sha_over_folder,
    fix_site_url,
    hash_file,
)

log: logging.Logger = logging.getLogger("mkdocs")


def get_juvix_version(juvix_bin: str) -> Optional[str]:
    try:
        result = subprocess.run(
            [juvix_bin, "--numeric-version"],
            stdout=subprocess.PIPE,
            check=True,
            text=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        log.error("Failed to get Juvix version: %s", e)
        return None


def generate_css_file(css_file: Path, version: Optional[str] = None) -> Optional[Path]:
    css_file.parent.mkdir(parents=True, exist_ok=True)
    css_file.write_text(
        f"""
code.juvix::after {{
    font-family: var(--md-code-font-family);
    content: "Juvix v{version}";
    font-size: 10px;
    color: var(--md-juvix-codeblock-footer);
    float: right;
}}
"""
    )
    log.info("CSS file generated at %s.", css_file)
    return css_file


class JuvixPlugin(BasePlugin):
    mkconfig: MkDocsConfig
    juvix_md_files: List[Dict[str, Any]]

    site_dir: Optional[str]
    site_url: str
    ROOT_DIR: Path
    DOCS_DIR: Path
    CACHE_DIR: Path
    MARKDOWN_JUVIX_OUTPUT: Path

    JUVIX_ENABLED: bool = bool(os.environ.get("JUVIX_ENABLED", True))
    REMOVE_CACHE: bool = bool(os.environ.get("REMOVE_CACHE", False))
    JUVIX_AVAILABLE: bool

    JUVIX_VERSION: Optional[str] = None
    JUVIX_BIN: str = os.environ.get("JUVIX_BIN", "juvix")
    JUVIXCODE_CACHE_DIR: Path
    JUVIXCODE_HASH_FILE: Path
    HASH_DIR: Path
    HTML_CACHE_DIR: Path
    FIRST_RUN: bool = True

    JUVIX_FOOTER_CSS_FILE: Path
    CACHE_JUVIX_VERSION_FILE: Path

    def on_config(self, config: MkDocsConfig, **kwargs) -> MkDocsConfig:
        config_file = config.config_file_path
        self.ROOT_DIR = Path(config_file).parent.absolute()

        self.DOCS_DIR = self.ROOT_DIR / config.get("docs_dir", "docs")
        self.CACHE_DIR = self.ROOT_DIR / ".hooks"

        if self.REMOVE_CACHE:
            log.info("Removing Juvix Plugin cache directories.")
            shutil.rmtree(self.CACHE_DIR, ignore_errors=True)

        self.MARKDOWN_JUVIX_OUTPUT = self.CACHE_DIR / ".MD"
        self.MARKDOWN_JUVIX_OUTPUT.mkdir(parents=True, exist_ok=True)

        self.JUVIXCODE_CACHE_DIR = self.CACHE_DIR / ".JUVIX_MD"
        self.JUVIXCODE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        self.JUVIXCODE_HASH_FILE = self.CACHE_DIR / ".hash_juvix_md"

        self.HTML_CACHE_DIR = self.CACHE_DIR / ".HTML"
        self.HTML_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        self.FIRST_RUN = True

        self.HASH_DIR = self.CACHE_DIR / ".HASH"
        self.HASH_DIR.mkdir(parents=True, exist_ok=True)

        self.JUVIX_AVAILABLE = shutil.which(self.JUVIX_BIN) is not None
        if not self.JUVIX_AVAILABLE:
            self.JUVIX_ENABLED = False

        if self.JUVIX_ENABLED:
            try:
                subprocess.run([self.JUVIX_BIN, "--version"], capture_output=True)
            except FileNotFoundError:
                log.warning(
                    "The Juvix binary is not available. Please install Juvix and make sure it's available in the PATH."
                )
            cmd = [self.JUVIX_BIN, "--numeric-version"]
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode == 0:
                JUVIX_VERSION = result.stdout.decode("utf-8")
                log.info(
                    f"Using Juvix v{JUVIX_VERSION} to render Juvix Markdown files."
                )

        self.JUVIX_FOOTER_CSS_FILE = (
            self.DOCS_DIR / "assets" / "css" / "juvix_codeblock_footer.css"
        )
        self.JUVIX_FOOTER_CSS_FILE.parent.mkdir(parents=True, exist_ok=True)

        self.CACHE_JUVIX_VERSION_FILE = self.CACHE_DIR / ".juvix-version"

        config = fix_site_url(config)
        self.mkconfig = config

        # Add CSS file to extra_css
        config["extra_css"].append(
            self.JUVIX_FOOTER_CSS_FILE.relative_to(self.DOCS_DIR).as_posix()
        )

        self.juvix_md_files: List[Dict[str, Any]] = []

        self.site_dir = config.get("site_dir", None)
        self.site_url = config.get("site_url", "")

        if not self.JUVIX_AVAILABLE:
            log.info(
                "Juvix is not available on the system. check the JUVIX_BIN environment variable."
            )

        return config

    def on_files(self, files: Files, *, config: MkDocsConfig) -> Optional[Files]:
        _files = []
        for file in files:
            if not file.abs_src_path:
                continue
            if ".juvix-build" not in file.abs_src_path:
                _files.append(file)
        return Files(_files)

    def on_page_read_source(self, page: Page, config: MkDocsConfig) -> Optional[str]:
        if not page.file.abs_src_path:
            return None

        filepath = Path(page.file.abs_src_path)

        if (
            not filepath.as_posix().endswith(".juvix.md")
            or not self.JUVIX_ENABLED
            or not self.JUVIX_AVAILABLE
        ):
            return None

        output = self.generate_markdown(filepath)
        if not output:
            log.error(f"Error generating markdown for file: {filepath}")

        return output

    def on_post_build(self, config: MkDocsConfig) -> None:
        if self.JUVIX_ENABLED and self.JUVIX_AVAILABLE:
            self.generate_html(generate=False, move_cache=True)

    def on_serve(self, server: Any, config: MkDocsConfig, builder: Any) -> None:
        gitignore = None
        if (gitignore_file := self.ROOT_DIR / ".gitignore").exists():
            with open(gitignore_file) as file:
                gitignore = pathspec.PathSpec.from_lines(
                    pathspec.patterns.GitWildMatchPattern,
                    file,  # type: ignore
                )

        def callback_wrapper(
            callback: Callable[[FileSystemEvent], None],
        ) -> Callable[[FileSystemEvent], None]:
            def wrapper(event: FileSystemEvent) -> None:
                if gitignore and gitignore.match_file(
                    Path(event.src_path).relative_to(config.docs_dir).as_posix()  # type: ignore
                ):
                    return

                fpath: Path = Path(event.src_path).absolute()  # type: ignore
                fpathstr: str = fpath.as_posix()

                if ".juvix-build" in fpathstr:
                    return

                if fpathstr.endswith(".juvix.md"):
                    log.debug("Juvix file changed: %s", fpathstr)
                return callback(event)

            return wrapper

        handler = (
            next(
                handler
                for watch, handler in server.observer._handlers.items()
                if watch.path == config.docs_dir
            )
            .copy()
            .pop()
        )
        handler.on_any_event = callback_wrapper(handler.on_any_event)

    def on_page_markdown(
        self, markdown: str, page: Page, config: MkDocsConfig, files: Files
    ) -> Optional[str]:
        path = page.file.abs_src_path
        if path and not path.endswith(".juvix.md"):
            return markdown

        page.file.name = page.file.name.replace(".juvix", "")
        page.file.url = page.file.url.replace(".juvix", "")
        page.file.dest_uri = page.file.dest_uri.replace(".juvix", "")
        page.file.abs_dest_path = page.file.abs_dest_path.replace(".juvix", "")

        return markdown

    def move_html_cache_to_site_dir(self, filepath: Path, site_dir: Path) -> None:
        rel_to_docs = filepath.relative_to(self.DOCS_DIR)
        if filepath.is_dir():
            dest_folder = site_dir / rel_to_docs
        else:
            dest_folder = site_dir / rel_to_docs.parent

        dest_folder.mkdir(parents=True, exist_ok=True)

        # Patch: remove all the .html files in the destination folder of the
        # Juvix Markdown file to not lose the generated HTML files in the site
        # directory.

        for _file in self.JUVIXCODE_CACHE_DIR.rglob("*.juvix.md"):
            file = _file.absolute()

            html_file_path = (
                self.HTML_CACHE_DIR
                / file.relative_to(self.JUVIXCODE_CACHE_DIR).parent
                / file.name.replace(".juvix.md", ".html")
            )

            if html_file_path.exists():
                log.info(f"Removing file: {html_file_path}")
                html_file_path.unlink()

        index_file = self.HTML_CACHE_DIR / "index.html"
        if index_file.exists():
            index_file.unlink()

        # move the generated HTML files to the site directory
        shutil.copytree(self.HTML_CACHE_DIR, dest_folder, dirs_exist_ok=True)
        return

    def new_or_changed_or_no_exist(self, filepath: Path) -> bool:
        content_hash = hash_file(filepath)
        path_hash = compute_hash_filepath(filepath, hash_dir=self.HASH_DIR)
        if not path_hash.exists():
            log.debug(f"File: {filepath} does not have a hash file.")
            return True
        fresh_content_hash = path_hash.read_text()
        return content_hash != fresh_content_hash

    def on_pre_build(self, config: MkDocsConfig) -> None:
        if self.FIRST_RUN:
            try:
                subprocess.run(
                    [self.JUVIX_BIN, "dependencies", "update"], capture_output=True
                )
            except Exception as e:
                if self.JUVIX_ENABLED and self.JUVIX_AVAILABLE:
                    log.error(
                        f"A problem occurred while updating Juvix dependencies: {e}"
                    )
                return

        # New code for CSS generation
        version = get_juvix_version(self.JUVIX_BIN)
        if version is None:
            log.error(
                "Cannot generate CSS file without Juvix version. Make sure Juvix is installed."
            )
        else:
            need_to_write = (
                not self.CACHE_JUVIX_VERSION_FILE.exists()
                or not self.JUVIX_FOOTER_CSS_FILE.exists()
            )
            read_version = (
                self.CACHE_JUVIX_VERSION_FILE.read_text().strip()
                if not need_to_write
                else None
            )
            if read_version != version:
                self.CACHE_JUVIX_VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
                self.CACHE_JUVIX_VERSION_FILE.write_text(version)
                need_to_write = True
            if need_to_write:
                generate_css_file(self.JUVIX_FOOTER_CSS_FILE, version)

        for _file in self.DOCS_DIR.rglob("*.juvix.md"):
            file: Path = _file.absolute()
            relative_to: Path = file.relative_to(self.DOCS_DIR)
            url = urljoin(
                self.site_url, relative_to.as_posix().replace(".juvix.md", ".html")
            )
            self.juvix_md_files.append(
                {
                    "module_name": self.unqualified_module_name(file),
                    "qualified_module_name": self.qualified_module_name(file),
                    "url": url,
                    "file": file.absolute().as_posix(),
                }
            )
            self.generate_markdown(file)

        self.juvix_md_files.sort(key=lambda x: x["qualified_module_name"])
        juvix_modules = self.CACHE_DIR.joinpath("juvix_modules.json")

        if juvix_modules.exists():
            juvix_modules.unlink()

        with open(juvix_modules, "w") as f:
            json.dump(self.juvix_md_files, f, indent=4)

        sha_filecontent = (
            self.JUVIXCODE_HASH_FILE.read_text()
            if self.JUVIXCODE_HASH_FILE.exists()
            else None
        )

        current_sha: str = compute_sha_over_folder(self.JUVIXCODE_CACHE_DIR)
        equal_hashes = current_sha == sha_filecontent

        log.info("Computed Juvix content hash: %s", current_sha)
        if not equal_hashes:
            log.info("Cache Juvix content hash: %s", sha_filecontent)
        else:
            log.info("The Juvix Markdown content has not changed.")

        generate: bool = (
            self.JUVIX_ENABLED
            and self.JUVIX_AVAILABLE
            and (
                not equal_hashes
                or (
                    self.HTML_CACHE_DIR.exists()
                    and (len(list(self.HTML_CACHE_DIR.glob("*"))) == 0)
                )
            )
        )

        if not generate:
            log.info("Skipping Juvix HTML generation for Juvix files.")
        else:
            log.info(
                "Generating auxiliary HTML for Juvix files. This may take a while... It's only generated once per session."
            )

        with open(self.JUVIXCODE_HASH_FILE, "w") as f:
            f.write(current_sha)

        self.generate_html(generate=generate, move_cache=True)
        self.FIRST_RUN = False
        return

    def generate_html(self, generate: bool = True, move_cache: bool = True) -> None:
        everythingJuvix = self.DOCS_DIR.joinpath("everything.juvix.md")

        if not everythingJuvix.exists():
            log.warning(
                """Consider creating a file named 'everything.juvix.md' or \
                'index.juvix.md' in the docs directory to generate the HTML \
                for all Juvix Markdown file. Otherwise, the compiler will \
                generate the HTML for each Juvix Markdown file on each run."""
            )

        files_to_process = (
            self.juvix_md_files
            if not everythingJuvix.exists()
            else [
                {
                    "file": everythingJuvix,
                    "module_name": self.unqualified_module_name(everythingJuvix),
                    "qualified_module_name": self.qualified_module_name(
                        everythingJuvix
                    ),
                    "url": urljoin(self.site_url, everythingJuvix.name).replace(
                        ".juvix.md", ".html"
                    ),
                }
            ]
        )

        for filepath_info in files_to_process:
            filepath = Path(filepath_info["file"])

            if generate:
                self.generate_html_per_file(filepath)
            if self.site_dir and move_cache:
                self.move_html_cache_to_site_dir(filepath, Path(self.site_dir))
        return

    def generate_html_per_file(
        self, _filepath: Path, remove_cache: bool = False
    ) -> None:
        if remove_cache:
            try:
                shutil.rmtree(self.HTML_CACHE_DIR)
            except Exception as e:
                log.error(f"Error removing folder: {e}")

        self.HTML_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        filepath = _filepath.absolute()

        cmd = (
            [self.JUVIX_BIN, "html"]
            + ["--strip-prefix=docs"]
            + ["--folder-structure"]
            + [f"--output-dir={self.HTML_CACHE_DIR.as_posix()}"]
            + [f"--prefix-url={self.site_url}"]
            + [f"--prefix-assets={self.site_url}"]
            + [filepath.as_posix()]
        )

        log.info(f"Juvix call:\n  {' '.join(cmd)}")

        cd = subprocess.run(cmd, cwd=self.DOCS_DIR, capture_output=True)
        if cd.returncode != 0:
            log.error(cd.stderr.decode("utf-8") + "\n\n" + "Fix the error first.")
            return

        # The following is necessary as this project may
        # contain assets with changes that are not reflected
        # in the generated HTML by Juvix.

        good_assets = self.DOCS_DIR / "assets"
        good_assets.mkdir(parents=True, exist_ok=True)

        assets_in_html = self.HTML_CACHE_DIR / "assets"

        if assets_in_html.exists():
            shutil.rmtree(assets_in_html, ignore_errors=True)

        shutil.copytree(good_assets, assets_in_html, dirs_exist_ok=True)

    @lru_cache(maxsize=128)
    def path_juvix_md_cache(self, _filepath: Path) -> Optional[Path]:
        filepath = _filepath.absolute()
        md_filename = filepath.name.replace(".juvix.md", ".md")
        rel_to_docs = filepath.relative_to(self.DOCS_DIR)
        return self.MARKDOWN_JUVIX_OUTPUT / rel_to_docs.parent / md_filename

    @lru_cache(maxsize=128)
    def read_cache(self, filepath: Path) -> Optional[str]:
        if cache_path := self.path_juvix_md_cache(filepath):
            return cache_path.read_text()
        return None

    def generate_markdown(self, filepath: Path) -> Optional[str]:
        if (
            not self.JUVIX_ENABLED
            or not self.JUVIX_AVAILABLE
            or not filepath.as_posix().endswith(".juvix.md")
        ):
            return None

        if self.new_or_changed_or_no_exist(filepath):
            log.info(f"Running Juvix Markdown on file: {filepath}")
            return self.run_juvix(filepath)

        log.debug(f"Reading cache for file: {filepath}")
        return self.read_cache(filepath)

    def unqualified_module_name(self, filepath: Path) -> Optional[str]:
        fposix: str = filepath.as_posix()
        if not fposix.endswith(".juvix.md"):
            return None
        return os.path.basename(fposix).replace(".juvix.md", "")

    def qualified_module_name(self, filepath: Path) -> Optional[str]:
        absolute_path = filepath.absolute()
        cmd = [self.JUVIX_BIN, "dev", "root", absolute_path.as_posix()]
        pp = subprocess.run(cmd, cwd=self.DOCS_DIR, capture_output=True)
        root = None
        try:
            root = pp.stdout.decode("utf-8").strip()
        except Exception as e:
            log.error(f"Error running Juvix dev root: {e}")
            return None

        if not root:
            return None

        relative_to_root = filepath.relative_to(Path(root))

        qualified_name = (
            relative_to_root.as_posix()
            .replace(".juvix.md", "")
            .replace("./", "")
            .replace("/", ".")
        )

        return qualified_name if qualified_name else None

    def md_filename(self, filepath: Path) -> Optional[str]:
        module_name = self.unqualified_module_name(filepath)
        return module_name + ".md" if module_name else None

    def run_juvix(self, _filepath: Path) -> Optional[str]:
        filepath = _filepath.absolute()
        fposix: str = filepath.as_posix()

        if not fposix.endswith(".juvix.md"):
            log.debug(f"The file: {fposix} is not a Juvix Markdown file.")
            return None

        rel_to_docs: Path = filepath.relative_to(self.DOCS_DIR)

        cmd: List[str] = [
            self.JUVIX_BIN,
            "markdown",
            "--strip-prefix=docs",
            "--folder-structure",
            f"--prefix-url={self.site_url}",
            "--stdout",
            fposix,
            "--no-colors",
        ]

        log.debug(f"Juvix\n {' '.join(cmd)}")

        pp = subprocess.run(cmd, cwd=self.DOCS_DIR, capture_output=True)

        if pp.returncode != 0:
            msg = pp.stderr.decode("utf-8").replace("\n", " ").strip()
            log.debug(f"Error running Juvix on file: {fposix} -\n {msg}")

            format_head = f"!!! failure\n\n    {msg}\n\n"
            return format_head + filepath.read_text().replace("```juvix", "```")

        log.debug(f"Saving Juvix markdown output to: {self.MARKDOWN_JUVIX_OUTPUT}")

        new_folder: Path = self.MARKDOWN_JUVIX_OUTPUT.joinpath(rel_to_docs.parent)
        new_folder.mkdir(parents=True, exist_ok=True)

        md_filename: Optional[str] = self.md_filename(filepath)
        if md_filename is None:
            log.debug(f"Could not determine the markdown file name for: {fposix}")
            return None

        new_md_path: Path = new_folder.joinpath(md_filename)

        with open(new_md_path, "w") as f:
            md_output: str = pp.stdout.decode("utf-8")
            f.write(md_output)

        raw_path: Path = self.JUVIXCODE_CACHE_DIR.joinpath(rel_to_docs)
        raw_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.copy(filepath, raw_path)
        except Exception as e:
            log.error(f"Error copying file: {e}")

        self.update_hash_file(filepath)

        return md_output

    def update_hash_file(self, filepath: Path) -> Optional[Tuple[Path, str]]:
        path_hash = compute_hash_filepath(filepath, hash_dir=self.HASH_DIR)

        try:
            with open(path_hash, "w") as f:
                content_hash = hash_file(filepath)
                f.write(content_hash)
                return (path_hash, content_hash)

        except Exception as e:
            log.error(f"Error updating hash file: {e}")
        return None
