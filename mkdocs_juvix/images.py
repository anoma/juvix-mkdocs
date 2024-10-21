import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin
from mkdocs.plugins import BasePlugin, get_plugin_logger
from common.models.loc import FileLoc  # type: ignore
from common.utils import fix_site_url  # type:ignore
from markdown.extensions import Extension  # type: ignore
from markdown.preprocessors import Preprocessor  # type: ignore
from mkdocs.config.defaults import MkDocsConfig  # type: ignore
from mkdocs.structure.files import Files  # type: ignore
from mkdocs.structure.pages import Page
from mkdocs_juvix.env import ENV  # type: ignore

log = get_plugin_logger("\033[94m[images]\033[0m")


IMAGES_PATTERN = re.compile(
    r"""
!\[
(?P<caption>[^\]]*)\]\(
(?P<url>[^\)]+)\)
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
        md.preprocessors.register(self.imgpp, "img-pp", 110)

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
        current_page_url = None

        if "current_page" in config and isinstance(config["current_page"], Page):
            url_relative = self.env.DOCS_PATH / Path(
                config["current_page"].url.replace(".html", ".md")
            )
            current_page_url = url_relative.as_posix()

        if not current_page_url:
            log.error("Current page URL not found. Images will not be processed.")
            return lines

        in_html_comment = False
        in_div = False

        for i, line in enumerate(lines.copy()):
            if "<!--" in line:
                in_html_comment = True
            if "-->" in line:
                in_html_comment = False
            if "<div" in line:
                in_div = True
            if "</div>" in line:
                in_div = False
            if in_html_comment or in_div:
                continue

            matches = IMAGES_PATTERN.finditer(line)

            for match in matches:
                _url = match.group("url")
                url = Path(_url)
                if url.as_posix().startswith("http"):
                    continue

                loc = FileLoc(current_page_url, i + 1, match.start() + 2)

                image_fname = url.name
                img_cache = self.env.CACHE_IMAGES_PATH / image_fname

                if image_fname.endswith(".dot.svg") and self.env.USE_DOT:
                    dot_file = image_fname.replace(".dot.svg", ".dot")
                    dot_location = self.env.IMAGES_PATH / dot_file
                    log.debug(f"{loc}\nGenerating SVG from DOT file: {dot_location}")

                    if not dot_location.exists():
                        log.info(f"{dot_location} not found. Skipping SVG generation.")
                        continue

                    cmd = f"{self.env.DOT_BIN} {self.env.DOT_FLAGS} {dot_location.as_posix()} -o {img_cache.absolute().as_posix()}"

                    log.debug(f"Running command: {cmd}")

                    output = subprocess.run(cmd, shell=True, check=True)

                    if output.returncode != 0:
                        log.error(f"Error running graphviz: {output}")

                    if not img_cache.exists():
                        config["images_issues"] += 1
                        log.error(
                            f"{loc}\n [!] Image not found. Expected location:\n==> {img_cache}"
                        )

                img_expected_location = self.env.IMAGES_PATH / image_fname

                new_url = urljoin(
                    config["site_url"],
                    img_expected_location.relative_to(self.env.DOCS_ABSPATH).as_posix(),
                )

                lines[i] = lines[i].replace(_url, new_url)

                log.debug(
                    f"{loc}\n[!] Image URL: {_url}\nwas replaced by the following URL:\n ==> {new_url}"
                )
        return lines


class ImagePlugin(BasePlugin):
    config: MkDocsConfig
    env: ENV

    def on_config(self, config: MkDocsConfig) -> MkDocsConfig:
        config = fix_site_url(config)
        if self.env is None:
            self.env = ENV(config)

        if not shutil.which(self.env.DOT_BIN):
            log.warning(
                "Graphviz not found. Please install it otherwise dot pictures won't render correctly."
            )
            self.env.USE_DOT = False

        imgext_instance = ImgExtension(config=config, env=self.env)
        config.markdown_extensions.append(imgext_instance)  # type: ignore

        config["images"] = {}  # page: [image]
        config.setdefault("current_page", None)  # current page being processed
        config["images_issues"] = 0
        return config


    def on_page_markdown(self,
        markdown, page: Page, config: MkDocsConfig, files: Files
    ) -> str:
        config["current_page"] = page  # needed for the preprocessor
        return markdown

    def on_post_build(self, config: MkDocsConfig) -> None:
        if config["images_issues"] > 0:
            log.error(
                f"\n[!] {config['images_issues']} image(s) not found. Please check the logs for more details."
            )
        else:
            images_dir = self.env.IMAGES_PATH
            if not images_dir.exists():
                log.error(f"Expected images directory {images_dir} not found.")
                images_dir.mkdir(parents=True, exist_ok=True)
            try:
                path_images = self.env.CACHE_IMAGES_PATH
                if not path_images.exists():
                    log.error(f"Expected images cache directory {path_images} not found.")
                    return
                shutil.copytree(path_images, images_dir, dirs_exist_ok=True)
            except Exception as e:
                log.error(f"Error copying images to site directory: {e}")
