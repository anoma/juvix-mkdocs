"""
Support for wiki-style links in MkDocs in tandem of pydownx_snippets.
"""

import json
import os
import re
from os import getenv
from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin

import mkdocs.plugins
from dotenv import load_dotenv
from markdown.extensions import Extension
from mkdocs.config.defaults import MkDocsConfig
from mkdocs.plugins import BasePlugin, get_plugin_logger
from mkdocs.structure.files import Files
from mkdocs.structure.pages import Page
from mkdocs.utils import meta

from mkdocs_juvix.common.models.entry import ResultEntry
from mkdocs_juvix.common.preprocesors.links import WLPreprocessor
from mkdocs_juvix.common.utils import (
    create_mermaid_diagram,
    fix_site_url,
    get_page_title,
)
from mkdocs_juvix.env import ENV
from mkdocs_juvix.snippets import (
    DEFAULT_URL_SIZE,
    DEFAULT_URL_TIMEOUT,
    SnippetPreprocessor,
)

load_dotenv()


log = get_plugin_logger("Wikilinks")

files_relation: List[ResultEntry] = []


class WLExtension(Extension):
    config: MkDocsConfig
    env: ENV

    def __init__(self, config: MkDocsConfig):
        self.config = config
        self.env = ENV(config)

        if "pymdownx.snippets" in self.config.mdx_configs:
            bpath = self.config.mdx_configs["pymdownx.snippets"].get(
                "base_path", [".", "includes"]
            )

            excluded_dirs = [".", "__", "site", "env", "venv"]

            for root, dirs, _ in os.walk("."):
                dirs[:] = [
                    d
                    for d in dirs
                    if not any(d.startswith(exclude) for exclude in excluded_dirs)
                ]

                bpath.extend(os.path.relpath(os.path.join(root, d), ".") for d in dirs)

            self.config.mdx_configs["pymdownx.snippets"]["base_path"] = bpath

    def __repr__(self):
        return "WLExtension"

    def extendMarkdown(self, md):  # noqa: N802
        self.md = md
        md.registerExtension(self)

        # Snippet extension preprocessor
        sc = self.config.mdx_configs.get("pymdownx.snippets", {})
        sc.setdefault("dedent_subsections", True)
        sc.setdefault("url_request_headers", {})
        sc.setdefault("url_timeout", DEFAULT_URL_TIMEOUT)
        sc.setdefault("url_max_size", DEFAULT_URL_SIZE)
        sc.setdefault("url_download", True)
        sc.setdefault("auto_append", [])
        sc.setdefault("check_paths", True)
        sc.setdefault("encoding", "utf-8")
        sc.setdefault("restrict_base_path", True)
        sc.setdefault("base_path", [".", "includes"])

        sp = SnippetPreprocessor(sc, md, self.env)

        self.wlpp = WLPreprocessor(self.config, sp)
        md.preprocessors.register(self.wlpp, "wl-pp", 100)


