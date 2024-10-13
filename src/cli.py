# asd

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import click
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
@click.option("--site-dir", default="docs", help="Site directory", show_default=True)
@click.option(
    "--site-author",
    default="Tara",
    help="Site author",
    show_default=True,
)
@click.option("--force", "-f", is_flag=True, help="Force overwrite existing files")
@click.option("--no-juvix-package", is_flag=True, help="Skip Juvix package setup")
@click.option("--no-everything", is_flag=True, help="Skip everything.juvix.md")
@click.option("--no-github-actions", is_flag=True, help="Skip GitHub Actions setup")
def new(
    project_name,
    description,
    font_text,
    font_code,
    theme,
    site_dir,
    site_author,
    force,
    no_juvix_package,
    no_everything,
    no_github_actions,
):
    """Create a new Juvix documentation project."""

    project_path = Path(project_name)

    if force and project_path.exists():
        try:
            shutil.rmtree(project_path)
        except Exception as e:
            click.secho(f"Failed to remove directory: {e}", fg="red")
            return
    elif project_path.exists():
        click.secho(
            f"Directory '{project_name}' already exists. Try -f to force overwrite.",
            fg="yellow",
        )
        return

    project_path.mkdir(exist_ok=True, parents=True)
    click.secho(f"Created {project_path}.")

    docs_path = project_path / "docs"
    docs_path.mkdir(exist_ok=True, parents=True)
    click.secho(f"Created {docs_path}.")

    # Check if juvix is installed and retrieve the version
    try:
        juvix_version = (
            subprocess.check_output(
                ["juvix", "--numeric-version"], stderr=subprocess.STDOUT
            )
            .decode()
            .strip()
        )

        if Version.parse(juvix_version) < MIN_JUVIX_VERSION:
            click.secho(
                f"""Juvix version {MIN_JUVIX_VERSION} or higher is required. \
                        Please upgrade Juvix and try again.""",
                fg="red",
            )
            return
        click.secho(f"Detected Juvix version {juvix_version}.")

    except subprocess.CalledProcessError:
        click.secho(
            "Juvix is not installed. Please install Juvix and try again.", fg="red"
        )
        return

    if not no_juvix_package:
        # Run 'juvix init -n' in the docs folder
        try:
            click.secho("Initializing Juvix project...", nl=False)
            subprocess.run(["juvix", "init", "-n"], cwd=docs_path, check=True)
            juvixPackagePath = docs_path / "Package.juvix"
            click.secho("Checking if Juvix package exists...")
            if not juvixPackagePath.exists():
                click.secho(
                    "Failed to initialize Juvix project. Please try again.", fg="red"
                )
                return
            click.secho("Done.", fg="green")
            click.secho(f"Created {juvixPackagePath}.")

        except Exception as e:
            click.secho(
                f"Failed to initialize Juvix project. Please try again. Error: {e}",
                fg="red",
            )
            return

    # Create mkdocs.yml if it doesn't exist
    mkdocs_file = project_path / "mkdocs.yml"
    year = datetime.now().year
    if not mkdocs_file.exists():
        mkdocs_file.touch()
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
            )
        )
        click.secho(f"Added {mkdocs_file}.")

        # copy the assets folder
        shutil.copytree(
            FIXTURES_PATH / "assets",
            project_path / "docs" / "assets",
            dirs_exist_ok=True,
        )

        with mkdocs_file.open("a") as f:
            f.write("\n")
            f.write("extra_css:\n")
        for file in (project_path / "docs" / "assets" / "css").iterdir():
            relative_path = file.relative_to(project_path / "docs")
            with mkdocs_file.open("a") as f:
                f.write(f"  - {relative_path}\n")
                click.secho(f"Added {relative_path}")

        with mkdocs_file.open("a") as f:
            f.write("\n")
            f.write("extra_javascript:\n")

        for file in (project_path / "docs" / "assets" / "js").iterdir():
            relative_path = file.relative_to(project_path / "docs")
            with mkdocs_file.open("a") as f:
                f.write(f"  - {relative_path}\n")
                click.secho(f"Added {relative_path}")

    # Create .gitignore if it doesn't exist
    gitignore_file = project_path / ".gitignore"
    if not gitignore_file.exists():
        gitignore_file.write_text((FIXTURES_PATH / ".gitignore").read_text())
        click.secho(f"Created {gitignore_file}.")

    # Add README.md
    readme_file = project_path / "README.md"
    readme_file.write_text((FIXTURES_PATH / "README.md").read_text())
    click.secho(f"Created {readme_file}.")

    # Run poetry init and add mkdocs-juvix-plugin mkdocs-material
    try:
        click.secho("Initializing poetry project...", nl=False)
        subprocess.run(
            [
                "poetry",
                "init",
                "-n",
                f"--name={project_name}",
                f"--description='{description}'",
                f"--author={site_author}",
                # f"--directory={project_path.as_posix()}",
                # "-q",
            ],
            cwd=project_path,
            check=True,
        )
        click.secho("Done.", fg="green")
        click.secho("Installing mkdocs-juvix-plugin... ", nl=False)
        subprocess.run(
            ["poetry", "add", "mkdocs-juvix-plugin", "-q", "-n"],
            cwd=project_path,
            check=True,
        )
        click.secho("Done.", fg="green")
        click.secho("Installing mkdocs-material... ", nl=False)
        subprocess.run(
            ["poetry", "add", "mkdocs-material", "-q", "-n"],
            cwd=project_path,
            check=True,
        )
        click.secho("Done.", fg="green")

    except Exception as e:
        click.secho(
            f"Failed to add mkdocs-juvix-plugin and mkdocs-material. Error: {e}",
            fg="red",
        )
        return

    # Create docs folder and subfolders
    assets_path = docs_path / "assets"
    if not assets_path.exists():
        assets_path.mkdir(parents=True, exist_ok=True)
        click.secho(f"Created {assets_path}.")

    css_path = assets_path / "css"
    js_path = assets_path / "js"

    if not css_path.exists():
        css_path.mkdir(parents=True, exist_ok=True)
        click.secho(f"Created {css_path}.")

    if not js_path.exists():
        js_path.mkdir(parents=True, exist_ok=True)
        click.secho(f"Created {js_path}.")

    # Create index.md
    index_file = docs_path / "index.md"
    index_file.write_text("# Welcome to Juvix Documentation\n")

    test_file = docs_path / "test.juvix.md"
    test_file.write_text((FIXTURES_PATH / "test.juvix.md").read_text())

    if not no_everything:
        everything_file = docs_path / "everything.juvix.md"
        everything_file.write_text((FIXTURES_PATH / "everything.juvix.md").read_text())

    if not no_github_actions:
        github_actions_file = project_path / ".github" / "workflows" / "ci.yml"
        click.secho("Creating GitHub Actions workflow...", nl=False)
        github_actions_file.parent.mkdir(parents=True, exist_ok=True)
        github_actions_file.write_text(
            (FIXTURES_PATH / "ci.yml")
            .read_text()
            .format(
                site_author=site_author,
                site_author_email="site@domain.com",
                juvix_version=juvix_version,
                project_name=project_name,
            )
        )
        click.secho("Done.", fg="green")
        click.secho(f"Added {github_actions_file}.")

    click.secho(f"Project '{project_name}' initialized successfully!", fg="green")
    click.secho("Run `poetry run mkdocs serve` to start the server.", fg="yellow")
    click.secho(
        "Run `juvix typecheck docs/test.juvix.md` to typecheck the test file.",
        fg="yellow",
    )
    click.secho("Run `git init` to initialize a git repository.", fg="yellow")


if __name__ == "__main__":
    cli()
