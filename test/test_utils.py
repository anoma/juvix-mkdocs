import tempfile
from pathlib import Path
from mkdocs_juvix.utils import (
    compute_sha_over_folder,
    hash_file,
    compute_hash_filepath
)

def test_compute_sha_over_folder():
    with tempfile.TemporaryDirectory() as tmpdirname:
        folder_path = Path(tmpdirname)
        (folder_path / "file1.txt").write_text("Hello World")
        (folder_path / "file2.txt").write_text("Another file")
        
        # Compute hash
        folder_hash = compute_sha_over_folder(folder_path)
        
        # Verify hash is consistent
        assert isinstance(folder_hash, str)
        assert len(folder_hash) == 64  # SHA-256 hash length

def test_hash_file():
    with tempfile.NamedTemporaryFile(delete=False) as tmpfile:
        tmpfile.write(b"Hello World")
        tmpfile_path = Path(tmpfile.name)
    
    try:
        file_hash = hash_file(tmpfile_path)
        assert isinstance(file_hash, str)
        assert len(file_hash) == 64  # SHA-256 hash length
    finally:
        tmpfile_path.unlink()  # Clean up

def test_compute_hash_filepath():
    filepath = Path("/some/path/to/file.txt")
    hash_path = compute_hash_filepath(filepath)
    
    assert isinstance(hash_path, Path)
    assert len(hash_path.name) == 64  # SHA-256 hash length

def test_sha_changes_with_new_file():
    with tempfile.TemporaryDirectory() as tmpdirname:
        folder_path = Path(tmpdirname)
        
        # Create initial files
        (folder_path / "file1.txt").write_text("Hello World")
        (folder_path / "file2.txt").write_text("Another file")
        
        # Compute initial hash
        initial_hash = compute_sha_over_folder(folder_path)
        
        # Add a new file
        (folder_path / "new_file.txt").write_text("This is a new file")
        
        # Compute new hash
        new_hash = compute_sha_over_folder(folder_path)
        
        # Assert that the hash has changed
        assert initial_hash != new_hash, "SHA should change when a new file is added"
