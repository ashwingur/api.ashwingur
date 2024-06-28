import sys
from flask_login import login_required
from app.mediareviews import bp
from flask import jsonify, request
from app.models.media_reviews import MediaReview, get_all_media_reviews_with_genres, create_new_media_review, update_media_review
from app.extensions import db, roles_required, limiter
from dateutil import parser

# Validate the field values, excluding ID
# Returns none if there is no issue, otherwise returns a response
def validate_media_review(data):
    name = data.get('name')
    media_type = data.get('media_type')
    cover_image = data.get('cover_image')
    rating = data.get('rating')
    review_content = data.get('review_content')
    word_count = data.get('word_count')
    run_time = data.get('run_time')
    creator = data.get('creator')
    media_creation_date = data.get('media_creation_date')
    consumed_date = data.get('consumed_date')
    pros = data.get('pros')
    cons = data.get('cons')
    visible = data.get('visible', True)
    genres = data.get('genres', [])

    if not name or not media_type:
        return jsonify({"error": "name and media_type are required"}), 400
    if media_type not in ["Movie", "Book", "Show", "Game", "Music"]:
        return jsonify({"error": f"Unknown media type {media_type}. It should be 'Movie', 'Book', 'Show', 'Game' or 'Music'"}), 400
    if media_creation_date and not is_valid_iso_string(media_creation_date):
        return jsonify({"error": f"media_creation_date '{media_creation_date}' is not a valid ISO 8601 date"}), 400
    if consumed_date and not is_valid_iso_string(consumed_date):
        return jsonify({"error": f"consumed_date '{consumed_date}' is not a valid ISO 8601 date"}), 400
    if rating and (rating < 0 or rating > 10):
        return jsonify({"error": f"rating was '{rating}' but must be between 0 and 10"}), 400
    if word_count and word_count < 0:
        return jsonify({"error": f"word_count was '{word_count}' but must be greater than 0"}), 400
    if run_time and run_time < 0:
        return jsonify({"error": f"run_time was '{run_time}' but must be greater than 0"}), 400
    if pros and not is_valid_list_of_non_empty_strings(pros):
        return jsonify({"error": f"pros must be a list of non-empty strings"}), 400
    if cons and not is_valid_list_of_non_empty_strings(cons):
        return jsonify({"error": f"cons must be a list of non-empty strings"}), 400
    if not isinstance(visible, bool):
        return jsonify({"error": f"visible must be a boolean"}), 400
    if not is_valid_list_of_non_empty_strings(genres):
        return jsonify({"error": f"genres must be a list of non-empty strings"}), 400
    
    return None


@bp.route('', methods=['GET'])
@limiter.limit('20/minute', override_defaults=True)
def get_review():
    return get_all_media_reviews_with_genres()
    

@bp.route('', methods=['POST'])
@login_required
@roles_required('admin')
@limiter.limit('10/minute', override_defaults=True)
def post_review():
    data = request.json

    id = data.get('id')
    if id is not None:
        return jsonify({"error": "ID should be null when creating a new media review"}), 400
    
    # Check if values are valid
    invalid_response = validate_media_review(data)
    if invalid_response:
        return invalid_response
    
    name = data.get('name')
    media_type = data.get('media_type')
    cover_image = data.get('cover_image')
    rating = data.get('rating')
    review_content = data.get('review_content')
    word_count = data.get('word_count')
    run_time = data.get('run_time')
    creator = data.get('creator')
    media_creation_date = data.get('media_creation_date')
    consumed_date = data.get('consumed_date')
    pros = data.get('pros')
    cons = data.get('cons')
    visible = data.get('visible', True)
    genres = data.get('genres', [])


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
        consumed_date=consumed_date,
        pros=pros,
        cons=cons,
        visible=visible
    )

    response = create_new_media_review(media_review, genres)

    return response

@bp.route('/<int:review_id>', methods=['PUT'])
@login_required
@roles_required('admin')
@limiter.limit('10/minute', override_defaults=True)
def update_review(review_id):
    data = request.json

    # Retrieve the media review by ID
    media_review = MediaReview.query.get(review_id)
    if not media_review:
        return jsonify({"error": "Media review not found"}), 404
    
    # Check if values are valid
    invalid_response = validate_media_review(data)
    if invalid_response:
        return invalid_response

    # Update the media review fields
    media_review.name = data.get('name', media_review.name)
    media_review.media_type = data.get('media_type', media_review.media_type)
    media_review.cover_image = data.get('cover_image', media_review.cover_image)
    media_review.rating = data.get('rating', media_review.rating)
    media_review.review_content = data.get('review_content', media_review.review_content)
    media_review.word_count = data.get('word_count', media_review.word_count)
    media_review.run_time = data.get('run_time', media_review.run_time)
    media_review.creator = data.get('creator', media_review.creator)
    media_review.media_creation_date = data.get('media_creation_date', media_review.media_creation_date)
    media_review.consumed_date = data.get('consumed_date', media_review.consumed_date)
    media_review.pros = data.get('pros', media_review.pros)
    media_review.cons = data.get('cons', media_review.cons)
    media_review.visible = data.get('visible', media_review.visible)

    # Handle genres
    new_genres = data.get('genres', [])

    response = update_media_review(media_review, new_genres)

    return response

def is_valid_list_of_non_empty_strings(obj):
    if not isinstance(obj, list):
        return False
    for item in obj:
        if not isinstance(item, str) or not item.strip():
            return False
    return True

def is_valid_iso_string(date_string):
    try:
        parser.isoparse(date_string)
        return True
    except ValueError:
        return False
