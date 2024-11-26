import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import click
import questionary
import toml  # type: ignore
from dotenv import load_dotenv
from semver import Version

from mkdocs_juvix.juvix_version import MIN_JUVIX_VERSION

load_dotenv()

JUVIX_BIN = os.getenv("JUVIX_BIN", "juvix")
POETRY_BIN = os.getenv("POETRY_BIN", "poetry")

SRC_PATH = Path(__file__).parent
assert SRC_PATH.exists(), f"SRC_PATH {SRC_PATH} does not exist"
ROOT_PATH = SRC_PATH.parent
assert ROOT_PATH.exists(), f"ROOT_PATH {ROOT_PATH} does not exist"

FIXTURES_PATH = SRC_PATH / "fixtures"

def version_from_toml():
    toml_path = SRC_PATH.parent / "pyproject.toml"
    if toml_path.exists():
        with toml_path.open() as f:
            toml_data = toml.load(f)
        return toml_data["tool"]["poetry"]["version"]
    else:
        return "unknown"


__version__ = version_from_toml()


@click.group()
@click.version_option(
    version=__version__,
    help="Show the version of the CLI.",
)
def cli():
    """Helper CLI for making beautiful MkDocs sites with support for Juvix code blocks."""
    pass


@cli.command()
# Project Information
@click.option(
    "--project-name",
    default="my-juvix-project",
    help="Name of the project",
    show_default=True,
)
@click.option(
    "--description",
    default="A Juvix documentation project using MkDocs.",
    help="Description of the project",
    show_default=True,
)
@click.option(
    "--site-author",
    default="Tara",
    help="Site author",
    show_default=True,
)
@click.option(
    "--site-author-email",
    default="site@domain.com",
    help="Site author email",
    show_default=True,
)
@click.option(
    "--repo-url",
    default="https://github.com/anoma/juvix-mkdocs",
    help="Repository URL",
    show_default=True,
)
@click.option(
    "--repo-name",
    default="juvix-mkdocs",
    help="Repository name",
    show_default=True,
)
# Directory Settings
@click.option(
    "--output-dir",
    default=".",
    show_default=True,
    help="Output directory for the project",
)
@click.option(
    "--docs-dir", default="docs", help="Docs directory as for MkDocs", show_default=True
)
@click.option(
    "--site-dir", default="site", help="Site directory as for MkDocs", show_default=True
)
@click.option(
    "--bib-dir", default="docs/references", help="BibTeX directory", show_default=True
)
# Theme and Font Settings
@click.option("--theme", default="material", help="Theme to use", show_default=True)
@click.option("--font-text", default="Inter", help="Font for text", show_default=True)
@click.option(
    "--font-code", default="Source Code Pro", help="Font for code", show_default=True
)
# Feature Flags
@click.option("--no-bibtex", is_flag=True, help="Skip BibTeX plugin setup")
@click.option("--no-juvix-package", is_flag=True, help="Skip Juvix package setup")
@click.option("--no-everything", is_flag=True, help="Skip everything.juvix.md")
@click.option("--no-github-actions", is_flag=True, help="Skip GitHub Actions setup")
@click.option("--no-material", is_flag=True, help="Skip mkdocs-material installation")
@click.option("--no-assets", is_flag=True, help="Skip assets folder creation")
@click.option("--no-init-git", is_flag=True, help="Skip git repository initialization")
@click.option("--no-typecheck", is_flag=True, help="Skip typechecking the test file")
@click.option("--no-run-server", is_flag=True, help="Skip running mkdocs serve")
@click.option("--no-open", is_flag=True, help="Do not open the project in a browser")
# Behavior Flags
@click.option("--force", "-f", is_flag=True, help="Force overwrite existing files")
@click.option(
    "--server-quiet", "-q", is_flag=True, help="Run mkdocs serve in quiet mode"
)
@click.option(
    "-n", "--no-interactive", is_flag=True, help="Run in non-interactive mode"
)
@click.option(
    "--in-development",
    "-D",
    is_flag=True,
    help="Install mkdocs-juvix-plugin in development mode",
)
@click.option(
    "--develop-dir",
    default="../.",
    help="Directory to install mkdocs-juvix-plugin in development mode",
)
@click.option(
    "--anoma-setup",
    is_flag=True,
    help="Setup the project to follow the Anoma style",
)
def new(
    project_name,
    description,
    site_author,
    site_author_email,
    repo_url,
    repo_name,
    output_dir,
    docs_dir,
    site_dir,
    bib_dir,
    theme,
    font_text,
    font_code,
    no_bibtex,
    no_juvix_package,
    no_everything,
    no_github_actions,
    no_material,
    no_assets,
    no_init_git,
    no_typecheck,
    no_run_server,
    no_open,
    force,
    server_quiet,
    no_interactive,
    in_development,
    develop_dir,
    anoma_setup,
):
    """Subcommand to create a new Juvix documentation project."""

    if not no_interactive:
        # Project Information
        project_name = questionary.text("Project name:", default=project_name).ask()
        description = questionary.text(
            "Project description:", default=description
        ).ask()
        site_author = questionary.text("Site author:", default=site_author).ask()
        site_author_email = questionary.text(
            "Site author email:", default=site_author_email
        ).ask()

        # Directory Settings
        docs_dir = questionary.text("Docs directory:", default=docs_dir).ask()
        site_dir = questionary.text("Site directory:", default=site_dir).ask()

        # Theme and Font Settings
        theme = questionary.text("Theme to use:", default=theme).ask()
        font_text = questionary.text("Font for text:", default=font_text).ask()
        font_code = questionary.text("Font for code:", default=font_code).ask()

        no_bibtex = not questionary.confirm(
            "Set up BibTeX plugin?", default=not no_bibtex
        ).ask()
        bib_dir = questionary.text("BibTeX directory:", default=bib_dir).ask()

        # Juvix-specific Settings
        no_juvix_package = not questionary.confirm(
            f"Set up {docs_dir}/Package.juvix? (recommended)",
            default=not no_juvix_package,
        ).ask()
        no_everything = not questionary.confirm(
            f"Create {docs_dir}/everything.juvix.md? (recommended)",
            default=not no_everything,
        ).ask()

        # Additional Settings
        no_github_actions = not questionary.confirm(
            "Set up GitHub Actions workflow? (.github/workflows/ci.yml)",
            default=not no_github_actions,
        ).ask()
        no_assets = not questionary.confirm(
            f"Create {docs_dir}/assets folder?", default=not no_assets
        ).ask()

    project_path = (
        Path(output_dir) / project_name if output_dir != "." else Path(project_name)
    )

    if project_path.exists() and not force:
        if (
            no_interactive
            or not questionary.confirm(
                f"Directory {project_path.absolute()} already exists. Overwrite?"
            ).ask()
        ):
            click.secho(
                f"Directory {project_path.absolute()} already exists.", fg="red"
            )
            click.secho("Aborting.", fg="red")
            click.secho("=" * 70, fg="white")
            click.secho(
                "Try a different project name or use -f to force overwrite.",
                fg="yellow",
            )
            return

    if project_path.exists() and force:
        click.secho("Removing existing directory... ", nl=False)
        try:
            shutil.rmtree(project_path)
            click.secho("Done.", fg="green")
        except Exception as e:
            click.secho(f"Failed. Error: {e}", fg="red")
            return
    try:
        click.secho(f"Creating {project_path}... ", nl=False)
        project_path.mkdir(exist_ok=True, parents=True)
        click.secho("Done.", fg="green")
    except Exception as e:
        click.secho(f"Failed. Error: {e}", fg="red")
        return

    docs_path = project_path / docs_dir

    if not docs_path.exists():
        docs_path.mkdir(exist_ok=True, parents=True)
        click.secho(f"Creating {docs_path}... ", nl=False)
        click.secho("Done.", fg="green")
    else:
        click.secho(f"Folder {docs_path} already exists.", fg="yellow")

    # Check if juvix is installed and retrieve the version
    try:
        click.secho("Checking Juvix version... ", nl=False)
        juvix_version_output = (
            subprocess.check_output(
                [JUVIX_BIN, "--numeric-version"], stderr=subprocess.STDOUT
            )
            .decode()
            .strip()
        )
        click.secho("Done. ", fg="green", nl=False)
        click.secho(f" Juvix v{juvix_version_output}.", fg="black", bg="white")

        if Version.parse(juvix_version_output) < MIN_JUVIX_VERSION:
            click.secho(
                f"""Juvix version {MIN_JUVIX_VERSION} or higher is required. \
                        Please upgrade Juvix and try again.""",
                fg="red",
            )
            exit(1)

    except subprocess.CalledProcessError:
        click.secho(
            "Juvix is not installed. Please install Juvix and try again.", fg="red"
        )
        return

    juvixPackagePath = docs_path / "Package.juvix"
    if juvixPackagePath.exists():
        click.secho(
            f"Found {juvixPackagePath}. Use -f to force overwrite.", fg="yellow"
        )

    if not no_juvix_package and (not juvixPackagePath.exists() or force):
        try:
            click.secho(f"Initializing Juvix project in {docs_path}...", nl=False)
            subprocess.run([JUVIX_BIN, "init", "-n"], cwd=docs_path, check=True)
            click.secho("Done.", fg="green")
            if not juvixPackagePath.exists():
                click.secho(
                    "Failed to initialize Juvix project. Please try again.", fg="red"
                )
                return
            click.secho(f"Adding {juvixPackagePath}.", nl=False)
            click.secho("Done.", fg="green")

        except Exception as e:
            click.secho(
                f"Failed to initialize Juvix project. Please try again. Error: {e}",
                fg="red",
            )
            return

    # Create mkdocs.yml if it doesn't exist

    mkdocs_file = project_path / "mkdocs.yml"
    if mkdocs_file.exists():
        click.secho(f"Found {mkdocs_file}. Use -f to force overwrite.", fg="yellow")

    year = datetime.now().year

    index_file = docs_path / "index.md"
    test_file = docs_path / "test.juvix.md"
    isabelle_file = docs_path / "isabelle.juvix.md"
    diagrams_file = docs_path / "diagrams.juvix.md"
    images_file = docs_path / "images.md"
    juvix_md_files = [index_file, test_file, isabelle_file, diagrams_file, images_file]

    # this file is a bit special, as goes separately
    everything_file = docs_path / "everything.juvix.md"

    if not mkdocs_file.exists() or force:
        mkdocs_file.touch()
        click.secho(f"Adding {mkdocs_file}.", nl=False)
        mkdocs_file.write_text(
            (FIXTURES_PATH / "mkdocs.yml")
            .read_text()
            .format(
                site_dir=site_dir,
                site_author=site_author,
                project_name=project_name,
                repo_url=repo_url,
                repo_name=repo_name,
                theme=theme,
                anoma_theme_config=(
                    ""
                    if not anoma_setup
                    else (FIXTURES_PATH / "anoma_theme.yml").read_text()
                ),
                year=year,
                font_text=font_text,
                font_code=font_code,
                juvix_version=juvix_version_output,
                bibtex=("" if no_bibtex else f"  - bibtex:\n      bib_dir: {bib_dir}"),
                theme_features=(
                    ""
                    if no_material
                    else (FIXTURES_PATH / "material_features.yml").read_text()
                ),
                markdown_extensions=(
                    (FIXTURES_PATH / "markdown_extensions.yml").read_text()
                ),
            )
        )

        if anoma_setup:
            # copy "overrides" folder from FIXTURES_PATH to project_path /
            # "docs"
            try:
                click.secho("Copying overrides folder... ", nl=False)
                shutil.copytree(
                    FIXTURES_PATH / "overrides",
                    project_path / "overrides",
                    dirs_exist_ok=True,
                )
                click.secho("Done.", fg="green")
            except Exception as e:
                click.secho(f"Failed to copy overrides folder. Error: {e}", fg="red")
                click.secho("Aborting. Use -f to force overwrite.", fg="red")
                return

        click.secho("Done.", fg="green")
        click.secho("Copying assets folder... ", nl=False)
        if not no_assets:
            # copy the assets folder
            try:
                shutil.copytree(
                    FIXTURES_PATH / "assets",
                    project_path / "docs" / "assets",
                    dirs_exist_ok=force,
                )
                click.secho("Done.", fg="green")
            except Exception as e:
                click.secho(f"Failed to copy assets folder. Error: {e}", fg="red")
                click.secho("Aborting. Use -f to force overwrite.", fg="red")
                return
        else:
            click.secho("Skipping.", fg="yellow")

        # copy the images folder
        try:
            click.secho("Copying images folder... ", nl=False)
            shutil.copytree(
                FIXTURES_PATH / "images", docs_path / "images", dirs_exist_ok=force
            )
            click.secho("Done.", fg="green")
        except Exception as e:
            click.secho(f"Failed to copy images folder. Error: {e}", fg="red")

        click.secho("Updating `extra_css` section in mkdocs.yml... ", nl=False)
        valid_css_files = ["juvix-highlighting.css", "juvix_codeblock_footer.css"]
        if not no_material:
            valid_css_files.append("juvix-material-style.css")

        if "extra_css:" not in mkdocs_file.read_text():
            with mkdocs_file.open("a") as f:
                f.write("\n")
                f.write("extra_css:\n")
            for file in (project_path / "docs" / "assets" / "css").iterdir():
                relative_path = file.relative_to(project_path / "docs")
                if file.name in valid_css_files:
                    with mkdocs_file.open("a") as f:
                        f.write(f"  - {relative_path}\n")
            click.secho("Done.", fg="green")
        else:
            click.secho("Skipping.", fg="yellow")
            click.secho(
                f"Please check that: {', '.join(valid_css_files)} are present in the extra_css section of mkdocs.yml.",
                fg="yellow",
            )

        click.secho("Updating `extra_javascript` section in mkdocs.yml... ", nl=False)
        valid_js_files = ["highlight.js", "mathjax.js", "tex-svg.js"]
        if "extra_javascript:" not in mkdocs_file.read_text():
            with mkdocs_file.open("a") as f:
                f.write("\n")
                f.write("extra_javascript:\n")
            for file in (project_path / "docs" / "assets" / "js").iterdir():
                relative_path = file.relative_to(project_path / "docs")
                if file.name in valid_js_files:
                    with mkdocs_file.open("a") as f:
                        f.write(f"  - {relative_path}\n")
            click.secho("Done.", fg="green")
        else:
            click.secho("Skipping.", fg="yellow")
            click.secho(
                f"Please check that: {', '.join(valid_js_files)} are present in the extra_javascript section of mkdocs.yml.",
                fg="yellow",
            )

    click.secho("Creating .gitignore...", nl=False)
    gitignore_file = project_path / ".gitignore"
    if not gitignore_file.exists() or force:
        gitignore_file.write_text((FIXTURES_PATH / ".gitignore").read_text())
        click.secho("Done.", fg="green")
    else:
        click.secho("File already exists. Use -f to force overwrite.", fg="yellow")

    # Add README.md
    click.secho("Creating README.md...", nl=False)
    readme_file = project_path / "README.md"
    if not readme_file.exists() or force:
        readme_file.write_text((FIXTURES_PATH / "README.md").read_text())
        click.secho("Done.", fg="green")
    else:
        click.secho("File already exists. Use -f to force overwrite.", fg="yellow")

    # Run poetry init and add mkdocs-juvix-plugin mkdocs-material
    try:
        poetry_file = project_path / "pyproject.toml"
        click.secho("Creating pyproject.toml... ", nl=False)
        python_version = ">=3.10,<3.14"
        if not poetry_file.exists() or force:
            click.secho("Initializing poetry project... ", nl=False)
            subprocess.run(
                [
                    POETRY_BIN,
                    "init",
                    "-n",
                    f"--name={project_name}",
                    f"--description='{description}'",
                    f"--author={site_author}",
                    "--license=MIT",
                    f"--python={python_version}",
                ],
                cwd=project_path,
                check=True,
            )
            click.secho("Done.", fg="green")
        else:
            click.secho("File already exists. Use -f to force overwrite.", fg="yellow")
    except Exception as e:
        click.secho(f"Failed to initialize Poetry project. Error: {e}", fg="red")
        return

    def install_poetry_package(package_name, skip_flag=False, development_flag=False):
        # ask for confirmation
        if not no_interactive and not skip_flag:
            skip_flag = questionary.confirm(
                f"Install {package_name}? (recommended)",
                default=skip_flag,
            ).ask()
        if skip_flag:
            click.secho(f"Skipping installation of {package_name}", fg="yellow")
            return

        alias_package_name = (
            package_name if package_name != "../." else "mkdocs-juvix-plugin-DEV"
        )

        click.secho(f"Installing {alias_package_name}... ", nl=False)
        poetry_cmd = [POETRY_BIN, "add", package_name, "-n"]
        if development_flag:
            poetry_cmd.append("--editable")
        try:
            output = subprocess.run(
                poetry_cmd,
                cwd=project_path,
                capture_output=True,
            )
            if output.returncode != 0:
                # print complete output
                click.secho(output.stdout.decode("utf-8").strip())
                click.secho(f"Error: {output.stderr.decode('utf-8').strip()}", fg="red")
                if not no_interactive:
                    if questionary.confirm("Continue?", default=True).ask():
                        return

            else:
                click.secho("Done.", fg="green")
        except Exception as e:
            click.secho(f"{e}", fg="red")

    try:
        if in_development:
            install_poetry_package(develop_dir, development_flag=True)
        else:
            install_poetry_package("mkdocs-juvix-plugin")

        # rest of the plugins
        rest_of_plugins = [
            "mkdocs-material",
            "graphviz",
            "pymdown-extensions",
            "mkdocs-macros-plugin",
            "mkdocs-glightbox",
            "mkdocs-kroki-plugin",
            "mdx-truly-sane-lists",
        ]
        for plugin in rest_of_plugins:
            install_poetry_package(plugin)
    except Exception:
        return

    if not no_interactive:
        install_pre_commit = questionary.confirm(
            "Install pre-commit? (recommended)", default=True
        ).ask()
        if install_pre_commit:
            install_poetry_package("pre-commit")
            # move the pre-commit config to the project path
            pre_commit_file = project_path / ".pre-commit-config.yaml"
            if not pre_commit_file.exists() or force:
                pre_commit_file.write_text(
                    (FIXTURES_PATH / ".pre-commit-config.yaml").read_text()
                )
                click.secho("Done.", fg="green")
            else:
                click.secho(
                    "File already exists. Use -f to force overwrite.", fg="yellow"
                )

    try:
        if not no_bibtex:
            install_poetry_package("mkdocs-bibtex")
            ref_file = project_path / bib_dir / "ref.bib"
            click.secho(
                f"Adding {FIXTURES_PATH / 'ref.bib'} to {ref_file}...", nl=False
            )
            if not ref_file.exists():
                ref_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(FIXTURES_PATH / "ref.bib", ref_file)
                click.secho("Done.", fg="green")
            else:
                click.secho(
                    "File already exists. Use -f to force overwrite.", fg="yellow"
                )
        else:
            click.secho("Skipping", fg="yellow")
    except Exception as e:
        click.secho(
            f"Failed to add mkdocs-bibtex using Poetry. Error: {e}",
            fg="red",
        )
        return

    assets_path = docs_path / "assets"
    if not assets_path.exists() or force:
        assets_path.mkdir(parents=True, exist_ok=True)
        click.secho(f"Created folder {assets_path}", nl=False)
        click.secho("Done.", fg="green")

    for path_name in ["css", "js"]:
        path = assets_path / path_name
        if not path.exists() or force:
            path.mkdir(parents=True, exist_ok=True)
            click.secho(f"Created folder {path}", nl=False)
            click.secho("Done.", fg="green")

    # Create index.md
    for file in juvix_md_files:
        click.secho(f"Creating {file.name}... ", nl=False)
        if not file.exists() or force:
            file.write_text((FIXTURES_PATH / file.name).read_text())
            click.secho("Done.", fg="green")
        else:
            click.secho("File already exists. Use -f to force overwrite.", fg="yellow")

    if not no_everything:
        click.secho("Creating everything.juvix.md... ", nl=False)
        if not everything_file.exists() or force:
            everything_file.write_text(
                (FIXTURES_PATH / "everything.juvix.md").read_text()
            )
            click.secho("Done.", fg="green")
        else:
            click.secho("File already exists. Use -f to force overwrite.", fg="yellow")
    else:
        click.secho("Skipping", fg="yellow")

    github_actions_file = project_path / ".github" / "workflows" / "ci.yml"
    if not no_github_actions:
        click.secho("Creating GitHub Actions workflow...", nl=False)
        github_actions_file.parent.mkdir(parents=True, exist_ok=True)
        github_actions_file.write_text(
            (FIXTURES_PATH / "ci.yml")
            .read_text()
            .format(
                site_author=site_author,
                site_author_email=site_author_email,
                juvix_version=juvix_version_output,
                project_name=project_name,
            )
        )
        click.secho("Done.", fg="green")
    else:
        click.secho("Skipping", fg="yellow")

    # Moving the `tutorial` folder to the project path
    click.secho("Moving the `tutorial` folder to the project path...", nl=False)
    shutil.copytree(FIXTURES_PATH / "tutorial", project_path / "docs" / "tutorial")
    click.secho("Done.", fg="green")

    click.secho(f"Project '{project_name}' initialized successfully!", fg="green")
    click.secho("=" * 80, fg="white")
    typecheck = not no_typecheck
    if not no_interactive:
        typecheck = questionary.confirm(
            "Typecheck the test file?", default=typecheck
        ).ask()

    # Typecheck given files
    files_to_typecheck = [test_file, isabelle_file, diagrams_file, everything_file]
    if typecheck:
        for file in files_to_typecheck:
            click.secho(f"Typechecking {file}...", nl=False)
            try:
                subprocess.run(
                    ["juvix", "typecheck", file],
                    # cwd=project_path,
                    check=True,
                    capture_output=True,
                )
                click.secho("All good.", fg="green")
            except subprocess.CalledProcessError as e:
                click.secho("Failed.", fg="red")
                click.secho(f"Error: {e.stderr.decode().strip()}", fg="red")
    else:
        click.secho(
            f"Run, e.g., `juvix typecheck {files_to_typecheck[0]}` to typecheck the test file.",
            fg="yellow",
        )

    # Initialize git repository
    init_git = not no_init_git
    if not no_interactive:
        init_git = questionary.confirm(
            "Initialize git repository?", default=init_git
        ).ask()

    if init_git:
        click.secho("Initializing git repository...", nl=False)
        try:
            subprocess.run(
                ["git", "init", "-q"],
                cwd=project_path,
                check=True,
                capture_output=True,
            )
            click.secho("Done.", fg="green")
            # remember to commit the files
            click.secho(
                "- Run `git add .` to add the files to the repository.", fg="green"
            )
            click.secho(
                "- Run `git add .` to add the files to the repository.",
                fg="green",
            )
            click.secho(
                "- Run `git commit -m 'Initial commit'` to commit the files.",
                fg="green",
            )
        except subprocess.CalledProcessError as e:
            click.secho("Failed.", fg="red")
            click.secho(f"Error: {e.stderr.decode().strip()}", fg="red")
        except FileNotFoundError:
            click.secho("Failed.", fg="red")
            click.secho("[!] Git is not installed or not in the system PATH.", fg="red")
    else:
        click.secho("- Run `git init` to initialize a git repository.", fg="green")

    run_server = not no_run_server
    if not no_interactive:
        run_server = questionary.confirm(
            "Do you want to start the server? (`poetry run mkdocs serve`)",
            default=run_server,
        ).ask()

    if run_server:
        click.secho("Starting the server... (Ctrl+C to stop)", fg="yellow")
        try:
            mkdocs_serve_cmd = ["poetry", "run", "mkdocs", "serve", "--clean"]
            if not no_open:
                mkdocs_serve_cmd.append("--open")
            if server_quiet:
                mkdocs_serve_cmd.append("-q")
            subprocess.run(
                mkdocs_serve_cmd,
                cwd=project_path,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            click.secho("Failed to start the server.", fg="red")
            click.secho(f"Error: {e}", fg="red")
        except FileNotFoundError:
            click.secho("Failed to start the server.", fg="red")
            click.secho(
                "Make sure Poetry is installed and in your system PATH.", fg="red"
            )
    else:
        # Build the project
        try:
            click.secho("Building the project... ", nl=False)
            subprocess.run(
                ["poetry", "run", "mkdocs", "build"], cwd=project_path, check=True
            )
            click.secho("Done.", fg="green")
        except subprocess.CalledProcessError as e:
            click.secho("Failed to build the project.", fg="red")
            click.secho(f"Error: {e}", fg="red")
        except FileNotFoundError:
            click.secho("Failed to build the project.", fg="red")
            click.secho(
                "Make sure Poetry is installed and in your system PATH.", fg="red"
            )

        click.secho(
            "Run `poetry run mkdocs serve` to start the server when you're ready.",
            fg="yellow",
        )


@cli.command()
@click.option(
    "--project-path",
    "-p",
    type=Path,
    default=Path.cwd(),
    help="Path to the project",
    show_default=True,
)
@click.option("--no-open", is_flag=True, help="Do not open the project in a browser")
@click.option("--quiet", "-q", is_flag=True, help="Run mkdocs serve in quiet mode")
@click.option(
    "--config-file",
    type=Path,
    default=Path("mkdocs.yml"),
    help="Path to the mkdocs configuration file",
    show_default=True,
)
@click.option(
    "--remove-cache", "-r", is_flag=True, help="Remove the cache before serving"
)
@click.option(
    "--verbose", "-v", is_flag=True, help="Set the environment variable VERBOSE to 1"
)
def serve(
    project_path: Path,
    no_open: bool,
    quiet: bool,
    config_file: Path,
    verbose: bool,
    remove_cache: bool,
):
    """This is a wrapper around `poetry run mkdocs serve`.
    It is used to serve the project using mkdocs."""

    click.secho("Running in project path: ", nl=False)
    click.secho(f"{project_path}", fg="blue")
    # check if the config file exists
    if not (project_path / config_file).exists():
        click.secho(
            f"Config file {config_file} not found. Specify a different config file using --config-file.",
            fg="red",
        )
        return

    if remove_cache:
        try:
            if (project_path / ".cache-juvix-mkdocs").exists():
                shutil.rmtree(project_path / ".cache-juvix-mkdocs")
            else:
                click.secho("Cache folder not found.", fg="yellow")
        except Exception:
            click.secho("Failed to remove .cache-juvix-mkdocs folder.", fg="red")

    mkdocs_serve_cmd = ["poetry", "run", "mkdocs", "serve", "--clean"]
    if not no_open:
        mkdocs_serve_cmd.append("--open")
    if quiet:
        mkdocs_serve_cmd.append("-q")
    if verbose:
        mkdocs_serve_cmd.append("-v")
    if config_file:
        mkdocs_serve_cmd.append(f"--config-file={config_file}")
    try:
        click.secho(f"> Running command: {' '.join(mkdocs_serve_cmd)}", fg="yellow")
        subprocess.run(mkdocs_serve_cmd, cwd=project_path, check=True)
    except subprocess.CalledProcessError as e:
        click.secho("Failed to start the server.", fg="red")
        click.secho(f"Error: {e}", fg="red")
    except FileNotFoundError:
        click.secho("Failed to start the server.", fg="red")
        click.secho("Make sure Poetry is installed and in your system PATH.", fg="red")


@cli.command()
@click.option(
    "--project-path",
    "-p",
    type=Path,
    default=Path.cwd(),
    help="Path to the project",
    show_default=True,
)
@click.option(
    "--config-file",
    type=Path,
    default=Path("mkdocs.yml"),
    help="Path to the mkdocs configuration file",
    show_default=True,
)
@click.option(
    "--remove-cache", "-r", is_flag=True, help="Remove the cache before building"
)
@click.option("--quiet", "-q", is_flag=True, help="Run mkdocs build in quiet mode")
@click.option(
    "--verbose", "-v", is_flag=True, help="Set the environment variable VERBOSE to 1"
)
def build(
    project_path: Path,
    config_file: Path,
    remove_cache: bool,
    quiet: bool,
    verbose: bool,
):
    """This is a wrapper around `poetry run mkdocs build`."""
    click.secho("Running in project path: ", nl=False)
    click.secho(f"{project_path}", fg="blue")
    # check if the config file exists
    if not (project_path / config_file).exists():
        click.secho(
            f"Config file {config_file} not found. Specify a different config file using --config-file.",
            fg="red",
        )
        return
    mkdocs_build_cmd = ["poetry", "run", "mkdocs", "build"]
    if config_file:
        mkdocs_build_cmd.append(f"--config-file={config_file}")
    if quiet:
        mkdocs_build_cmd.append("-q")
    if verbose:
        mkdocs_build_cmd.append("-v")
    if remove_cache:
        try:
            shutil.rmtree(project_path / ".cache-juvix-mkdocs")
        except Exception:
            click.secho("Failed to remove .cache-juvix-mkdocs folder.", fg="red")
            return
    try:
        subprocess.run(mkdocs_build_cmd, cwd=project_path, check=True)
    except subprocess.CalledProcessError as e:
        click.secho("Failed to build the project.", fg="red")
        click.secho(f"Error: {e}", fg="red")


if __name__ == "__main__":
    cli()
