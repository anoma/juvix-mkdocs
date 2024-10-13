import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import click
import questionary
from semver import Version

MIN_JUVIX_VERSION = Version(0, 6, 6)
SRC_PATH = Path(__file__).parent
FIXTURES_PATH = SRC_PATH / "fixtures"


@click.group()
def cli():
    """Helper CLI for making MkDocs projects with Juvix."""
    pass


@cli.command()
@click.option(
    "--project-name",
    default="my-juvix-project",
    help="Name of the project",
    show_default=True,
)
@click.option("--font-text", default="Inter", help="Font for text", show_default=True)
@click.option(
    "--font-code", default="Source Code Pro", help="Font for code", show_default=True
)
@click.option("--theme", default="material", help="Theme to use", show_default=True)
@click.option(
    "--description",
    default="A Juvix documentation project using MkDocs.",
    help="Description of the project",
    show_default=True,
)
@click.option(
    "--site-dir", default="site", help="Site directory as for MkDocs", show_default=True
)
@click.option(
    "--docs-dir", default="docs", help="Docs directory as for MkDocs", show_default=True
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
    "--bib-dir", default="docs/references", help="BibTeX directory", show_default=True
)
@click.option("--no-bibtex", is_flag=True, help="Skip BibTeX plugin setup")
@click.option("--force", "-f", is_flag=True, help="Force overwrite existing files")
@click.option("--no-juvix-package", is_flag=True, help="Skip Juvix package setup")
@click.option("--no-everything", is_flag=True, help="Skip everything.juvix.md")
@click.option("--no-github-actions", is_flag=True, help="Skip GitHub Actions setup")
@click.option("--no-material", is_flag=True, help="Skip mkdocs-material installation")
@click.option("--no-markdown-extensions", is_flag=True, help="Skip markdown extensions")
@click.option("--no-assets", is_flag=True, help="Skip assets folder creation")
@click.option("--no-init-git", is_flag=True, help="Skip git repository initialization")
@click.option("--no-typecheck", is_flag=True, help="Skip typechecking the test file")
@click.option("--no-run-server", is_flag=True, help="Skip running mkdocs serve")
@click.option(
    "-n", "--no-interactive", is_flag=True, help="Run in non-interactive mode"
)
def new(
    project_name,
    description,
    font_text,
    font_code,
    docs_dir,
    theme,
    site_dir,
    site_author,
    site_author_email,
    bib_dir,
    no_bibtex,
    force,
    no_juvix_package,
    no_everything,
    no_github_actions,
    no_material,
    no_markdown_extensions,
    no_assets,
    no_init_git,
    no_typecheck,
    no_run_server,
    no_interactive,
):
    """Create a new Juvix documentation project."""

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

        # Plugin and Feature Settings
        no_material = not questionary.confirm(
            "Install mkdocs-material? (recommended)", default=not no_material
        ).ask()
        no_markdown_extensions = not questionary.confirm(
            "Set up markdown extensions? (recommended)",
            default=not no_markdown_extensions,
        ).ask()
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

    project_path = Path(project_name)
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
            click.secho("=" * 80, fg="white")
            click.secho(
                "Try a different project name or use -f to force overwrite.",
                fg="yellow",
            )
            return

    if project_path.exists() and force:
        click.secho("Removing existing directory...", nl=False)
        try:
            shutil.rmtree(project_path)
            click.secho("Done.", fg="green")
        except Exception as _:
            click.secho("Failed.", fg="red")
            return

    project_path.mkdir(exist_ok=True, parents=True)
    click.secho(f"Creating {project_path}.", nl=False)
    click.secho("Done.", fg="green")

    docs_path = project_path / docs_dir

    if not docs_path.exists():
        docs_path.mkdir(exist_ok=True, parents=True)
        click.secho(f"Creating {docs_path}.", nl=False)
        click.secho("Done.", fg="green")
    else:
        click.secho(f"Folder {docs_path} already exists.", fg="yellow")

    # Check if juvix is installed and retrieve the version
    try:
        click.secho("Checking Juvix version...", nl=False)
        juvix_version = (
            subprocess.check_output(
                ["juvix", "--numeric-version"], stderr=subprocess.STDOUT
            )
            .decode()
            .strip()
        )
        click.secho("Done. ", fg="green", nl=False)
        click.secho(f" Juvix v{juvix_version}.", fg="black", bg="white")

        if Version.parse(juvix_version) < MIN_JUVIX_VERSION:
            click.secho(
                f"""Juvix version {MIN_JUVIX_VERSION} or higher is required. \
                        Please upgrade Juvix and try again.""",
                fg="red",
            )
            return

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
            click.secho("Initializing Juvix project... ", nl=False)
            subprocess.run(["juvix", "init", "-n"], cwd=docs_path, check=True)
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
                theme=theme,
                year=year,
                font_text=font_text,
                font_code=font_code,
                juvix_version=juvix_version,
                bibtex=("" if no_bibtex else f"  - bibtex:\n      bib_dir: {bib_dir}"),
                theme_features=(
                    ""
                    if no_material
                    else (FIXTURES_PATH / "material_features.yml").read_text()
                ),
                markdown_extensions=(
                    ""
                    if no_markdown_extensions
                    else (FIXTURES_PATH / "markdown_extensions.yml").read_text()
                ),
            )
        )
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

        click.secho("Updating `extra_css` section in mkdocs.yml... ", nl=False)
        valid_css_files = ["juvix-material-style.css", "juvix-highlighting.css"]
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
        if not poetry_file.exists() or force:
            click.secho("Initializing poetry project... ", nl=False)
            subprocess.run(
                [
                    "poetry",
                    "init",
                    "-n",
                    f"--name={project_name}",
                    f"--description='{description}'",
                    f"--author={site_author}",
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

    try:
        click.secho("Installing mkdocs-juvix-plugin... ", nl=False)
        subprocess.run(
            ["poetry", "add", "mkdocs-juvix-plugin", "-q", "-n"],
            cwd=project_path,
            check=True,
        )
        click.secho("Done.", fg="green")
    except Exception as e:
        click.secho(
            f"Failed to install mkdocs-juvix-plugin using Poetry. Error: {e}", fg="red"
        )
        return

    try:
        if not no_material:
            click.secho("Installing mkdocs-material... ", nl=False)
            subprocess.run(
                ["poetry", "add", "mkdocs-material", "-q", "-n"],
                cwd=project_path,
                check=True,
            )
            click.secho("Done.", fg="green")
        else:
            click.secho("Skipping", fg="yellow")
    except Exception as e:
        click.secho(
            f"Failed to add mkdocs-material using Poetry. Error: {e}",
            fg="red",
        )
        return

    try:
        if not no_bibtex:
            click.secho("Installing mkdocs-bibtex... ", nl=False)
            subprocess.run(
                ["poetry", "add", "mkdocs-bibtex", "-q", "-n"],
                cwd=project_path,
                check=True,
            )
            click.secho("Done.", fg="green")
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

    # Create docs folder and subfolders
    assets_path = docs_path / "assets"
    if not assets_path.exists() or force:
        assets_path.mkdir(parents=True, exist_ok=True)
        click.secho(f"Created folder {assets_path}", nl=False)
        click.secho("Done.", fg="green")

    css_path = assets_path / "css"
    js_path = assets_path / "js"

    if not css_path.exists() or force:
        css_path.mkdir(parents=True, exist_ok=True)
        click.secho(f"Created folder {css_path}", nl=False)
        click.secho("Done.", fg="green")

    if not js_path.exists() or force:
        js_path.mkdir(parents=True, exist_ok=True)
        click.secho(f"Created {js_path}.")

    # Create index.md
    click.secho("Creating index.juvix.md... ", nl=False)
    index_file = docs_path / "index.juvix.md"
    if not index_file.exists() or force:
        index_file.write_text((FIXTURES_PATH / "index.juvix.md").read_text())
        click.secho("Done.", fg="green")
    else:
        click.secho("File already exists. Use -f to force overwrite.", fg="yellow")

    click.secho("Creating test.juvix.md... ", nl=False)
    test_file = docs_path / "test.juvix.md"
    if not test_file.exists() or force:
        test_file.write_text((FIXTURES_PATH / "test.juvix.md").read_text())
        click.secho("Done.", fg="green")
    else:
        click.secho("File already exists. Use -f to force overwrite.", fg="yellow")

    if not no_everything:
        click.secho("Creating everything.juvix.md... ", nl=False)
        everything_file = docs_path / "everything.juvix.md"
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
                juvix_version=juvix_version,
                project_name=project_name,
            )
        )
        click.secho("Done.", fg="green")
    else:
        click.secho("Skipping", fg="yellow")

    click.secho(f"Project '{project_name}' initialized successfully!", fg="green")
    click.secho("=" * 80, fg="white")
    typecheck = not no_typecheck
    if not no_interactive:
        typecheck = questionary.confirm(
            "Typecheck the test file?", default=typecheck
        ).ask()

    # Typecheck the test file
    if typecheck:
        click.secho("Typechecking the test file ...", nl=False)
        try:
            subprocess.run(
                ["juvix", "typecheck", f"{docs_dir}/test.juvix.md"],
                cwd=project_path,
                check=True,
                capture_output=True,
            )
            click.secho("All good.", fg="green")
        except subprocess.CalledProcessError as e:
            click.secho("Failed.", fg="red")
            click.secho(f"Error: {e.stderr.decode().strip()}", fg="red")
    else:
        click.secho(
            "Run `juvix typecheck {docs_dir}/test.juvix.md` to typecheck the test file.",
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
        except subprocess.CalledProcessError as e:
            click.secho("Failed.", fg="red")
            click.secho(f"Error: {e.stderr.decode().strip()}", fg="red")
        except FileNotFoundError:
            click.secho("Failed.", fg="red")
            click.secho("Git is not installed or not in the system PATH.", fg="red")
    else:
        click.secho("Run `git init` to initialize a git repository.", fg="yellow")

    run_server = not no_run_server
    if not no_interactive:
        run_server = questionary.confirm(
            "Do you want to start the server now?", default=run_server
        ).ask()

    if run_server:
        click.secho("Starting the server...", fg="yellow")
        try:
            subprocess.run(
                ["poetry", "run", "mkdocs", "serve"], cwd=project_path, check=True
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
        click.secho(
            "Run `poetry run mkdocs serve` to start the server when you're ready.",
            fg="yellow",
        )


if __name__ == "__main__":
    cli()
