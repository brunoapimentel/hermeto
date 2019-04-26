# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import os
from abc import ABC, abstractmethod
import urllib.parse
import shutil
import tarfile
import tempfile
import subprocess

import requests

from cachito.errors import CachitoError


log = logging.getLogger(__name__)


class SCM(ABC):
    """The base class for interacting with source control."""

    def __init__(self, url, ref):
        """
        Initialize the SCM class.

        :param str url: the source control URL to the repository to fetch
        :param str ref: the source control reference
        """
        super().__init__()
        self.url = url
        self.ref = ref
        self._archives_dir = None
        self._archive_path = None
        self._repo_name = None

    @property
    def archive_path(self):
        """
        Get the path to where the archive for a particular SCM reference should be.

        :return: the path to the archive
        :rtype: str
        """
        if not self._archive_path:
            directory = os.path.join(self.archives_dir, *self.repo_name.split('/'))
            # Create the directories if they don't exist
            os.makedirs(directory, exist_ok=True)
            self._archive_path = os.path.join(directory, f'{self.ref}.tar.gz')

        return self._archive_path

    @property
    def archives_dir(self):
        """
        Get the absolute path of the archives directory from the Celery configuration.

        :returns: the absolute path of the archives directory
        :rtype: str
        """
        if not self._archives_dir:
            # Import this here to avoid a circular import
            import cachito.workers.tasks

            self._archives_dir = os.path.abspath(
                cachito.workers.tasks.app.conf.cachito_archives_dir
            )
            log.debug('Using "%s" as the archives directory', self._archives_dir)

        return self._archives_dir

    def download_source_archive(self, url):
        """
        Download the compressed archive of the source and place it in long-term storage.

        This is useful for services like GitHub, where they already provide a mechanism to
        download the compressed archive directly.

        :param str url: the URL to download the compressed source archive from
        :raises CachitoError: if the download fails
        """
        with tempfile.TemporaryDirectory(prefix='cachito-') as temp_dir:
            log.debug('Downloading the archive "%s"', url)
            with requests.get(url, stream=True, timeout=120) as response:
                if not response.ok:
                    log.error('The request to download "%s" failed with: %s', url, response.text)
                    if response.status_code == 404:
                        raise CachitoError('An invalid repository or reference was provided')
                    raise CachitoError(
                        'An unexpected error was encountered when downloading the source'
                    )

                temp_archive_path = os.path.join(temp_dir, os.path.basename(self.archive_path))
                with open(temp_archive_path, 'wb') as archive_file:
                    shutil.copyfileobj(response.raw, archive_file)

            extracted_src = None
            log.debug('Extracting the temporary archive at "%s"', temp_archive_path)
            with tarfile.open(temp_archive_path) as temp_archive:
                dir_name = temp_archive.firstmember.name
                temp_archive.extractall(temp_dir)
                extracted_src = os.path.join(temp_dir, dir_name)

            log.debug(
                'Recreating the archive with the correct directory structure at "%s"',
                self.archive_path,
            )
            with tarfile.open(self.archive_path, 'w:gz') as archive:
                archive.add(extracted_src, 'app')

    @abstractmethod
    def fetch_source(self):
        """
        Fetch the repo, create a compressed tar file, and put it in long-term storage.
        """

    @property
    @abstractmethod
    def repo_name(self):
        """
        Determine the repo name based on the URL
        """


class Git(SCM):
    """The git implementation of interacting with source control."""

    def clone_and_archive(self):
        """
        Clone the git repository and create the compressed source archive.

        :raises CachitoError: if cloning the repository fails or if the archive can't be created
        """
        error = 'An unexpected error was encountered when downloading the source'
        with tempfile.TemporaryDirectory(prefix='cachito-') as temp_dir:
            clone_path = os.path.join(temp_dir, 'repo')

            cmd = ['git', 'clone', '-q', '--no-checkout', self.url, clone_path]
            log.debug('Cloning the repo with "%s"', ' '.join(cmd))
            git_clone = subprocess.Popen(cmd, stderr=subprocess.PIPE)
            _, error_output = git_clone.communicate()
            if git_clone.returncode != 0:
                error_output = error_output.decode('utf-8')
                log.error(
                    'Cloning the git repository with "%s" failed with: %s',
                    ' '.join(cmd),
                    error_output,
                )
                raise CachitoError('Cloning the git repository failed')

            cmd = [
                'git',
                '-C',
                clone_path,
                'archive',
                '-o',
                self.archive_path,
                '--prefix=app/',
                self.ref,
            ]
            log.debug('Creating the archive with "%s"', ' '.join(cmd))
            git_archive = subprocess.Popen(cmd, stderr=subprocess.PIPE)
            _, error_output = git_archive.communicate()
            if git_archive.returncode != 0:
                error_output = error_output.decode('utf-8')
                log.error(
                    'Archiving the git repository with "%s" failed with: %s',
                    ' '.join(cmd),
                    error_output,
                )
                if 'Not a valid object name' in error_output:
                    error = 'An invalid reference was provided'
                # If git archive failed but still created the archive, then clean it up
                if os.path.exists(self.archive_path):
                    os.remove(self.archive_path)
                raise CachitoError(error)

    def fetch_source(self):
        """
        Fetch the repo, create a compressed tar file, and put it in long-term storage.
        """
        # If it already exists, don't download it again
        if os.path.exists(self.archive_path):
            log.debug('The archive already exists at "%s"', self.archive_path)
            return

        parsed_url = urllib.parse.urlparse(self.url)

        if parsed_url.netloc == 'github.com':
            log.debug('The SCM URL "%s" uses GitHub', self.url)
            url = f'https://github.com/{self.repo_name}/archive/{self.ref}.tar.gz'
            self.download_source_archive(url)
        else:
            self.clone_and_archive()

    @property
    def repo_name(self):
        """
        Determine the repo name based on the URL
        """
        if not self._repo_name:
            parsed_url = urllib.parse.urlparse(self.url)
            repo = parsed_url.path.strip('/')
            if repo.endswith('.git'):
                repo = repo[: -len('.git')]
            self._repo_name = repo
            log.debug('Parsed the repository name "%s" from %s', self._repo_name, self.url)

        return self._repo_name
