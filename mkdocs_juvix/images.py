import re
import shutil
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple
from urllib.parse import urljoin

import numpy as np
import trio  # type: ignore
from colorama import Fore, Style  # type: ignore
from markdown.extensions import Extension  # type: ignore
from markdown.preprocessors import Preprocessor  # type: ignore
from mkdocs.config.defaults import MkDocsConfig  # type: ignore
from mkdocs.plugins import BasePlugin
from mkdocs.structure.files import Files  # type: ignore
from mkdocs.structure.pages import Page
from ncls import NCLS  # type: ignore

from mkdocs_juvix.common.utils import fix_site_url  # type:ignore
from mkdocs_juvix.env import ENV  # type: ignore
from mkdocs_juvix.logger import log
from mkdocs_juvix.utils import time_spent as time_spent_decorator

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
(?P<rest>\<img.*)src\=(?:\"|\')(?P<url>.+?)(?:\"|\')
""",
    re.VERBOSE,
)


def time_spent(message: Optional[Any] = None, print_result: bool = False):
    return time_spent_decorator(log=log, message=message, print_result=print_result)


@time_spent(message="> processing images")
def process_images(
    env: ENV, md: Optional[str], md_filepath: Optional[Path] = None
) -> Optional[str]:
    def create_ignore_tree(text: str) -> Optional[Any]:
        """Create NCLS tree of regions to ignore (code blocks, comments, divs)"""
        ignore_pattern = re.compile(
            r"(```(?:[\s\S]*?)```|<!--[\s\S]*?-->|<div>[\s\S]*?</div>)", re.DOTALL
        )
        intervals = [(m.start(), m.end(), 1) for m in ignore_pattern.finditer(text)]

        if intervals:
            starts, ends, ids = map(np.array, zip(*intervals))
            return NCLS(starts, ends, ids)
        return None

    def should_process_match(tree: Optional[Any], start: int, end: int) -> bool:
        """Check if match should be processed based on ignore regions"""
        return not tree or not list(tree.find_overlap(start, end))

    def process_image_url(new_url, match: re.Match, html: bool = False) -> str:
        url_str = match.group("url")
        if not url_str:
            return ""

        if html:
            img_rest = match.group("rest") or "<img"
            return f'{img_rest} src="{new_url}"'

        caption = match.group("caption") or ""
        return f"![{caption}]({new_url})"

    def find_replacements(
        text: str, ignore_tree: Optional[Any], html: bool = False
    ) -> List[Tuple[int, int, str]]:
        """Find all image references that need to be replaced"""
        replacements = []

        if html:
            pattern = HTML_IMG_PATTERN
        else:
            pattern = IMAGES_PATTERN

        for match in pattern.finditer(text):
            start, end = match.span()
            if should_process_match(ignore_tree, start, end):
                log.debug(
                    f"Processing image URL: {Fore.GREEN}{match.group('url')}{Style.RESET_ALL}"
                )
                url = Path(match.group("url"))

                # if the url is just a filename, we need to make sure it's
                # relative to the docs images folder
                if (
                    not url.as_posix().startswith("http")
                    and not url.is_absolute()
                    and url.parent == Path(".")
                ):
                    image_url = urljoin(
                        env.SITE_URL,
                        (env.IMAGES_PATH / url.name)
                        .relative_to(env.DOCS_ABSPATH)
                        .as_posix(),
                    )

                    new_text = process_image_url(
                        image_url,
                        match,
                        html=html,
                    )
                    replacements.append((start, end, new_text))
        return replacements

    if md is None:
        if md_filepath is None:
            return None
        markdown_text = Path(md_filepath).read_text()
    else:
        markdown_text = md

    ignore_tree = create_ignore_tree(markdown_text)
    replacements = find_replacements(markdown_text, ignore_tree, html=False)
    for start, end, new_url in reversed(replacements):
        markdown_text = markdown_text[:start] + new_url + markdown_text[end:]

    if "<img" in markdown_text:
        ignore_tree = create_ignore_tree(markdown_text)
        replacements = find_replacements(markdown_text, ignore_tree, html=True)
        for start, end, new_url in reversed(replacements):
            markdown_text = markdown_text[:start] + new_url + markdown_text[end:]

    return markdown_text


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
        config = self.config
        if not isinstance(config.get("current_page"), Page):
            log.error("Current page URL not found. Images will not be processed.")
            return lines

        md_filepath = self.env.DOCS_PATH / Path(
            config["current_page"].url.replace(".html", ".md")
        )
        result = process_images(
            self.env,
            "\n".join(lines),
            md_filepath,
        )
        if result is None:
            return "\n".join(lines)
        return result.split("\n")


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
                cond = self.env.is_file_new_or_changed_for_cache(dot_file)
                svg_file = dot_file.with_suffix(".dot.svg")
                if cond:
                    await self._generate_dot_svg(dot_file)
                    if svg_file.exists():
                        log.info(
                            f"Requested SVG for {Fore.GREEN}{dot_file.relative_to(self.env.DOCS_PATH)}{Style.RESET_ALL} "
                            f"agenerated: {Fore.GREEN}{svg_file.relative_to(self.env.DOCS_PATH)}{Style.RESET_ALL}"
                        )
                        self.env.update_hash_file(dot_file)
                return svg_file
            except Exception as e:
                log.error(
                    f"Error generating SVG for {Fore.GREEN}{dot_file}{Style.RESET_ALL}: {e}"
                )
                return None

        async def run_in_parallel(dot_files: List[Path]):
            async with trio.open_nursery() as nursery:
                for dot_file in dot_files:
                    nursery.start_soon(process_dot_file, dot_file)

        if dot_files and self.env.FIRST_RUN:
            time_start = time.time()
            trio.run(run_in_parallel, dot_files)
            time_end = time.time()
            log.info(
                f"SVG generation took {Fore.GREEN}{time_end - time_start:.5f}{Style.RESET_ALL} seconds"
            )
            self.env.FIRST_RUN = False

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
