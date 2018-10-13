# -*- coding: utf-8 -*-
import json
import os
import re
from math import ceil
from time import mktime
from typing import TYPE_CHECKING

import dateutil.parser
import googleapiclient.discovery
import requests
from google.oauth2.service_account import Credentials
from googleapiclient.errors import HttpError
from sphinx.errors import ExtensionError
from sphinx.transforms.post_transforms.images import ImageConverter
from sphinx.util import logging
from sphinx.util.images import get_image_extension
from sphinx.util.osutil import ensuredir

if TYPE_CHECKING:
    from typing import Dict, Tuple  # NOQA
    from docutils import nodes  # NOQA

logger = logging.getLogger(__name__)

ENVIRONMENT_NAME = 'GOOGLE_DRIVE_SERVICE_ACCOUNT_KEY'
drive_url_re = re.compile('https://drive.google.com/open\\?id=([^/?]+)')
drawings_url_re = re.compile('https://docs.google.com/drawings/d/([^/?]+)(?:/edit.*)?')


def url_to_file_id(url):
    # type: (str) -> str
    matched = drive_url_re.match(url)
    if matched:
        return matched.group(1)

    matched = drawings_url_re.match(url)
    if matched:
        return matched.group(1)

    return None


class UnsupportedMimeType(Exception):
    pass


class GoogleDrive(object):
    SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
    IMAGE_INFO_FIELDS = 'mimeType,modifiedTime,trashed,webContentLink'

    def __init__(self, credentials):
        # type: (Credentials) -> None
        self.service = googleapiclient.discovery.build('drive', 'v3', credentials=credentials)

    @classmethod
    def from_service_account_file(cls, path):
        # type: (str) -> GoogleDrive
        credentials = Credentials.from_service_account_file(path, scopes=cls.SCOPES)
        return cls(credentials)

    @classmethod
    def from_service_account_info(cls, data):
        # type: (str) -> GoogleDrive
        params = json.loads(data)
        credentials = Credentials.from_service_account_info(params, scopes=cls.SCOPES)
        return cls(credentials)

    def get_image_info(self, file_id):
        # type: (str) -> Dict[str, str]
        request = self.service.files().get(fileId=file_id, fields=self.IMAGE_INFO_FIELDS)
        return request.execute()

    def get_image(self, file_id, mimetype):
        # type: (str, str) -> bytes
        request = self.service.files().export(fileId=file_id, mimeType=mimetype)
        return request.execute()


class Image:
    EXPORTABLE_IMAGES = ('application/vnd.google-apps.drawing',)

    def __init__(self, drive, file_id, supported_image_types):
        # type: (GoogleDrive, str, Tuple[str]) -> None
        image_info = drive.get_image_info(file_id)
        if image_info.get('trashed'):
            raise IOError('target file has been removed.')

        self.drive = drive
        self.file_id = file_id
        self.exportable = image_info.get('mimeType') in self.EXPORTABLE_IMAGES
        self.mimetype = self.guess_mimetype(image_info, supported_image_types)
        self.url = image_info.get('webContentLink')

        d = dateutil.parser.parse(image_info['modifiedTime'])
        self.last_modified = int(mktime(d.timetuple()))

    def guess_mimetype(self, image_info, supported_image_types):
        # type: (Dict[str, str], Tuple[str]) -> str
        mimetype = image_info.get('mimeType', '')
        if mimetype in self.EXPORTABLE_IMAGES:
            if 'application/pdf' in supported_image_types:
                return 'application/pdf'
            else:
                return 'image/png'
        else:
            if mimetype in supported_image_types:
                return mimetype
            else:
                raise UnsupportedMimeType(mimetype)

    @property
    def extension(self):
        # type: () -> str
        return get_image_extension(self.mimetype)

    def read(self):
        # type: () -> bytes
        if self.exportable:
            return self.drive.get_image(self.file_id, self.mimetype)
        else:
            r = requests.get(self.url)
            return r.content


class GoogleDriveImageConverter(ImageConverter):
    default_priority = 80  # before ImageDownloader

    def match(self, node):
        # type: (nodes.Node) -> bool
        uri = node.get('uri', '')
        return bool(url_to_file_id(uri))

    def connect_to_GoogleDrive(self):
        # type: () -> GoogleDrive
        if ENVIRONMENT_NAME in os.environ:
            account_info = os.environ[ENVIRONMENT_NAME]
            return GoogleDrive.from_service_account_info(account_info)
        elif self.config.googledrive_service_account:
            return GoogleDrive.from_service_account_file(self.config.googledrive_service_account)

        raise ExtensionError('service_account for google drive is not configured.')

    def handle(self, node):
        # type: (nodes.Node) -> None
        try:
            drive = self.connect_to_GoogleDrive()
            file_id = url_to_file_id(node['uri'])
            image = Image(drive, file_id, self.app.builder.supported_image_types)

            path = os.path.join(self.imagedir, 'googledrive', file_id + image.extension)
            if os.path.exists(path):
                timestamp = ceil(os.stat(path).st_mtime)
                if timestamp <= image.last_modified:
                    return

            ensuredir(os.path.dirname(path))
            self.env.original_image_uri[path] = node['uri']

            with open(path, 'wb') as f:
                f.write(image.read())

            node['candidates'].pop('?')
            node['candidates'][image.mimetype] = path
            node['uri'] = path
            self.app.env.images.add_file(self.env.docname, path)
        except IOError:
            logger.warning('Fail to download a image: %s (not found)', node['uri'])
        except UnsupportedMimeType as exc:
            logger.warning('Unsupported image: %s (%s)', node['uri'], exc)
        except Exception as exc:
            if isinstance(exc, HttpError) and exc.resp.status == 404:
                logger.warning('Fail to download a image: %s (not found)', node['uri'])
            else:
                logger.warning('Fail to download a image on Google Drive: %s (%r)', node['uri'], exc)


def setup(app):
    app.add_config_value('googledrive_service_account', None, 'env')
    app.add_post_transform(GoogleDriveImageConverter)
