import os
import shutil
from pathlib import Path

from click.testing import CliRunner

from src.cli import new


def test_new_command():
    runner = CliRunner()
    with runner.isolated_filesystem():
        project_name = "test_project"
        result = runner.invoke(
            new,
            [
                "--project-name",
                project_name,
                "--description",
                "Test project description",
                "--font-text",
                "Inter",
                "--font-code",
                "Fira Code",
                "--theme",
                "material",
                "--site-dir",
                "documentation",
                "--site-author",
                "Test Author",
                "--site-author-email",
                "test@example.com",
                "--force",
                "--no-juvix-package",
                "--no-everything",
                "--no-github-actions",
            ],
        )

        assert result.exit_code == 0
        assert f"Project '{project_name}' initialized successfully!" in result.output

        project_path = Path(project_name)
        assert project_path.exists()
        assert (project_path / "mkdocs.yml").exists()
        assert (project_path / ".gitignore").exists()
        assert (project_path / "README.md").exists()
        assert (project_path / "pyproject.toml").exists()
        assert (project_path / "documentation").exists()
        assert (project_path / "documentation" / "index.juvix.md").exists()
        assert (project_path / "documentation" / "test.juvix.md").exists()
        assert not (project_path / "documentation" / "everything.juvix.md").exists()
        assert not (project_path / ".github" / "workflows" / "ci.yml").exists()

        # Clean up
        shutil.rmtree(project_path)


def test_new_command_existing_directory():
    runner = CliRunner()
    with runner.isolated_filesystem():
        project_name = "existing_project"
        os.mkdir(project_name)

        result = runner.invoke(new, ["--project-name", project_name])

        assert result.exit_code == 0
        assert (
            f"Directory '{project_name}' already exists. Try -f to force overwrite."
            in result.output
        )


def test_new_command_force_overwrite():
    runner = CliRunner()
    with runner.isolated_filesystem():
        project_name = "force_overwrite_project"
        os.mkdir(project_name)
        (Path(project_name) / "existing_file.txt").write_text(
            "This file should be removed"
        )

        result = runner.invoke(new, ["--project-name", project_name, "--force"])

        assert result.exit_code == 0
        assert f"Project '{project_name}' initialized successfully!" in result.output
        assert not (Path(project_name) / "existing_file.txt").exists()

        # Clean up
        shutil.rmtree(project_name)


def test_new_command_with_everything_and_github_actions():
    runner = CliRunner()
    with runner.isolated_filesystem():
        project_name = "full_project"
        result = runner.invoke(new, ["--project-name", project_name, "--force"])

        assert result.exit_code == 0
        assert f"Project '{project_name}' initialized successfully!" in result.output

        project_path = Path(project_name)
        assert (project_path / "docs" / "everything.juvix.md").exists()
        assert (project_path / ".github" / "workflows" / "ci.yml").exists()

        # Clean up
        shutil.rmtree(project_path)
