import json
import logging
from os import getenv, environ
import os
import re
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
from dotenv import load_dotenv

from mkdocs_juvix.utils import (
    compute_hash_filepath,
    compute_sha_over_folder,
    fix_site_url,
    hash_file,
)

load_dotenv()
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


def generate_code_block_footer_css_file(
        css_file: Path, 
        compiler_version: Optional[str] = None
) -> Optional[Path]:
    css_file.parent.mkdir(parents=True, exist_ok=True)
    css_file.write_text(
        f"""
code.juvix::after {{
    font-family: var(--md-code-font-family);
    content: "Juvix v{compiler_version}";
    font-size: 11px;
    color: var(--md-juvix-codeblock-footer);
    float: right;
}}
"""
    )
    return css_file


class JuvixPlugin(BasePlugin):
    mkconfig: MkDocsConfig
    juvix_md_files: List[Dict[str, Any]]

    # Config variables created from environment variables or from the config file
    SITE_DIR: Optional[str]
    SITE_URL: str
    REMOVE_CACHE : bool = bool(getenv("REMOVE_CACHE", False)) # Whether the cache should be removed
    
    JUVIX_FOOTER_CSS_FILENAME : str = getenv("JUVIX_FOOTER_CSS_FILENAME", "juvix_codeblock_footer.css")
    JUVIX_ENABLED : bool = bool(getenv("JUVIX_ENABLED", True)) # Whether the user wants to use Juvix
    JUVIX_AVAILABLE : bool = bool(getenv("JUVIX_AVAILABLE", True)) # Whether Juvix is available on the system   
    JUVIX_VERSION : Optional[str] = getenv("JUVIX_VERSION", None) # The version of Juvix that is being used
    JUVIX_BIN_NAME : str = getenv("JUVIX_BIN", "juvix") # The name of the Juvix binary
    JUVIX_BIN_PATH : str = getenv("JUVIX_PATH", "") # The path to the Juvix binary
    JUVIX_BIN : str = JUVIX_BIN_PATH + "/" + JUVIX_BIN_NAME if JUVIX_BIN_PATH != "" else JUVIX_BIN_NAME # The full path to the Juvix binary
    JUVIXCODE_CACHE_DIRNAME : str = getenv("JUVIXCODE_CACHE_DIRNAME", ".juvix_md") # The name of the directory where the Juvix Markdown files are cached
    JUVIXCODE_PROJECT_HASH_FILENAME : str = getenv("JUVIXCODE_PROJECT_HASH_FILENAME", ".hash_juvix_md") # The name of the file where the Juvix Markdown files are cached
    
    ISABELLE_PROJECT_HASH_FILENAME : str = getenv("ISABELLE_PROJECT_HASH_FILENAME", ".hash_isabelle_md") # The name of the file where the Isabelle Markdown files are cached
    ISABELLE_ENABLED : bool = bool(getenv("ISABELLE_ENABLED", True)) # Whether the user wants to use Isabelle
    ISABELLECODE_CACHE_DIRNAME : str = getenv("ISABELLECODE_CACHE_DIRNAME", ".isabelle_md") # The name of the directory where the Isabelle Markdown files are cached
    
    HASHES_DIRNAME : str = getenv("HASHES_DIRNAME", ".hashes") # The name of the directory where the hashes are stored
    HTML_CACHE_DIRNAME : str = getenv("HTML_CACHE_DIRNAME", ".html") # The name of the directory where the HTML files are cached
    FIRST_RUN : bool = bool(getenv("FIRST_RUN", True)) # Whether this is the first time the plugin is run
    MARKDOWN_JUVIX_OUTPUT_FILENAME : str = getenv("MARKDOWN_JUVIX_OUTPUT_FILENAME", ".juvix_md") # The name of the file where the Juvix Markdown files are stored
    CACHE_JUVIX_VERSION_FILENAME : str = getenv("CACHE_JUVIX_VERSION_FILENAME", ".juvix_version") # The name of the file where the Juvix version is stored
    CACHE_DIRNAME : str = getenv("CACHE_DIRNAME", ".hooks") # The name of the directory where the hooks are stored
    DOCS_DIRNAME : str = getenv("DOCS_DIRNAME", "docs") # The name of the directory where the documentation is stored
    
    CACHE_PATH: Path = Path(CACHE_DIRNAME) # The path to the cache directory
    JUVIXCODE_CACHE_PATH: Path = CACHE_PATH / JUVIXCODE_CACHE_DIRNAME # The path to the Juvix Markdown cache directory
    ROOT_PATH: Path = CACHE_PATH.parent # The path to the root directory
    DOCS_PATH: Path = ROOT_PATH / DOCS_DIRNAME # The path to the documentation directory
    MARKDOWN_JUVIX_OUTPUT_PATH: Path = CACHE_PATH / HTML_CACHE_DIRNAME # The path to the Juvix Markdown output directory
    HASHES_PATH: Path = CACHE_PATH / HASHES_DIRNAME # The path to the hashes directory
    
    JUVIX_FOOTER_CSS_FILEPATH: Path = ( # The path to the Juvix footer CSS file
        DOCS_PATH / "assets" / "css" / JUVIX_FOOTER_CSS_FILENAME
    )
    CACHE_JUVIX_VERSION_FILEPATH: Path = CACHE_PATH / CACHE_JUVIX_VERSION_FILENAME # The path to the Juvix version file

    def on_config(self, config: MkDocsConfig, **kwargs) -> MkDocsConfig:
        config_file = config.config_file_path

        self.ROOT_PATH = Path(config_file).parent.absolute()
        self.CACHE_PATH = self.ROOT_PATH / self.CACHE_DIRNAME
        self.DOCS_PATH = self.ROOT_PATH / self.DOCS_DIRNAME
        
        # check DOCS_PATH
        if not self.DOCS_PATH.exists():
            log.error(f"""The documentation path {self.DOCS_PATH} does not exist.
                      Please create it. or change the DOCS_DIRNAME environment variable.""")
            exit(1)

        self.force = self.REMOVE_CACHE
        self.FIRST_RUN = True

        directories : List[Path] = [
            self.MARKDOWN_JUVIX_OUTPUT_PATH,
            self.JUVIXCODE_CACHE_PATH,
            self.CACHE_PATH,
            self.HASHES_PATH,
            self.JUVIX_FOOTER_CSS_FILEPATH.parent
        ]

        for directory in directories:
            if directory.exists() and self.force:
                shutil.rmtree(directory, ignore_errors=True)
            directory.mkdir(parents=True, exist_ok=True)

        self.JUVIXCODE_HASH_FILE = self.HASHES_PATH / self.JUVIXCODE_PROJECT_HASH_FILENAME
        self.JUVIX_AVAILABLE = shutil.which(self.JUVIX_BIN) is not None
        self.JUVIX_ENABLED = self.JUVIX_AVAILABLE

        if self.JUVIX_ENABLED:
            try:
                subprocess.run([self.JUVIX_BIN, "--version"], capture_output=True)
            except Exception as e:
                log.warning(
                    f"The Juvix binary is not available. Please install Juvix and make sure it's available in the PATH. Error: {e}"
                )

            numeric_version_cmd = [self.JUVIX_BIN, "--numeric-version"]
            result = subprocess.run(numeric_version_cmd, capture_output=True)
            if result.returncode == 0:
                self.JUVIX_VERSION = result.stdout.decode("utf-8")
                log.info(
                    f"Using Juvix v{self.JUVIX_VERSION} to render Juvix Markdown files."
                )

        config = fix_site_url(config)
        self.mkconfig = config

        # Add CSS file to extra_css
        config["extra_css"].append(
            self.JUVIX_FOOTER_CSS_FILEPATH.relative_to(self.DOCS_PATH).as_posix()
        )

        self.juvix_md_files: List[Dict[str, Any]] = []

        self.SITE_DIR = config.get("site_dir", getenv("SITE_DIR", None))
        self.SITE_URL = config.get("site_url", getenv("SITE_URL", ""))

        if not self.JUVIX_AVAILABLE:
            log.info(
                "Juvix is not available on the system. check the JUVIX_BIN environment variable."
            )

        return config
    
        """
        Mkdocs Pipeline
        ├── on_startup(command, dirty)
        └── on_config(config)
            ├── on_pre_build(config)
            ├── on_files(files, config)
            │   └── on_nav(nav, config, files)
            │       ├── Populate the page:
            │       │   ├── on_pre_page(page, config, files)
            │       │   ├── on_page_read_source(page, config)
            │       │   ├── on_page_markdown(markdown, page, config, files)
            │       │   ├── render()
            │       │   └── on_page_content(html, page, config, files)
            │       ├── on_env(env, config, files)
            │       └── Build the pages:
            │           ├── get_context()
            │           ├── on_page_context(context, page, config, nav)
            │           ├── get_template() & render()
            │           ├── on_post_page(output, page, config)
            │           └── write_file()
            ├── on_post_build(config)
            ├── on_serve(server, config)
            └── on_shutdown()
        """

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
        if (gitignore_file := self.ROOT_PATH / ".gitignore").exists():
            with open(gitignore_file) as file:
                gitignore = pathspec.PathSpec.from_lines(
                    pathspec.patterns.GitWildMatchPattern,  # type: ignore
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

    def on_page_content(
        self, html: str, page: Page, config: MkDocsConfig, files: Files
    ) -> Optional[str]:
        log.error(
            "Found a .juvix.html link : "
            + str(len(re.findall('".juvix.html"', html)))
        )
        html = html.replace('".juvix.html"', '".html"')
        return html

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

        log.error("INFO" + "-" * 80)
        log.error("abs_dest_path: " + str(page.file.abs_dest_path))
        # log.error("abs_src_path: " + str(page.file.abs_src_path))
        # log.error("url: " + str(page.file.url))
        # log.error("dest_uri: " + str(page.file.dest_uri))
        # log.error("name: " + str(page.file.name))
        # log.error("-" * 100)

        return markdown

    def move_html_cache_to_site_dir(self, filepath: Path, site_dir: Path) -> None:
        rel_to_docs = filepath.relative_to(self.DOCS_PATH)
        if filepath.is_dir():
            dest_folder = site_dir / rel_to_docs
        else:
            dest_folder = site_dir / rel_to_docs.parent

        dest_folder.mkdir(parents=True, exist_ok=True)

        # Patch: remove all the .html files in the destination folder of the
        # Juvix Markdown file to not lose the generated HTML files in the site
        # directory.

        for _file in self.JUVIXCODE_CACHE_PATH.rglob("*.juvix.md"):
            file = _file.absolute()

            html_file_path = (
                self.HTML_CACHE_DIR
                / file.relative_to(self.JUVIXCODE_CACHE_PATH).parent
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
                not self.CACHE_JUVIX_VERSION_FILEPATH.exists()
                or not self.JUVIX_FOOTER_CSS_FILEPATH.exists()
            )
            read_version = (
                self.CACHE_JUVIX_VERSION_FILEPATH.read_text().strip()
                if not need_to_write
                else None
            )
            if read_version != version:
                self.CACHE_JUVIX_VERSION_FILEPATH.parent.mkdir(parents=True, exist_ok=True)
                self.CACHE_JUVIX_VERSION_FILEPATH.write_text(version)
                need_to_write = True
            if need_to_write:
                generate_code_block_footer_css_file(self.JUVIX_FOOTER_CSS_FILEPATH, version)

        for _file in self.DOCS_PATH.rglob("*.juvix.md"):
            file: Path = _file.absolute()
            relative_to: Path = file.relative_to(self.DOCS_PATH)
            url = urljoin(
                self.SITE_URL, relative_to.as_posix().replace(".juvix.md", ".html")
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
        juvix_modules = self.CACHE_PATH.joinpath("juvix_modules.json")

        if juvix_modules.exists():
            juvix_modules.unlink()

        with open(juvix_modules, "w") as f:
            json.dump(self.juvix_md_files, f, indent=4)

        sha_filecontent = (
            self.JUVIXCODE_HASH_FILE.read_text()
            if self.JUVIXCODE_HASH_FILE.exists()
            else None
        )

        current_sha: str = compute_sha_over_folder(self.JUVIXCODE_CACHE_PATH)
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
        everythingJuvix = self.DOCS_PATH.joinpath("everything.juvix.md")

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
                    "url": urljoin(self.SITE_URL, everythingJuvix.name).replace(
                        ".juvix.md", ".html"
                    ),
                }
            ]
        )

        for filepath_info in files_to_process:
            filepath = Path(filepath_info["file"])

            if generate:
                self.generate_html_per_file(filepath)
            if self.SITE_DIR and move_cache:
                self.move_html_cache_to_site_dir(filepath, Path(self.SITE_DIR))
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
            + [f"--prefix-url={self.SITE_URL}"]
            + [f"--prefix-assets={self.SITE_URL}"]
            + [filepath.as_posix()]
        )

        log.info(f"Juvix call:\n  {' '.join(cmd)}")

        cd = subprocess.run(cmd, cwd=self.DOCS_PATH, capture_output=True)
        if cd.returncode != 0:
            log.error(cd.stderr.decode("utf-8") + "\n\n" + "Fix the error first.")
            return

        # The following is necessary as this project may
        # contain assets with changes that are not reflected
        # in the generated HTML by Juvix.

        good_assets = self.DOCS_PATH / "assets"
        good_assets.mkdir(parents=True, exist_ok=True)

        assets_in_html = self.HTML_CACHE_DIR / "assets"

        if assets_in_html.exists():
            shutil.rmtree(assets_in_html, ignore_errors=True)

        shutil.copytree(good_assets, assets_in_html, dirs_exist_ok=True)

    @lru_cache(maxsize=128)
    def path_juvix_md_cache(self, _filepath: Path) -> Optional[Path]:
        filepath = _filepath.absolute()
        md_filename = filepath.name.replace(".juvix.md", ".md")
        rel_to_docs = filepath.relative_to(self.DOCS_PATH)
        return self.MARKDOWN_JUVIX_OUTPUT_PATH / rel_to_docs.parent / md_filename

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
        pp = subprocess.run(cmd, cwd=self.DOCS_PATH, capture_output=True)
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

        rel_to_docs: Path = filepath.relative_to(self.DOCS_PATH)

        cmd: List[str] = [
            self.JUVIX_BIN,
            "markdown",
            "--strip-prefix=docs",
            "--folder-structure",
            f"--prefix-url={self.SITE_URL}",
            "--stdout",
            fposix,
            "--no-colors",
        ]

        log.debug(f"Juvix\n {' '.join(cmd)}")

        pp = subprocess.run(cmd, cwd=self.DOCS_PATH, capture_output=True)

        if pp.returncode != 0:
            msg = pp.stderr.decode("utf-8").replace("\n", " ").strip()
            log.debug(f"Error running Juvix on file: {fposix} -\n {msg}")

            format_head = f"!!! failure\n\n    {msg}\n\n"
            return format_head + filepath.read_text().replace("```juvix", "```")

        log.debug(f"Saving Juvix markdown output to: {self.MARKDOWN_JUVIX_OUTPUT_PATH}")

        new_folder: Path = self.MARKDOWN_JUVIX_OUTPUT_PATH.joinpath(rel_to_docs.parent)
        new_folder.mkdir(parents=True, exist_ok=True)

        md_filename: Optional[str] = self.md_filename(filepath)
        if md_filename is None:
            log.debug(f"Could not determine the markdown file name for: {fposix}")
            return None

        new_md_path: Path = new_folder.joinpath(md_filename)

        with open(new_md_path, "w") as f:
            md_output: str = pp.stdout.decode("utf-8")
            f.write(md_output)

        raw_path: Path = self.JUVIXCODE_CACHE_PATH.joinpath(rel_to_docs)
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
