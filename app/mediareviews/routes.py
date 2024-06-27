from app.mediareviews import bp
from flask import jsonify, request
from app.models.media_reviews import get_all_media_reviews_with_genres


@bp.route('', methods=['GET'])
def test():
    if request.method == 'GET':
        return get_all_media_reviews_with_genres()