# -*- coding: utf-8 -*-
import json
import os
import re
from io import BytesIO
from math import ceil
from time import mktime
from typing import Dict, Tuple

import dateutil.parser
import googleapiclient.discovery
import PIL.Image
import requests
from docutils import nodes
from google.oauth2.service_account import Credentials
from googleapiclient.errors import HttpError
from sphinx.application import Sphinx
from sphinx.errors import ExtensionError
from sphinx.transforms.post_transforms.images import ImageConverter
from sphinx.util import logging
from sphinx.util.images import get_image_extension
from sphinx.util.osutil import ensuredir

logger = logging.getLogger(__name__)

ENVIRONMENT_NAME = 'GOOGLE_DRIVE_SERVICE_ACCOUNT_KEY'
drive_url_re = re.compile('https://drive.google.com/open\\?id=([^/?]+)')
drawings_url_re = re.compile('https://docs.google.com/drawings/d/([^/?]+)(?:/edit.*)?')


def url_to_file_id(url: str) -> str:
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

    def __init__(self, credentials: Credentials) -> None:
        self.service = googleapiclient.discovery.build('drive', 'v3', credentials=credentials)

    @classmethod
    def from_service_account_file(cls, path: str) -> "GoogleDrive":
        credentials = Credentials.from_service_account_file(path, scopes=cls.SCOPES)
        return cls(credentials)

    @classmethod
    def from_service_account_info(cls, data: str) -> "GoogleDrive":
        params = json.loads(data)
        credentials = Credentials.from_service_account_info(params, scopes=cls.SCOPES)
        return cls(credentials)

    def get_image_info(self, file_id: str) -> Dict[str, str]:
        request = self.service.files().get(fileId=file_id, fields=self.IMAGE_INFO_FIELDS)
        return request.execute()

    def get_image(self, file_id: str, mimetype: str) -> bytes:
        request = self.service.files().export(fileId=file_id, mimeType=mimetype)
        return request.execute()


class Image:
    EXPORTABLE_IMAGES = ('application/vnd.google-apps.drawing',)

    def __init__(self, drive: GoogleDrive, file_id: str, supported_image_types: Tuple[str]) -> None:
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

    def guess_mimetype(self, image_info: Dict[str, str], supported_image_types: Tuple[str]) -> str:
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
    def extension(self) -> str:
        return get_image_extension(self.mimetype)

    def read(self) -> bytes:
        if self.exportable:
            return self.drive.get_image(self.file_id, self.mimetype)
        else:
            r = requests.get(self.url)
            return r.content


def trim_image(content: bytes, mimetype: str) -> bytes:
    if mimetype in ('image/png', 'image/jpeg'):
        image = PIL.Image.open(BytesIO(content))
        box = image.getbbox()
        if box[0] != 0 or box[1] != 0 or box[2:] != image.size:
            output = BytesIO()
            fileext = get_image_extension(mimetype)
            image.crop(box).save(output, format=fileext[1:])
            content = output.getvalue()

    return content


class GoogleDriveImageConverter(ImageConverter):
    default_priority = 80  # before ImageDownloader

    def match(self, node: nodes.Node) -> bool:
        uri = node.get('uri', '')
        return bool(url_to_file_id(uri))

    def connect_to_GoogleDrive(self) -> GoogleDrive:
        if ENVIRONMENT_NAME in os.environ:
            account_info = os.environ[ENVIRONMENT_NAME]
            return GoogleDrive.from_service_account_info(account_info)
        elif self.config.googledrive_service_account:
            return GoogleDrive.from_service_account_file(self.config.googledrive_service_account)

        raise ExtensionError('service_account for google drive is not configured.')

    def handle(self, node: nodes.Node) -> None:
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
                content = image.read()
                if self.config.googledrive_trim_images:
                    content = trim_image(content, image.mimetype)
                f.write(content)

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


def setup(app: Sphinx):
    app.add_config_value('googledrive_service_account', None, 'env')
    app.add_config_value('googledrive_trim_images', bool, 'env')
    app.add_post_transform(GoogleDriveImageConverter)
