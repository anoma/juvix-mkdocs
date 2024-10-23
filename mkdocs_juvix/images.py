import re
import shutil
import time
from pathlib import Path
from typing import List, Optional

import numpy as np
import trio  # type: ignore
from colorama import Fore, Style  # type: ignore
from markdown.extensions import Extension  # type: ignore
from markdown.preprocessors import Preprocessor  # type: ignore
from mkdocs.config.defaults import MkDocsConfig  # type: ignore
from mkdocs.plugins import BasePlugin, get_plugin_logger
from mkdocs.structure.files import Files  # type: ignore
from mkdocs.structure.pages import Page
from ncls import NCLS

from mkdocs_juvix.common.utils import fix_site_url  # type:ignore
from mkdocs_juvix.env import ENV  # type: ignore

log = get_plugin_logger(f"{Fore.BLUE}[juvix_mkdocs-images]{Style.RESET_ALL}")

IMAGES_PATTERN = re.compile(
    r"""
!\[
(?P<caption>[^\]]*)\]\(
(?P<url>[^\)]+)\)
""",
    re.VERBOSE,
)

HTML_IMG_PATTERN = re.compile(
    r"""
<img\s+src=("|')(?P<url>[^\)]+)("|')
""",
    re.VERBOSE,
)


class ImgExtension(Extension):
    config: MkDocsConfig
    env: ENV

    def __init__(self, config: MkDocsConfig, env: Optional[ENV] = None):
        self.config = config
        if env is None:
            self.env = ENV(config)
        else:
            self.env = env

    def __repr__(self):
        return "ImgExtension"

    def extendMarkdown(self, md):  # noqa: N802
        self.md = md
        md.registerExtension(self)
        self.imgpp = ImgPreprocessor(self.config, self.env)
        md.preprocessors.register(self.imgpp, "img-pp", 90)


class ImgPreprocessor(Preprocessor):
    config: MkDocsConfig
    env: ENV

    def __init__(self, config, env: Optional[ENV] = None):
        self.config = config
        if env is None:
            self.env = ENV(config)
        else:
            self.env = env

    def run(self, lines):
        full_text = "".join(lines)

        config = self.config
        current_page_url = None

        if "current_page" in config and isinstance(config["current_page"], Page):
            url_relative = self.env.DOCS_PATH / Path(
                config["current_page"].url.replace(".html", ".md")
            )
            current_page_url = url_relative.as_posix()

        if not current_page_url:
            log.error("Current page URL not found. Images will not be processed.")
            return lines

        ignore_blocks = re.compile(
            r"(```(?:[\s\S]*?)```|<!--[\s\S]*?-->|<div>[\s\S]*?</div>)", re.DOTALL
        )
        intervals = []
        try:
            for match in ignore_blocks.finditer(full_text):
                intervals.append((match.start(), match.end(), 1))
        except Exception as e:
            log.error(f"Error occurred while processing ignore patterns: {e}")
            return lines

        ignore_tree = None
        if intervals:
            starts, ends, ids = map(np.array, zip(*intervals))
            ignore_tree = NCLS(starts, ends, ids)

        def img_markdown_link(match: re.Match, img_expected_location: Path) -> str:
            if match.group("caption"):
                return (
                    f"![{match.group('caption')}]({img_expected_location.as_posix()})"
                )
            else:
                return img_expected_location.as_posix()

        full_text = "".join(lines)

        time_start = time.time()

        def process_matches(pattern, process_func):
            matches = list(pattern.finditer(full_text))
            if matches:
                replacements = []
                for match in matches:
                    start, end = match.start(), match.end()
                    if ignore_tree and not list(ignore_tree.find_overlap(start, end)):
                        url = Path(match.group("url"))
                        if url.as_posix().startswith("http"):
                            continue
                        image_fname = url.name
                        img_expected_location = self.env.IMAGES_PATH / image_fname
                        new_url = process_func(match, img_expected_location)
                        replacements.append((start, end, new_url))
                return replacements
            return []

        replacements = process_matches(
            IMAGES_PATTERN,
            lambda match, img_expected_location: img_markdown_link(
                match, img_expected_location
            ),
        )

        for start, end, new_url in reversed(replacements):
            full_text = full_text[:start] + new_url + full_text[end:]

        replacements = process_matches(
            HTML_IMG_PATTERN,
            lambda _,
            img_expected_location: f'<img src="{img_expected_location.absolute().as_posix()}" />',
        )
        for start, end, new_url in reversed(replacements):
            full_text = full_text[:start] + new_url + full_text[end:]

        time_end = time.time()
        log.debug(
            f"Path image resolution took {time_end - time_start:.5f} seconds for {current_page_url}"
        )

        return full_text.split("\n")


class ImagesPlugin(BasePlugin):
    env: ENV

    def on_config(self, config: MkDocsConfig) -> MkDocsConfig:
        config = fix_site_url(config)
        self.env = ENV(config)

        if not shutil.which(self.env.DOT_BIN):
            log.warning(
                "Graphviz not found. Please install it otherwise dot pictures won't render correctly."
            )
            self.env.USE_DOT = False

        dot_files = list(self.env.IMAGES_PATH.glob("*.dot"))

        async def process_dot_file(dot_file: Path):
            try:
                cond = self.env.new_or_changed_or_not_exists(dot_file)
                svg_file = dot_file.with_suffix(".dot.svg")
                if cond:
                    await self._generate_dot_svg(dot_file)
                    if svg_file.exists():
                        log.info(f"Generated SVG: {svg_file}")
                        self.env.update_hash_file(dot_file)
                return svg_file
            except Exception as e:
                log.error(f"Error generating SVG for {dot_file}: {e}")
                return None

        async def run_in_parallel(dot_files: List[Path]):
            async with trio.open_nursery() as nursery:
                for dot_file in dot_files:
                    nursery.start_soon(process_dot_file, dot_file)

        if dot_files:
            time_start = time.time()
            trio.run(run_in_parallel, dot_files)
            time_end = time.time()
            log.info(
                f"SVG generation took {Fore.GREEN}{time_end - time_start:.5f}{Style.RESET_ALL} seconds"
            )

        imgext_instance = ImgExtension(config=config, env=self.env)
        config.markdown_extensions.append(imgext_instance)  # type: ignore

        config["images"] = {}  # page: [image]
        config.setdefault("current_page", None)  # current page being processed
        return config

    async def _generate_dot_svg(self, dot_file: Path) -> Optional[Path]:
        svg_file = dot_file.with_suffix(".dot.svg")

        if not svg_file.exists():
            self.env.IMAGES_PATH.mkdir(parents=True, exist_ok=True)

        dot_cmd = [
            self.env.DOT_BIN,
            self.env.DOT_FLAGS,
            dot_file.absolute().as_posix(),
            "-o",
            svg_file.absolute().as_posix(),
        ]

        try:
            output = await trio.run_process(dot_cmd)
            if output.returncode != 0:
                log.error(f"Error running graphviz: {output}")
                return None
            return dot_file
        except Exception as e:
            log.error(f"Error running graphviz: {e}")
            return None

    def on_page_markdown(
        self, markdown, page: Page, config: MkDocsConfig, files: Files
    ) -> str:
        config["current_page"] = page  # needed for the preprocessor
        return markdown
