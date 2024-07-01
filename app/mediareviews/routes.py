from datetime import datetime
import sys
from typing import List
from flask_login import login_required
from marshmallow import ValidationError
from app.mediareviews import bp
from flask import jsonify, request
from app.models.media_reviews import Genre, MediaReview, SubMediaReview, sub_media_review_schema, media_reviews_list_schema, media_review_schema
from app.models.media_reviews import get_all_media_reviews_with_genres, create_new_media_review, update_media_review, delete_media_review
from app.extensions import db, roles_required, limiter
from dateutil import parser
from zoneinfo import ZoneInfo
from sqlalchemy.exc import IntegrityError

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
        return jsonify({"error": f"Unknown media_type '{media_type}'. It should be 'Movie', 'Book', 'Show', 'Game' or 'Music'"}), 400
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
    # Query all media reviews from the database
    media_reviews = MediaReview.query.all()

    # Serialize the media reviews
    media_reviews_data = media_reviews_list_schema.dump(media_reviews)

    # Return the serialized data as a JSON response
    return jsonify(media_reviews_data)


@bp.route('', methods=['POST'])
@limiter.limit('10/minute', override_defaults=True)
@login_required
@roles_required('admin')
def create_review():
    json_data = request.get_json()

    if 'id' in json_data:
        json_data.pop('id')

    print(f'json data: {json_data}', file=sys.stderr)

    # Extract genres from json_data and remove it from the main data

    try:
        media_review: MediaReview = media_review_schema.load(json_data)
    except ValidationError as err:
        return jsonify({"error": f"Issue with provided fields: {err.messages}"}), 422

    # Check if the MediaReview already exists with the same name for the given media_review
    existing_review = MediaReview.query.filter_by(
        name=media_review.name).first()
    if existing_review:
        return jsonify({"error": f"Media with the name '{media_review.name}' already exists"}), 409

    # Fetch or create genres based on provided data
    genres: List[Genre] = media_review.genres
    processed_genres = []
    for genre in genres:
        existing_genre = Genre.query.filter_by(name=genre.name).first()
        if existing_genre:
            processed_genres.append(existing_genre)
        if not existing_genre:
            new_genre = Genre(name=genre.name)
            db.session.add(new_genre)
            db.session.flush()  # Ensures new_genre gets an ID
            processed_genres.append(new_genre)

    media_review.genres = processed_genres

    db.session.add(media_review)
    db.session.commit()
    result = media_review_schema.dump(media_review)
    return jsonify(result), 201


@bp.route('/<int:review_id>', methods=['PUT'])
@limiter.limit('10/minute', override_defaults=True)
@login_required
@roles_required('admin')
def update_review(review_id):
    data = request.json

    # Retrieve the media review by ID
    media_review = MediaReview.query.get(review_id)
    if not media_review:
        return jsonify({"error": f"Media review with id '{review_id}' not found"}), 404

    # Check if values are valid
    invalid_response = validate_media_review(data)
    if invalid_response:
        return invalid_response

    # Update the media review fields
    media_review.name = data.get('name', media_review.name)
    media_review.media_type = data.get('media_type', media_review.media_type)
    media_review.cover_image = data.get(
        'cover_image', media_review.cover_image)
    media_review.rating = data.get('rating', media_review.rating)
    media_review.review_content = data.get(
        'review_content', media_review.review_content)
    media_review.word_count = data.get('word_count', media_review.word_count)
    media_review.run_time = data.get('run_time', media_review.run_time)
    media_review.creator = data.get('creator', media_review.creator)
    media_review.media_creation_date = data.get(
        'media_creation_date', media_review.media_creation_date)
    media_review.consumed_date = data.get(
        'consumed_date', media_review.consumed_date)
    media_review.pros = data.get('pros', media_review.pros)
    media_review.cons = data.get('cons', media_review.cons)
    media_review.visible = data.get('visible', media_review.visible)
    media_review.review_last_update_date = datetime.now(tz=ZoneInfo("UTC"))

    new_genres = data.get('genres', [])

    response = update_media_review(media_review, new_genres)

    return response


@bp.route('/<int:review_id>', methods=['DELETE'])
@limiter.limit('3/minute; 20/hour', override_defaults=True)
@login_required
@roles_required('admin')
def delete_review(review_id):
    # Retrieve the media review by ID
    media_review = MediaReview.query.get(review_id)
    if not media_review:
        return jsonify({"error": "Media review not found"}), 404

    response = delete_media_review(media_review)
    return response


@bp.route('/submediareview/<int:id>', methods=['GET'])
def get_submediareview(id):
    sub_media_review = SubMediaReview.query.get(id)
    if not sub_media_review:
        return jsonify({"error": "SubMediaReview not found"}), 404

    result = sub_media_review_schema.dump(sub_media_review)
    return jsonify(result), 200


@bp.route('/submediareview', methods=['POST'])
def create_submediareview():
    json_data = request.get_json()
    if not json_data:
        return jsonify({'error': 'No input data provided'}), 400

    try:
        # Validate and deserialize input
        new_sub_media_review: SubMediaReview = sub_media_review_schema.load(
            json_data)
    except ValidationError as err:
        return jsonify({"error": f"Issue with provided fields: {err.messages}"}), 422

    return new_sub_media_review.insert()


@bp.route('/submediareview/<int:id>', methods=['PUT'])
def update_submediareview(id):
    json_data = request.get_json()
    if not json_data:
        return jsonify({'error': 'No input data provided'}), 400

    sub_media_review = SubMediaReview.query.get(id)
    if not sub_media_review:
        return jsonify({"error": "SubMediaReview not found"}), 404

    try:
        # Validate and deserialize input
        updated_sub_media_review: SubMediaReview = sub_media_review_schema.load(
            json_data, instance=sub_media_review, partial=True)
    except ValidationError as err:
        return jsonify({"error": f"Issue with provided fields: {err.messages}"}), 422

    return updated_sub_media_review.update()


@bp.route('/submediareview/<int:id>', methods=['DELETE'])
def delete_submediareview(id):
    sub_media_review = SubMediaReview.query.get(id)
    if not sub_media_review:
        return jsonify({"error": "SubMediaReview not found"}), 404

    try:
        db.session.delete(sub_media_review)
        db.session.commit()
        return '', 204
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "An error occurred while deleting the media review"}), 500


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
