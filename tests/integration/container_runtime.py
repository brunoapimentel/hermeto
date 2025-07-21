import json
import logging
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from typing import Any, Optional, Union


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


class ContainerRuntime:
    """Abstraction layer for container runtime operations (podman/buildah)."""

    def __init__(self, runtime: str = "podman"):
        """Initialize container runtime.

        :param runtime: Container runtime to use ('podman' or 'buildah')
        """
        if runtime not in ("podman", "buildah"):
            raise ValueError(f"Unsupported container runtime: {runtime}")
        self.runtime = runtime

    def pull_image(self, repository: str) -> tuple[str, int]:
        """Pull container image."""
        cmd = [self.runtime, "pull", repository]

        output, exit_code = run_cmd(cmd)

        if exit_code == 0 and self.runtime == "buildah":
            self._configure_buildah_container(repository)

        return output, exit_code

    def _configure_buildah_container(self, repository: str) -> None:
        # Create a working container from the image
        from_cmd = ["buildah", "from", repository]
        output, exit_code = run_cmd(from_cmd)
        if exit_code != 0:
            return output, exit_code

        # Extract container ID from output (usually the last line)
        self._container_id = output.strip().split('\n')[-1]

        # Get the entrypoint of the image
        output, exit_code = run_cmd(["buildah", "inspect", repository])
        parsed_output = json.loads(output)

        self._image_cmd = parsed_output["Docker"]["config"]["Cmd"]
        self._image_entrypoint = parsed_output["Docker"]["config"]["Entrypoint"]

    def remove_image(self, repository: str) -> tuple[str, int]:
        """Remove container image."""
        if self.runtime == "podman":
            cmd = ["podman", "rmi", "--force", repository]
        else:
            # Clean up the working container
            run_cmd(["buildah", "rm", self._container_id])
            cmd = ["buildah", "rmi", repository]

        return run_cmd(cmd)

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
        if container_flags is None:
            container_flags = []

        if self.runtime == "podman":
            return self._run_with_podman(repository, cmd, tmp_path, mounts, net, container_flags)
        else:  # buildah
            return self._run_with_buildah(repository, cmd, tmp_path, mounts, net, container_flags)

    def _run_with_podman(
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

    def _run_with_buildah(
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

        # fallback to the image's cmd if not provided
        cmd = cmd or self._image_cmd
        # if the image has an entrypoint, prepend it to the command
        if self._image_entrypoint:
            cmd = self._image_entrypoint + cmd

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
        run_cmd_args = ["buildah", "run"] + mount_args + network_args + container_flags + [self._container_id, "--"] + cmd
        return run_cmd(run_cmd_args)

    def build_image(self, build_cmd: list[str], tag: str) -> tuple[str, int]:
        """Build container image."""
        build_cmd = [self.runtime, *build_cmd, "--tag", tag]
        return run_cmd(build_cmd)


def get_container_runtime() -> ContainerRuntime:
    """Get the configured container runtime."""
    runtime_name = os.getenv("HERMETO_CONTAINER_RUNTIME", "podman").lower()
    return ContainerRuntime(runtime_name)
