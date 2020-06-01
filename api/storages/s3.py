from __future__ import unicode_literals
import os
import posixpath
import shutil
from io import TextIOBase, BytesIO
from functools import wraps
from tempfile import SpooledTemporaryFile
from threading import local
import boto3
from botocore.exceptions import ClientError

from PIL import Image, ImageOps

from django.conf import settings
from django.core.files.storage import Storage
from django.core.files.base import File

from django.contrib.staticfiles.storage import ManifestFilesMixin
from django.utils.six.moves.urllib.parse import urljoin
from django.utils.deconstruct import deconstructible
from django.utils.encoding import force_bytes, force_text
from django.utils.timezone import make_naive, utc

from ..settings import api_settings


# Some parts of Django expect an IOError, other parts expect an OSError, so this class inherits both!
# In Python 3, the distinction is irrelevant, but in Python 2 they are distinct classes.
if OSError is IOError:
    class S3Error(OSError):
        pass
else:
    class S3Error(OSError, IOError):
        pass


def _wrap_errors(func):
    @wraps(func)
    def _do_wrap_errors(self, name, *args, **kwargs):
        try:
            return func(self, name, *args, **kwargs)
        except ClientError as ex:
            raise S3Error("S3Storage error at {!r}: {}".format(name, force_text(ex)))
    return _do_wrap_errors


def _callable_setting(value, name):
    return value(name) if callable(value) else value


def _temporary_file():
    return SpooledTemporaryFile(max_size=1024 * 1024 * 50)  # 10 MB.


def _to_sys_path(name):
    return name.replace("/", os.sep)


def _to_posix_path(name):
    return name.replace(os.sep, "/")


def _wrap_path_impl(func):
    @wraps(func)
    def do_wrap_path_impl(self, name, *args, **kwargs):
        # The default implementations of most storage methods assume that system-native paths are used. But we deal with
        # posix paths. We fix this by converting paths to system form, passing them to the default implementation, then
        # converting them back to posix paths.
        return _to_posix_path(func(self, _to_sys_path(name), *args, **kwargs))
    return do_wrap_path_impl


class S3File(File):

    """
    A file returned from Amazon S3.
    """

    def __init__(self, file, name, storage):
        super(S3File, self).__init__(file, name)
        self._storage = storage

    def open(self, mode="rb"):
        if self.closed:
            self.file = self._storage.open(self.name, mode).file
        return super(S3File, self).open(mode)


class _Local(local):

    """
    Thread-local connection manager.

    Boto3 objects are not thread-safe.
    http://boto3.readthedocs.io/en/latest/guide/resources.html#multithreading-multiprocessing
    """

    def __init__(self, region="ap-northeast-2"):
        self.client = boto3.client('s3', region_name=region)


