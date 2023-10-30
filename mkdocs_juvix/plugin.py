import os
import sys
from timeit import default_timer as timer
from datetime import datetime, timedelta

from mkdocs import utils as mkdocs_utils
from mkdocs.config import config_options, Config
from mkdocs.plugins import BasePlugin
from mkdocs.structure.files import Files
from mkdocs.structure.nav import Navigation
from mkdocs.structure.pages import Page

from pathlib import *
import logging
import subprocess

log = logging.getLogger('mkdocs')

docsPath = Path("./docs")
juvixMdFolder = Path("./.juvix-mkdocs")


try:
    subprocess.check_output(["juvix", "--numeric-version"])
except Exception:
    log.error("Juvix is not installed and it's required for this plugin.")
    raise


class JuvixPlugin(BasePlugin):

    config_scheme = (
        ('param', config_options.Type(str, default='')),
    )

    def __init__(self):
        self.enabled = True

    def on_page_read_source(self, page: Page, config):
        if page.file.src_path.endswith(".juvix.md"):
            fpath = page.file.abs_src_path
            modname = os.path.basename(fpath).replace(".juvix.md", "")
            mdFile = modname + ".md"
            mdPath = juvixMdFolder.joinpath(mdFile)
            log.info("> Juvix file path: %s", fpath)
            log.info("> Juvix module name: %s", modname)

            check = ["juvix", "typecheck", fpath]
            runCheck = subprocess.run(check,
                                      cwd=docsPath,
                                      capture_output=True)

            if runCheck.returncode != 0:
                log.error("> Error: %s", runCheck.stderr)
                return """<code><div class="juvix-error">%s</div></code>""" % str(runCheck.stderr.decode("utf-8"))

            cmd = [
                "juvix",
                "markdown",
                "--no-path",
                "--stdout",
                fpath
            ]
            cd = subprocess.run(cmd, cwd=docsPath, capture_output=True)
            if cd.returncode != 0:
                log.error("> Juvix-plugin Error: %s",
                          cd.stderr.decode("utf-8"))
                raise Exception(cd.stderr.decode("utf-8"))
            stdout = cd.stdout.decode("utf-8")
            juvixMdFolder.mkdir(parents=True, exist_ok=True)
            with open(mdPath, "w") as f:
                f.write(stdout)
            return stdout
        return ""

    def on_page_markdown(self, markdown, page, config, files: Files):
        if page.file.name.endswith(".juvix"):
            page.file.name = page.file.name.replace(".juvix", "")
            page.file.url = page.file.url.replace(".juvix", "")
            page.file.dest_uri = page.file.dest_uri.replace(".juvix", "")
            page.file.abs_dest_path = page.file.abs_dest_path.replace(
                ".juvix", "")
        return markdown