class WikilinksPlugin(BasePlugin):
    ROOT_PATH: Path
    DOCS_PATH: Path
    CACHE_DIR: Path
    SITE_URL: str
    LINKS_JSON: Path
    GRAPH_JSON: Path
    NODES_JSON: Path
    PAGE_LINK_DIAGS: Path
    REPORT_BROKEN_WIKILINKS: bool = bool(getenv("REPORT_BROKEN_WIKILINKS", True))
    TOKEN_LIST_WIKILINKS: str = "<!-- list_wikilinks -->"
    TOKEN_MERMAID_WIKILINKS: str = "<!-- mermaid_wikilinks -->"

    DOCS_DIRNAME: str = getenv("DOCS_DIRNAME", "docs")
    CACHE_DIRNAME: str = getenv("CACHE_DIRNAME", ".hooks")
    LINKS_JSONNAME: str = getenv("LINKS_JSONNAME", "aliases.json")
    GRAPH_JSONNAME: str = getenv("GRAPH_JSONNAME", "graph.json")
    NODES_JSONNAME: str = getenv("NODES_JSONNAME", "nodes.json")
    PAGE_LINK_DIAGSNAME: str = getenv("PAGE_LINK_DIAGSNAME", "page_link_diags")

    def on_config(self, config: MkDocsConfig, **kwargs) -> MkDocsConfig:
        config = fix_site_url(config)
        self.SITE_URL = config.get("site_url", getenv("SITE_URL", ""))
        config_file = config.config_file_path
        self.ROOT_PATH = Path(config_file).parent.absolute()
        self.DOCS_PATH = self.ROOT_PATH / self.DOCS_DIRNAME
        self.CACHE_DIR = self.ROOT_PATH / self.CACHE_DIRNAME
        self.LINKS_JSON = self.CACHE_DIR / self.LINKS_JSONNAME
        self.GRAPH_JSON = self.CACHE_DIR / self.GRAPH_JSONNAME
        self.NODES_JSON = self.CACHE_DIR / self.NODES_JSONNAME
        self.PAGE_LINK_DIAGS = self.CACHE_DIR / self.PAGE_LINK_DIAGSNAME

        # create cache dir
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.PAGE_LINK_DIAGS.mkdir(parents=True, exist_ok=True)

        if "pymdownx.snippets" in config["markdown_extensions"]:
            config["markdown_extensions"].remove("pymdownx.snippets")

        wl_extension = WLExtension(config)
        config.markdown_extensions.append(wl_extension)  # type: ignore
        return config

    def on_pre_build(self, config: MkDocsConfig) -> None:
        config["aliases_for"] = {}
        config["url_for"] = {}
        config["wikilinks_issues"] = 0
        config["nodes"] = {}
        node_index = 0

        for _url, page in self._extract_aliases_from_nav(config["nav"]):
            url = urljoin(config["site_url"], _url)

            config["aliases_for"][url] = [page]
            config["url_for"].setdefault(page, [])
            config["url_for"][page].append(url)

            # Create a new entry if the URL is not already present in config["nodes"]
            if url not in config["nodes"]:
                config["nodes"][url] = {
                    "index": node_index,
                    "page": {"names": [], "path": _url.replace("./", "")},
                }
            # Append the page to the "names" list
            config["nodes"][url]["page"]["names"].append(page)
            node_index += 1

        if self.NODES_JSON.exists():
            self.NODES_JSON.unlink()

        with open(self.NODES_JSON, "w") as f:
            json.dump(
                {
                    "nodes": config.get("nodes", {}),
                },
                f,
                indent=2,
            )
        config["current_page"] = None  # current page being processed
        return

    def on_files(self, files: Files, config: MkDocsConfig) -> None:
        """When MkDocs loads its files, extract aliases from any Markdown files
        that were found.
        """
        for file in filter(lambda f: f.is_documentation_page(), files):
            pathFile: str | None = file.abs_src_path
            if pathFile is not None:
                with open(pathFile, encoding="utf-8-sig", errors="strict") as handle:
                    source, meta_data = meta.get_data(handle.read())
                    alias_names: Optional[List[str]] = self._get_alias_names(meta_data)

                    if alias_names is None or len(alias_names) < 1:
                        _title: Optional[str] = get_page_title(source, meta_data)

                        if _title:
                            _title = _title.strip()
                            _title = re.sub(r'^[\'"`]|["\'`]$', "", _title)

                            if _title not in config["url_for"]:
                                url = urljoin(config["site_url"], file.url)
                                config["url_for"][_title] = [url]
                                config["aliases_for"][url] = [_title]

        if self.LINKS_JSON.exists():
            self.LINKS_JSON.unlink()

        with open(self.LINKS_JSON, "w") as f:
            json.dump(
                {
                    "aliases_for": config.get("aliases_for", {}),
                    "url_for": {
                        k: [
                            p.replace(".md", ".html") if p.endswith(".md") else p
                            for p in v
                        ]
                        for k, v in config["url_for"].items()
                    },
                },
                f,
                indent=2,
            )

    @mkdocs.plugins.event_priority(-200)
    def on_page_markdown(
        self, markdown, page: Page, config: MkDocsConfig, files: Files
    ) -> str:
        config["current_page"] = page  # needed for the preprocessor
        config["links_number"] = []
        markdown += "\n" + self.TOKEN_LIST_WIKILINKS + "\n"
        markdown += "\n" + self.TOKEN_MERMAID_WIKILINKS + "\n"
        return markdown

    def on_page_content(
        self, html, page: Page, config: MkDocsConfig, files: Files
    ) -> str:
        if "current_page" not in config or "nodes" not in config:
            return html
        current_page = config["current_page"]
        url = current_page.canonical_url.replace(".html", ".md")
        if url not in config["nodes"]:
            return html

        if url not in config["nodes"] or "index" not in config["nodes"][url]:
            return html
        links_number = config.get("links_number", [])
        if len(links_number) > 0:
            actualindex = config["nodes"][url]["index"]
            result_entry = ResultEntry(
                file=current_page.url,
                index=actualindex,
                matches=links_number,
                url=current_page.canonical_url,
                name=current_page.title,
            )
            files_relation.append(result_entry)

            if page.meta.get("list_wikilinks", True):
                # Creat a bullet list of links
                wrapped_links = "<details class='quote'><summary>Wiki links on this page</summary><ul>"
                unique_links = {
                    link["url"]: (link["path"], link["name"]) for link in links_number
                }
                for url, (path, name) in unique_links.items():
                    wrapped_links += f"<li><a href='{url}' alt='{path}'>{name}</a></li>"
                wrapped_links += "</ul></details>"

                html = html.replace(self.TOKEN_LIST_WIKILINKS, wrapped_links)

            if page.meta.get("mermaid_wikilinks", False):
                mermaid_structure = create_mermaid_diagram([result_entry])
                file_path = (
                    result_entry.file.replace("\\", "_")
                    .replace("/", "_")
                    .replace(".html", ".mmd")
                )
                file_path = (self.PAGE_LINK_DIAGS / file_path).as_posix()
                with open(file_path, "w") as f:
                    f.write(mermaid_structure)

                wrapped_mermaid = f"""
                    <details class="quote">
                    <summary>Link graph</summary>
                    <div style="text-align: center;">
                    <pre class="mermaid" ><code>{mermaid_structure}</code></pre>
                    </div>
                    </details>
                """
                html = html.replace(self.TOKEN_MERMAID_WIKILINKS, wrapped_mermaid)
        return html

    def on_post_build(self, config: MkDocsConfig):
        if self.GRAPH_JSON.exists():
            self.GRAPH_JSON.unlink()

        serialized_files_relation = [entry.to_dict() for entry in files_relation]
        with open(self.GRAPH_JSON, "w") as graph_json_file:
            json.dump(
                {"graph": serialized_files_relation},
                graph_json_file,
                indent=2,
            )

        mermaid_structure = create_mermaid_diagram(files_relation)
        file_path = (self.PAGE_LINK_DIAGS / "graph.mmd").as_posix()
        with open(file_path, "w") as f:
            f.write(mermaid_structure)

    def _extract_aliases_from_nav(self, item, parent_key=None):
        result = []
        if isinstance(item, str):
            if parent_key:
                result.append((item, parent_key))
        elif isinstance(item, list):
            for i in item:
                result.extend(self._extract_aliases_from_nav(i, parent_key))
        elif isinstance(item, dict):
            for k, v in item.items():
                if isinstance(v, str):
                    result.append((v, k))
                else:
                    result.extend(self._extract_aliases_from_nav(v, k))
        return result

    def _get_alias_names(self, meta_data: dict):
        """Returns the list of configured alias names."""
        if len(meta_data) <= 0 or "alias" not in meta_data:
            return None
        aliases = meta_data["alias"]
        if isinstance(aliases, list):
            return list(filter(lambda value: isinstance(value, str), aliases))
        if isinstance(aliases, dict) and "name" in aliases:
            return [aliases["name"]]
        if isinstance(aliases, str):
            return [aliases]
        return None