@deconstructible
class S3Storage(Storage):

    """
    An implementation of Django file storage over S3.
    """
    KEY_PREFIX = api_settings.ATTACHED_FILE_S3_KEY_PREFIX
    BUCKET_NAME = api_settings.ATTACHED_FILE_S3_BUCKET_NAME
    MEDIA_URL = api_settings.ATTACHED_FILE_MEDIA_URL
    RESIZE = False

    @property
    def s3_client(self):
        return self._connection.client

    def __init__(self, **kwargs):
        self._kwargs = kwargs
        self._base_url = None
        self._region = kwargs.get("region", api_settings.ATTACHED_FILE_S3_REGION)
        self._connection = _Local(self._region)
        super(S3Storage, self).__init__()


    # Helpers.
    def _get_key_name(self, name):
        if name.startswith("/"):
            name = name[1:]
        return posixpath.normpath(posixpath.join(self.KEY_PREFIX, _to_posix_path(name)))

    def _object_params(self, name):
        params = {
            "Bucket": self.BUCKET_NAME,
            "Key": self._get_key_name(name),
        }
        return params

    def _object_put_params(self, name):
        # Set basic params.
        params = {
            "ACL": "private"
        }
        params.update(self._object_params(name))
        return params

    @property
    def base_url(self):
        return self.MEDIA_URL

    @_wrap_errors
    def _open(self, name, mode="rb"):
        if mode != "rb":
            raise ValueError("S3 files can only be opened in read-only mode")
        # Load the key into a temporary file. It would be nice to stream the
        # content, but S3 doesn't support seeking, which is sometimes needed.
        obj = self.s3_client.get_object(**self._object_params(name))
        content = _temporary_file()
        shutil.copyfileobj(obj["Body"], content)
        content.seek(0)
        # Un-gzip if required.
        # if obj.get("ContentEncoding") == "gzip":
        #    content = gzip.GzipFile(name, "rb", fileobj=content)
        # All done!
        return S3File(content, name, self)

    @_wrap_errors
    def _save(self, name, content):
        put_params = self._object_put_params(name)
        temp_files = []
        # The Django file storage API always rewinds the file before saving,
        # therefor so should we.
        content.seek(0)
        saved = False
        # Convert content to bytes.
        if isinstance(content.file, TextIOBase):
            temp_file = _temporary_file()
            temp_files.append(temp_file)
            for chunk in content.chunks():
                temp_file.write(force_bytes(chunk))
            temp_file.seek(0)
            content = temp_file
        if self.RESIZE:
            with Image.open(content) as img:
                put_params["ContentType"] = Image.MIME[img.format]
                image_size = (512, 512)
                if img.width > image_size[0] or img.height > image_size[0]:
                    thumb = ImageOps.fit(img, image_size, Image.ANTIALIAS)
                    img_bytes = BytesIO()
                    thumb.save(img_bytes, format=img.format)
                    img_byte_array = img_bytes.getvalue()
                    self.s3_client.put_object(Body=img_byte_array, **put_params)
        else:
            self.s3_client.put_object(Body=content.read(), **put_params)

        # Close all temp files.
        for temp_file in temp_files:
            temp_file.close()
        # All done!
        return name

    # Subsiduary storage methods.
    @_wrap_path_impl
    def get_valid_name(self, name):
        return super(S3Storage, self).get_valid_name(name)

    @_wrap_path_impl
    def get_available_name(self, name, max_length=None):
        return super(S3Storage, self).get_available_name(name, max_length=max_length)

    @_wrap_path_impl
    def generate_filename(self, filename):
        return super(S3Storage, self).generate_filename(filename)

    @_wrap_errors
    def meta(self, name):
        """Returns a dictionary of metadata associated with the key."""
        return self.s3_client.head_object(**self._object_params(name))

    @_wrap_errors
    def delete(self, name):
        self.s3_client.delete_object(**self._object_params(name))

    def exists(self, name):
        name = _to_posix_path(name)
        if name.endswith("/"):
            # This looks like a directory, but on S3 directories are virtual, so we need to see if the key starts
            # with this prefix.
            results = self.s3_client.list_objects_v2(
                Bucket=self.BUCKET_NAME,
                MaxKeys=1,
                Prefix=self._get_key_name(name) + "/",  # Add the slash again, since _get_key_name removes it.
            )
            return "Contents" in results
        # This may be a file or a directory. Check if getting the file metadata throws an error.
        try:
            self.meta(name)
        except S3Error:
            # It's not a file, but it might be a directory. Check again that it's not a directory.
            return self.exists(name + "/")
        else:
            return True

    def listdir(self, path):
        path = self._get_key_name(path)
        path = "" if path == "." else path + "/"
        # Look through the paths, parsing out directories and paths.
        files = []
        dirs = []
        paginator = self.s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(
            Bucket=self.BUCKET_NAME,
            Delimiter="/",
            Prefix=path,
        )
        for page in pages:
            for entry in page.get("Contents", ()):
                files.append(posixpath.relpath(entry["Key"], path))
            for entry in page.get("CommonPrefixes", ()):
                dirs.append(posixpath.relpath(entry["Prefix"], path))
        # All done!
        return dirs, files

    def size(self, name):
        return self.meta(name)["ContentLength"]

    def url(self, name):
        # return urljoin(self.base_url, filepath_to_uri(name))
        return urljoin(self.base_url, posixpath.join(self.KEY_PREFIX, _to_posix_path(name)))

    def modified_time(self, name):
        return make_naive(self.meta(name)["LastModified"], utc)

    created_time = accessed_time = modified_time

    def get_modified_time(self, name):
        timestamp = self.meta(name)["LastModified"]
        return timestamp if settings.USE_TZ else make_naive(timestamp)

    get_created_time = get_accessed_time = get_modified_time

    """
    def sync_meta_iter(self):
        paginator = self.s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(
            Bucket=api_settings.ATTACHED_FILE_S3_BUCKET_NAME,
            Prefix=api_settings.ATTACHED_FILE_S3_KEY_PREFIX,
        )
        for page in pages:
            for entry in page.get("Contents", ()):
                name = posixpath.relpath(entry["Key"], api_settings.ATTACHED_FILE_S3_KEY_PREFIX)
                try:
                    obj = self.meta(name)
                except S3Error:
                    # This may be caused by a race condition, with the entry being deleted before it was accessed.
                    # Alternatively, the key may be something that, when normalized, has a different path, which will
                    # mean that the key's meta cannot be accessed.
                    continue
                put_params = self._object_put_params(name)
                # Set content encoding.
                content_encoding = obj.get("ContentEncoding")
                if content_encoding:
                    put_params["ContentEncoding"] = content_encoding
                # Update the metadata.
                self.s3_client.copy_object(
                    ContentType=obj["ContentType"],
                    CopySource={
                        "Bucket": self.settings.AWS_S3_BUCKET_NAME,
                        "Key": self._get_key_name(name),
                    },
                    MetadataDirective="REPLACE",
                    **put_params
                )
                yield name

    def sync_meta(self):
        for path in self.sync_meta_iter():
            pass
    """


class StaticS3Storage(S3Storage):
    """
    An S3 storage for storing static files.
    """
    BUCKET_NAME = api_settings.S3_BUCKET_NAME
    MEDIA_URL = api_settings.S3_IMAGE_MEDIA_URL
    KEY_PREFIX = ""
    RESIZE = False

    def __init__(self, **kwargs):
        self._kwargs = kwargs
        self.KEY_PREFIX = kwargs.get("key")
        self.RESIZE = kwargs.get("resize")
        super(StaticS3Storage, self).__init__()

    def _object_put_params(self, name):
        # Set basic params.
        params = {
            "ACL": "public-read"
        }
        params.update(self._object_params(name))
        return params


class ManifestStaticS3Storage(ManifestFilesMixin, StaticS3Storage):

    def post_process(self, *args, **kwargs):
        try:
            for r in super(ManifestStaticS3Storage, self).post_process(*args, **kwargs):
                yield r
        finally:
            pass
