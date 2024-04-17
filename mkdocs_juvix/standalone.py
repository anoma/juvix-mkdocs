import hashlib
import logging
import subprocess
from pathlib import *

import markdown as mk

log = logging.getLogger("mkdocs")

try:
    subprocess.check_output(["juvix", "--numeric-version"])
except Exception:
    log.error("Juvix is not installed and it's required for this plugin.")
    raise

docsPath = Path("./docs")
snippetsPath = docsPath.joinpath("juvix-snippets")
snippetsPath.mkdir(parents=True, exist_ok=True)


def render(
    src: str, language: str, class_name: str, options: dict, md: mk.Markdown, **kwargs
):
    try:
        modname = "M" + hashlib.md5(src.encode("utf-8")).hexdigest()[:5]
        moduleFolder = snippetsPath.joinpath(modname)
        moduleFolder.mkdir(parents=True, exist_ok=True)

        fname = modname + ".juvix"
        fpath = moduleFolder.joinpath(fname)

        log.info("> Juvix-plugin: juvix-snippet: %s", fpath)
        juvixYaml = moduleFolder.joinpath("juvix.yaml")

        with open(juvixYaml, "w") as f:
            f.write("name: juvix-snippets\n")

        with open(fpath, "w") as f:
            f.write("module %s;\n" % modname)
            f.write(src)
            f.write("\n")
            f.write("end;\n")

        check = ["juvix", "typecheck", fname]
        runCheck = subprocess.run(check, cwd=moduleFolder, capture_output=True)

        if runCheck.returncode != 0:
            log.error("> Error: %s", runCheck.stderr)
            return """<code><div class="juvix-error">%s</div></code>""" % str(
                runCheck.stderr.decode("utf-8")
            )

        htmlCmd = [
            "juvix",
            "html",
            "--only-source",
            "--only-code",
            "--no-path",
            "--prefix-url=",
            ("--prefix-id=%s" % modname),
            fname,
        ]
        cd = subprocess.run(htmlCmd, cwd=moduleFolder, capture_output=True)

        if cd.returncode != 0:
            log.error("> Juvix-plugin Error: %s", cd.stderr.decode("utf-8"))
            raise Exception(cd.stderr.decode("utf-8"))

        htmlFolder = moduleFolder.joinpath("html")
        htmlFile = modname + ".html"
        moduleHtmlPath = htmlFolder.joinpath(htmlFile)

        with open(moduleHtmlPath, "r") as f:
            moduleHtml = "".join(f.readlines()[2:])
            mainOutput = "<pre><code><div>%s</div></code></pre>" % moduleHtml
            extraOutput = []
            if len(list(htmlFolder.iterdir())) > 2:
                extraOutput += [
                    "<details class='quote'><summary>Auxiliary definitions</summary>"
                ]
                for f in htmlFolder.iterdir():
                    if f.is_file() and f.name + ".html" != htmlFile:
                        with open(f, "r") as m:
                            fOut = "".join(m.readlines())
                            extraOutput += [
                                """
                                            <details class='quote'><summary>%s </summary>
                                            <pre><code><div>%s</div></code></pre>
                                            </details>"""
                                % (f.name, fOut)
                            ]
                extraOutput += ["</details>"]
            return mainOutput + "\n".join(extraOutput)

    except Exception:
        import traceback

        print(traceback.format_exc())
        raise
