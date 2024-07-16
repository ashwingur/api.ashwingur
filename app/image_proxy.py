import base64
import hashlib
import hmac
import mimetypes

from config import Config


class ImageProxy:
    key = bytes.fromhex(Config.IMGPROXY_KEY)
    salt = bytes.fromhex(Config.IMGPROXY_SALT)

    @staticmethod
    def sign_image_url(url: str, use_webp: bool) -> str:
        # Detect the image source image format

        # Only process to webp if it isn't already and handle animated GIFs
        if use_webp:
            imgproxy_url = f'/rs:fit:0:320:0/plain/{url}@webp'
        else:
            imgproxy_url = f'/plain/{url}'

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
