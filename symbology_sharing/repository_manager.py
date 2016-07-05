# coding=utf-8
import csv
import os
import shutil

from PyQt4.QtCore import QObject, QSettings, QTemporaryFile

from symbology_sharing.utilities import repo_settings_group, local_collection_path
from symbology_sharing.repository_handler import BaseRepositoryHandler
from symbology_sharing.resource_handler import BaseResourceHandler
from symbology_sharing.network_manager import NetworkManager
from symbology_sharing.collections_manager import CollectionsManager
from symbology_sharing.collection import (
    COLLECTION_INSTALLED_STATUS, COLLECTION_NOT_INSTALLED_STATUS)


class RepositoryManager(QObject):
    """Class to handle repositories."""

    DIRECTORY_URL = 'https://raw.githubusercontent.com/anitagraser/QGIS-style-repo-dummy/master/directory.csv'

    def __init__(self):
        """Constructor.

        ..note:
        - Directories is a list of repository that are registered in user's
        QGIS. Data structure of directories:
        self._directories = {
            'QGIS Official Repository': 'git@github.com:anitagraser/QGIS-style-repo-dummy.git',
            'Akbar's Github Repository': 'git@github.com:akbargumbira/QGIS-style-repo-dummy.git',
            'Akbar's Bitbucket Repository': 'git@bitbucket.org:akbargumbira/qgis-style-repo-dummy.git'
        }
        """
        QObject.__init__(self)
        self._online_directories = {}
        self._directories = {}
        self._collections_manager = CollectionsManager()
        # Fetch online dir
        self.fetch_online_directories()
        # Load repositories from settings
        self.load()
        # Load collections from settings
        self._collections_manager.load()

    @property
    def directories(self):
        """Property for repositories registered in settings.

        :returns: Dictionary of repositories registered
        :rtype: dict
        """
        return self._directories

    @property
    def collections_manager(self):
        return self._collections_manager

    @property
    def collections(self):
        """Get all the collections registered."""
        return self._collections_manager.collections

    def fetch_online_directories(self):
        """Fetch online directory of repositories."""
        downloader = NetworkManager(self.DIRECTORY_URL)
        status, _ = downloader.fetch()
        if status:
            directory_file = QTemporaryFile()
            if directory_file.open():
                directory_file.write(downloader.content)
                directory_file.close()

            with open(directory_file.fileName()) as csv_file:
                reader = csv.DictReader(csv_file, fieldnames=('name', 'url'))
                for row in reader:
                    self._online_directories[row['name']] = row['url'].strip()

    def load(self):
        """Load repositories registered in settings."""
        self._directories = {}
        settings = QSettings()
        settings.beginGroup(repo_settings_group())

        # Write online directory first to QSettings if needed
        for online_dir_name in self._online_directories:
            repo_present = False
            for repo_name in settings.childGroups():
                url = settings.value(repo_name + '/url', '', type=unicode)
                if url == self._online_directories[online_dir_name]:
                    repo_present = True
                    break
            if not repo_present:
                self.add_repository(
                    online_dir_name, self._online_directories[online_dir_name])

        for repo_name in settings.childGroups():
            self._directories[repo_name] = {}
            url = settings.value(
                repo_name + '/url', '', type=unicode)
            self._directories[repo_name]['url'] = url
        settings.endGroup()

    def add_repository(self, repo_name, url):
        """Add repository to settings and add the collections from that repo.

        :param url: The URL of the repository
        :type url: str
        """
        repo_handler = BaseRepositoryHandler.get_handler(url)
        if repo_handler is None:
            raise Exception('There is no handler available for the given URL!')

        # Fetch metadata
        status, description = repo_handler.fetch_metadata()
        if status:
            # Parse metadata
            collections = repo_handler.parse_metadata()
            self._collections_manager.add_repo_collection(
                repo_name, collections)
            # Add to QSettings
            settings = QSettings()
            settings.beginGroup(repo_settings_group())
            settings.setValue(repo_name + '/url', url)
            settings.endGroup()
            # Serialize collections every time we successfully added repo
            self._collections_manager.serialize()

        return status, description

    def edit_repository(self, old_repo_name, new_repo_name, new_url):
        """Edit repository and update the collections."""
        # Fetch the metadata from the new url
        repo_handler = BaseRepositoryHandler.get_handler(new_url)
        if repo_handler is None:
            raise Exception('There is no handler available for the given URL!')
        status, description = repo_handler.fetch_metadata()

        if status:
            # Parse metadata
            collections = repo_handler.parse_metadata()
            # Remove old repo collections
            self._collections_manager.remove_repo_collection(old_repo_name)
            # Add collections with the new repo name
            self._collections_manager.add_repo_collection(
                new_repo_name, collections)
            # Update QSettings
            settings = QSettings()
            settings.beginGroup(repo_settings_group())
            settings.remove(old_repo_name)
            settings.setValue(new_repo_name + '/url', new_url)
            settings.endGroup()
            # Serialize collections every time we sucessfully edited repo
            self._collections_manager.serialize()
        return status, description

    def remove_repository(self, old_repo_name):
        """Remove repository and all the collections of that repository."""
        # Remove collections
        self._collections_manager.remove_repo_collection(old_repo_name)
        # Remove repo from QSettings
        settings = QSettings()
        settings.beginGroup(repo_settings_group())
        settings.remove(old_repo_name)
        settings.endGroup()
        # Serialize collections every time sucessfully remove a repo
        self._collections_manager.serialize()

    def reload_repository(self, repo_name, url):
        """Re-fetch the repository and update the collections registry."""
        status, description = self.edit_repository(repo_name, repo_name, url)
        return status, description

    def download_collection(self, collection_id):
        """Download collection given the id."""
        repo_url = self.collections[collection_id]['repository_url']
        repo_handler = BaseRepositoryHandler.get_handler(repo_url)
        if repo_handler is None:
            raise Exception('There is no handler available for the given URL!')
        register_name = self.collections[collection_id]['register_name']
        status, information = repo_handler.download_collection(
            collection_id, register_name)
        return status, information

    def install_collection(self, collection_id):
        """Install a collection."""
        for resource_handler in BaseResourceHandler.registry.values():
            resource_handler_instance = resource_handler(collection_id)
            resource_handler_instance.install()
        self.collections[collection_id]['status'] = COLLECTION_INSTALLED_STATUS

    def uninstall_collection(self, collection_id):
        """Uninstall the collection from QGIS."""
        # Remove the collection directory
        collection_dir = local_collection_path(collection_id)
        if os.path.exists(collection_dir):
            shutil.rmtree(collection_dir)
        # Uninstall all type of resources from QGIS
        for resource_handler in BaseResourceHandler.registry.values():
            resource_handler_instance = resource_handler(collection_id)
            resource_handler_instance.uninstall()
        self.collections[collection_id]['status'] = COLLECTION_NOT_INSTALLED_STATUS
