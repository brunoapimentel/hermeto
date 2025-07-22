import json
import logging
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Optional, Union

if TYPE_CHECKING:
    # Import conditionally so that we don't have to introduce a runtime dependency on
    # typing-extensions. This is only imported when a type-checker is running.
    # In python 3.11, it can be imported directly from the stdlib 'typing' module.
    from typing_extensions import assert_never

log = logging.getLogger(__name__)


def run_cmd(cmd: Union[list[str], str], **subprocess_kwargs: Any) -> tuple[str, int]:
    """
    Run command via subprocess.

    :param cmd: command to be executed
    :param subprocess_kwargs: passthrough kwargs to subprocess.run
    :return: Command output and exitcode
    :rtype: Tuple
    """
    log.info("Run command: %s.", cmd)

    # redirect stderr to stdout for easier evaluation/handling of a single stream
    forced_options = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "encoding": "utf-8",
        "text": True,
    }

    subprocess_kwargs.update(forced_options)
    process = subprocess.run(cmd, **subprocess_kwargs)

    return process.stdout, process.returncode


class ContainerRuntime(ABC):
    """Abstraction layer for container runtime operations."""
    def __init__(self):
        """Initialize container runtime."""
        self.runtime = ""
    
    @abstractmethod
    def pull_image(self, repository: str) -> tuple[str, int]:
        """Pull container image."""

    @abstractmethod
    def run_cmd_on_image(
        self,
        repository: str,
        cmd: list[str],
        tmp_path: Path,
        mounts: Sequence[tuple[Union[str, os.PathLike[str]], Union[str, os.PathLike[str]]]] = (),
        net: Optional[str] = None,
        container_flags: Optional[list[str]] = None,
    ) -> tuple[str, int]:
        """Run command on container image."""

    @abstractmethod
    def build_image(self, build_cmd: list[str], tag: str) -> tuple[str, int]:
        """Build container image."""

    @abstractmethod
    def remove_image(self, repository: str) -> tuple[str, int]:
        """Remove container image.""" 


class PodmanRuntime(ContainerRuntime):
    def __init__(self):
        """Initialize container runtime."""
        self.runtime = "podman"

    def build_image(self, build_cmd: list[str], tag: str) -> tuple[str, int]:
        """Build container image."""
        build_cmd = [self.runtime, *build_cmd, "--tag", tag]
        return run_cmd(build_cmd)
    
    def pull_image(self, repository: str) -> tuple[str, int]:
        """Pull container image."""
        return run_cmd([self.runtime, "pull", repository])

    def run_cmd_on_image(
        self,
        repository: str,
        cmd: list[str],
        tmp_path: Path,
        mounts: Sequence[tuple[Union[str, os.PathLike[str]], Union[str, os.PathLike[str]]]] = (),
        net: Optional[str] = None,
        container_flags: Optional[list[str]] = None,
    ) -> tuple[str, int]:
        """Run command using podman."""
        if container_flags is None:
            container_flags = []

        container_flags.extend(["-v", f"{tmp_path}:{tmp_path}:z"])
        for src, dest in mounts:
            container_flags.extend(["-v", f"{src}:{dest}:z"])
        if net:
            container_flags.append(f"--net={net}")

        image_cmd = ["podman", "run", "--rm", *container_flags, repository] + cmd
        return run_cmd(image_cmd)
    
    def remove_image(self, repository: str) -> tuple[str, int]:
        """Remove container image."""
        return run_cmd(["podman", "rmi", "--force", repository])


class BuildahRuntime(ContainerRuntime):
    def __init__(self):
        """Initialize container runtime.

        :param runtime: Container runtime to use ('podman' or 'buildah')
        """
        self.runtime = "buildah"
        self._image_cmd = ""
        self._image_entrypoint = ""
        self._container_id = ""
    
    def build_image(self, build_cmd: list[str], tag: str) -> tuple[str, int]:
        """Build container image."""
        return run_cmd([self.runtime, "--tag", tag, *build_cmd])

    def _configure_buildah_container(self, repository: str) -> str:
        # Create a working container from the image
        from_cmd = ["buildah", "from", repository]
        output, exit_code = run_cmd(from_cmd)
        if exit_code != 0:
            return output, exit_code

        # Extract container ID from output (usually the last line)
        return output.strip().split('\n')[-1]

    def _get_image_config(self, repository: str) -> tuple[str, str]:
                # Get the entrypoint of the image
        output, exit_code = run_cmd(["buildah", "inspect", repository])
        parsed_output = json.loads(output)

        cmd = parsed_output["Docker"]["config"]["Cmd"]
        entrypoint = parsed_output["Docker"]["config"]["Entrypoint"]

        return cmd, entrypoint

    def pull_image(self, repository: str) -> tuple[str, int]:
        """Pull container image."""
        return run_cmd([self.runtime, "pull", repository])

    def run_cmd_on_image(
        self,
        repository: str,
        cmd: list[str],
        tmp_path: Path,
        mounts: Sequence[tuple[Union[str, os.PathLike[str]], Union[str, os.PathLike[str]]]] = (),
        net: Optional[str] = None,
        container_flags: Optional[list[str]] = None,
    ) -> tuple[str, int]:
        """Run command using buildah."""
        if container_flags is None:
            container_flags = []

        container_id = self._configure_buildah_container(repository)
        image_cmd, image_entrypoint = self._get_image_config(repository)

        # fallback to the image's cmd if not provided
        cmd = cmd or image_cmd

        # if the image has an entrypoint, prepend it to the command
        if image_entrypoint:
            cmd = image_entrypoint + cmd

        # Mount volumes if needed
        mount_args = []
        mount_args.extend(["-v", f"{tmp_path}:{tmp_path}:z"])
        for src, dest in mounts:
            mount_args.extend(["-v", f"{src}:{dest}:z"])

        # Add network flag if specified
        network_args = []
        if net:
            network_args.extend(["--network", net])

        # Run the command in the container
        try:
            run_cmd_args = ["buildah", "run"] + mount_args + network_args + container_flags + [container_id, "--"] + cmd
            return run_cmd(run_cmd_args)
        finally:
            run_cmd(["buildah", "rm", container_id])
    
    def remove_image(self, repository: str) -> tuple[str, int]:
        """Remove container image."""
        # Clean up the working container
        return run_cmd(["buildah", "rmi", repository])


def get_container_runtime() -> ContainerRuntime:
    """Get the configured container runtime."""
    runtime_name = os.getenv("HERMETO_CONTAINER_RUNTIME", "podman").lower()

    if runtime_name == "podman":
        return PodmanRuntime()
    
    if runtime_name == "buildah":
        return BuildahRuntime()

    assert_never(runtime_name)
