# -*- coding: utf-8 -*-
import json
import os
import re
from collections import namedtuple
from math import ceil
from time import mktime

import dateutil.parser
import googleapiclient.discovery
from google.oauth2.service_account import Credentials
from sphinx.transforms.post_transforms.images import ImageConverter
from sphinx.util import logging
from sphinx.util.osutil import ensuredir

logger = logging.getLogger(__name__)

ImageFormat = namedtuple('FileType', ['mimetype', 'extension'])

ENVIRONMENT_NAME = 'GOOGLE_DRIVE_SERVICE_ACCOUNT_KEY'
drawings_re = re.compile('https://docs.google.com/drawings/d/([^/?]+)(?:/edit.*)?')


def url_to_file_id(url):
    # type: (str) -> str
    matched = drawings_re.match(url)
    if matched:
        return matched.group(1)

    return None


class GoogleDrive(object):
    SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

    def __init__(self, credentials):
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

    def get_last_modified(self, file_id):
        # type: (str) -> int
        request = self.service.files().get(fileId=file_id, fields='modifiedTime')
        stat = request.execute()
        d = dateutil.parser.parse(stat['modifiedTime'])
        return int(mktime(d.timetuple()))

    def get_image(self, file_id, mimetype):
        # type: (str, str) -> bytes
        request = self.service.files().export(fileId=file_id, mimeType=mimetype)
        return request.execute()


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

    def guess_imageformat_for(self, file_id):
        # type: (str) -> ImageFormat
        if 'application/pdf' in self.app.builder.supported_image_types:
            mimetype = 'application/pdf'
            fileext = '.pdf'
        else:
            mimetype = 'image/png'
            fileext = '.png'

        return ImageFormat(mimetype, fileext)

    def handle(self, node):
        # type: (nodes.Node) -> bool
        try:
            drive = self.connect_to_GoogleDrive()
            file_id = url_to_file_id(node['uri'])
            imgformat = self.guess_imageformat_for(file_id)

            path = os.path.join(self.imagedir, 'googledrive',
                                file_id + imgformat.extension)

            if os.path.exists(path):
                timestamp = ceil(os.stat(path).st_mtime)
                if timestamp <= drive.get_last_modified(file_id):
                    return True

            ensuredir(os.path.dirname(path))
            self.env.original_image_uri[path] = node['uri']

            with open(path, 'wb') as f:
                content = drive.get_image(file_id, imgformat.mimetype)
                f.write(content)

            node['candidates'].pop('?')
            node['candidates'][imgformat.mimetype] = path
            node['uri'] = path
            self.app.env.images.add_file(self.env.docname, path)
        except Exception as exc:
            logger.warning('Fail to download a image on Google Drive: %s (%r)', node['uri'], exc)
            return False


def setup(app):
    app.add_config_value('googledrive_service_account', None, 'env')
    app.add_post_transform(GoogleDriveImageConverter)
