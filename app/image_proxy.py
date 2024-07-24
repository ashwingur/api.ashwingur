import base64
import hashlib
import hmac
from typing import Literal
from urllib.parse import quote_plus

from config import Config


class ImageProxy:
    key = bytes.fromhex(Config.IMGPROXY_KEY)
    salt = bytes.fromhex(Config.IMGPROXY_SALT)

    @staticmethod
    def sign_image_url(url: str, format: Literal['webp', 'avif', 'png', 'jpg'] | None,
                       resizing_type: Literal['fit', 'fill',
                                              'fill-down', 'force', 'auto'] = 'fit',
                       w=0, h=0, enlarge: bool = False, quality=75) -> str:
        # Escape special characters in url
        url = quote_plus(url)

        # Only process to webp if it isn't already and handle animated GIFs
        imgproxy_url = f'/rs:{resizing_type}:{w}:{h}:{1 if enlarge else 0}/q:{quality}'

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
