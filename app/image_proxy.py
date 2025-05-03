import base64
import hashlib
import hmac
import os
import re
from typing import Literal
import unicodedata
from urllib.parse import quote_plus
import requests
from werkzeug.utils import secure_filename
from flask import current_app

from config import Config


class ImageProxy:
    key = bytes.fromhex(Config.IMGPROXY_KEY)
    salt = bytes.fromhex(Config.IMGPROXY_SALT)

    @staticmethod
    def sign_image_url(url: str, format: Literal['webp', 'avif', 'png', 'jpg'] | None,
                       resizing_type: Literal['fit', 'fill',
                                              'fill-down', 'force', 'auto'] = 'fit',
                       w=0, h=0, enlarge: bool = False, quality=75, cachebuster: str = None) -> str:
        # Escape special characters in url
        if url.startswith("local:///"):
            # Only quote the path part, not the protocol
            url = "local:///" + quote_plus(url[9:])
        else:
            url = quote_plus(url)

        # Only process to webp if it isn't already and handle animated GIFs
        imgproxy_url = f'/rs:{resizing_type}:{w}:{h}:{1 if enlarge else 0}/q:{quality}'
        
        if cachebuster is not None:
            imgproxy_url += f'/cb:{quote_plus(str(cachebuster))}'

        if format:
            imgproxy_url = f'{imgproxy_url}/plain/{url}@{format}'
        else:
            imgproxy_url = f'{imgproxy_url}/plain/{url}'

        path = imgproxy_url.encode()

        digest = hmac.new(ImageProxy.key, msg=ImageProxy.salt +
                          path, digestmod=hashlib.sha256).digest()
        signature = base64.urlsafe_b64encode(digest).rstrip(b"=")

        url = b'/%s%s' % (
            signature,
            path,
        )

        if Config.FLASK_ENV == "DEV":
            base_url = "http://localhost:8080"
        else:
            base_url = "https://imgproxy.ashwingur.com"

        return base_url + url.decode()
    
    @staticmethod
    def download_image(url: str, filename: str) -> str:
        """
        Downloads an image from an external URL and saves it to the 'static/images' directory with the given filename.
        
        :param url: The URL of the image to download.
        :param filename: The name to save the image as (without path).
        :return: The full path to the saved image.
        """
        # Define the directory where images will be saved
        image_dir = os.path.join(current_app.root_path, 'static', 'images')

        # Ensure the directory exists
        os.makedirs(image_dir, exist_ok=True)

        # Add User-Agent header to mimic a browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/113.0.0.0 Safari/537.36'
        }
        # Get the image content from the URL
        response = requests.get(url, stream=True, headers=headers)

        # Check if the request was successful
        if response.status_code != 200:
            raise Exception(f"Failed to download image. Status code: {response.status_code}")

        # Sanitize the filename to prevent any issues
        filename = secure_filename(filename)

        # Define the path where the image will be saved
        save_path = os.path.join(image_dir, filename)

        # Save the image to the file
        with open(save_path, 'wb') as file:
            file.write(response.content)

        # Return the path where the image is saved
        return os.path.relpath(save_path, current_app.root_path)

    @staticmethod
    def rename_image(old_filename: str, new_filename: str) -> str:
        """
        Renames an existing image file in the 'static/images' directory.

        :param old_filename: The current name of the image file.
        :param new_filename: The new name to give the image file.
        :return: The new relative path of the renamed image.
        :raises FileNotFoundError: If the old image file does not exist.
        """
        image_dir = os.path.join(current_app.root_path, 'static', 'images')

        old_path = os.path.join(image_dir, secure_filename(old_filename))
        new_path = os.path.join(image_dir, secure_filename(new_filename))

        if not os.path.isfile(old_path):
            raise FileNotFoundError(f"Image '{old_filename}' not found.")

        os.rename(old_path, new_path)

        return os.path.relpath(new_path, current_app.root_path)

    @staticmethod
    def delete_image(filename: str) -> None:
        """
        Deletes an image from the 'static/images' directory.

        :param filename: The name of the image file to delete.
        :raises FileNotFoundError: If the image file does not exist.
        """
        image_dir = os.path.join(current_app.root_path, 'static', 'images')
        file_path = os.path.join(image_dir, secure_filename(filename))

        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Image '{filename}' not found.")

        os.remove(file_path)

    @staticmethod
    def sanitise_name(name: str) -> str:
        # Normalize Unicode characters to their closest ASCII equivalent
        name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')

        # Replace spaces and similar characters with underscore
        name = re.sub(r'[\s]+', '_', name)

        # Remove all characters except alphanumeric, underscore, and dash
        name = re.sub(r'[^\w\-]', '', name)

        return name