"""
Unit tests for Docker image extraction.

These tests verify the image extraction logic without requiring
a VM or root privileges. They test:
- Layer extraction and ordering
- CMD/ENTRYPOINT parsing
- Manifest handling
"""

import pytest
import sys
import os
import io
import json
import tarfile
import tempfile
import shutil
from pathlib import Path

# Add parent directory to path to import faasd
sys.path.insert(0, str(Path(__file__).parent.parent))
import faasd


class TestImageExtraction:
    """Test Docker image extraction functions."""

    def test_extract_simple_image(self, temp_dir):
        """Test extracting a simple Docker image with one layer."""
        # Create a minimal Docker image tarball
        image_tar = self._create_test_image(
            temp_dir,
            layers=[
                {"file.txt": b"hello world"}
            ],
            cmd=["echo", "hello"]
        )

        # Extract to rootfs
        rootfs_path = temp_dir / "rootfs"
        with open(image_tar, 'rb') as f:
            faasd.extract_docker_image(f, str(rootfs_path))

        # Verify extraction
        assert rootfs_path.exists()
        assert (rootfs_path / "file.txt").exists()
        assert (rootfs_path / "file.txt").read_bytes() == b"hello world"

    def test_extract_multi_layer_image(self, temp_dir):
        """Test that layers are applied in correct order (overlaying)."""
        # Create image with 3 layers that modify the same file
        image_tar = self._create_test_image(
            temp_dir,
            layers=[
                {"file.txt": b"layer1"},
                {"file.txt": b"layer2"},  # Overwrites layer1
                {"file.txt": b"layer3"},  # Overwrites layer2
            ],
            cmd=["cat", "file.txt"]
        )

        # Extract
        rootfs_path = temp_dir / "rootfs"
        with open(image_tar, 'rb') as f:
            faasd.extract_docker_image(f, str(rootfs_path))

        # Verify final layer wins (overlay behavior)
        content = (rootfs_path / "file.txt").read_bytes()
        assert content == b"layer3", "Final layer should overwrite previous layers"

    def test_extract_directory_structure(self, temp_dir):
        """Test extraction of nested directory structures."""
        image_tar = self._create_test_image(
            temp_dir,
            layers=[
                {
                    "app/handler.py": b"print('handler')",
                    "app/lib/utils.py": b"print('utils')",
                    "etc/config.json": b'{"key": "value"}',
                }
            ],
            cmd=["python3", "/app/handler.py"]
        )

        rootfs_path = temp_dir / "rootfs"
        with open(image_tar, 'rb') as f:
            faasd.extract_docker_image(f, str(rootfs_path))

        # Verify directory structure
        assert (rootfs_path / "app" / "handler.py").exists()
        assert (rootfs_path / "app" / "lib" / "utils.py").exists()
        assert (rootfs_path / "etc" / "config.json").exists()

    def test_get_image_entrypoint_cmd(self, temp_dir):
        """Test extracting CMD from image config."""
        image_tar = self._create_test_image(
            temp_dir,
            layers=[{"dummy.txt": b"data"}],
            cmd=["python3", "/app/handler.py"]
        )

        with open(image_tar, 'rb') as f:
            cmd = faasd.get_image_entrypoint(f)

        assert cmd == ["python3", "/app/handler.py"]

    def test_get_image_entrypoint_with_entrypoint(self, temp_dir):
        """Test extracting ENTRYPOINT + CMD from image config."""
        image_tar = self._create_test_image(
            temp_dir,
            layers=[{"dummy.txt": b"data"}],
            entrypoint=["python3"],
            cmd=["/app/handler.py"]
        )

        with open(image_tar, 'rb') as f:
            cmd = faasd.get_image_entrypoint(f)

        # ENTRYPOINT + CMD should be combined
        assert cmd == ["python3", "/app/handler.py"]

    def test_extract_missing_manifest_fails(self, temp_dir):
        """Test that extraction fails gracefully with invalid image."""
        # Create tarball without manifest.json
        invalid_tar = temp_dir / "invalid.tar"
        with tarfile.open(invalid_tar, 'w') as tar:
            # Add a random file but no manifest
            info = tarfile.TarInfo(name="random.txt")
            info.size = 5
            tar.addfile(info, io.BytesIO(b"hello"))

        rootfs_path = temp_dir / "rootfs"
        with pytest.raises(Exception, match="manifest.json not found"):
            with open(invalid_tar, 'rb') as f:
                faasd.extract_docker_image(f, str(rootfs_path))

    # Helper methods for creating test images

    def _create_test_image(
        self,
        work_dir: Path,
        layers: list,
        cmd: list = None,
        entrypoint: list = None
    ) -> Path:
        """
        Create a minimal Docker image tarball for testing.

        Args:
            work_dir: Working directory for creating tarball
            layers: List of dicts, each dict maps filename -> content
            cmd: CMD directive
            entrypoint: ENTRYPOINT directive

        Returns:
            Path to created tarball
        """
        layer_tars = []
        layer_ids = []

        # Create each layer tarball
        for i, layer_files in enumerate(layers):
            layer_id = f"layer{i}"
            layer_ids.append(layer_id)

            # Create layer tarball
            layer_tar_path = work_dir / f"{layer_id}.tar"
            with tarfile.open(layer_tar_path, 'w') as layer_tar:
                for filename, content in layer_files.items():
                    # Create parent directories if needed
                    if '/' in filename:
                        parts = filename.split('/')
                        for j in range(1, len(parts)):
                            dir_path = '/'.join(parts[:j])
                            dir_info = tarfile.TarInfo(name=dir_path)
                            dir_info.type = tarfile.DIRTYPE
                            dir_info.mode = 0o755
                            try:
                                layer_tar.addfile(dir_info)
                            except:
                                pass  # Directory may already exist

                    # Add file
                    info = tarfile.TarInfo(name=filename)
                    info.size = len(content)
                    info.mode = 0o644
                    layer_tar.addfile(info, io.BytesIO(content))

            layer_tars.append(f"{layer_id}.tar")

        # Create config
        config = {
            "architecture": "amd64",
            "config": {
                "Cmd": cmd or [],
                "Entrypoint": entrypoint or []
            },
            "rootfs": {
                "type": "layers",
                "diff_ids": [f"sha256:{lid}" for lid in layer_ids]
            }
        }

        config_json = json.dumps(config).encode()
        config_path = work_dir / "config.json"
        config_path.write_bytes(config_json)

        # Create manifest
        manifest = [{
            "Config": "config.json",
            "RepoTags": ["test:latest"],
            "Layers": layer_tars
        }]

        manifest_json = json.dumps(manifest).encode()
        manifest_path = work_dir / "manifest.json"
        manifest_path.write_bytes(manifest_json)

        # Create final image tarball
        image_tar = work_dir / "image.tar"
        with tarfile.open(image_tar, 'w') as tar:
            # Add manifest
            tar.add(manifest_path, arcname="manifest.json")
            # Add config
            tar.add(config_path, arcname="config.json")
            # Add layer tarballs
            for layer_tar_name in layer_tars:
                tar.add(work_dir / layer_tar_name, arcname=layer_tar_name)

        return image_tar


class TestRegistryFunctions:
    """Test registry management functions (if applicable)."""

    def test_registry_persistence(self, mock_registry_file):
        """Test that registry can be read and written."""
        # This is a placeholder - adjust based on actual registry functions in faasd
        assert mock_registry_file.exists()
        data = json.loads(mock_registry_file.read_text())
        assert isinstance(data, dict)
