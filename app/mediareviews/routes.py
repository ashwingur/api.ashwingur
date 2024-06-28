from flask_login import login_required
from app.mediareviews import bp
from flask import jsonify, request
from app.models.media_reviews import MediaReview, get_all_media_reviews_with_genres, create_new_media_review
from app.extensions import db, roles_required
from sqlalchemy.exc import IntegrityError


@bp.route('', methods=['GET', 'POST'])
@login_required
@roles_required('admin')
def test():
    if request.method == 'GET':
        return get_all_media_reviews_with_genres()
    if request.method == 'POST':
        data = request.json

        id = data.get('id')
        if id is not None:
            return jsonify({"error": "ID should be null when creating a new media review"}), 400
        name = data.get('name')
        media_type = data.get('media_type')
        cover_image = data.get('cover_image')
        rating = data.get('rating')
        review_content = data.get('review_content')
        word_count = data.get('word_count')
        run_time = data.get('run_time')
        creator = data.get('creator')
        media_creation_date = data.get('media_creation_date')
        date_consumed = data.get('date_consumed')
        pros = data.get('pros')
        cons = data.get('cons')
        visible = data.get('visible', True)
        genres = data.get('genres', [])

        if not name or not media_type:
            return jsonify({"error": "name and media_type are required"}), 400
        
        # TODO: Dont allow it if a review with same name and media type exists

        media_review = MediaReview(
            name=name,
            media_type=media_type,
            cover_image=cover_image,
            rating=rating,
            review_content=review_content,
            word_count=word_count,
            run_time=run_time,
            creator=creator,
            media_creation_date=media_creation_date,
            date_consumed=date_consumed,
            pros=pros,
            cons=cons,
            visible=visible
        )

        response = create_new_media_review(media_review, genres)

        return response
