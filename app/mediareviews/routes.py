from datetime import datetime
import sys
from typing import List
from flask_login import login_required
from marshmallow import ValidationError
from app.mediareviews import bp
from flask import jsonify, request
from app.models.media_reviews import Genre, MediaReview, SubMediaReview, sub_media_review_schema, media_reviews_list_schema, media_review_schema, genre_list_schema
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

    # Check if 'id' is present and has a value, if it's null we delete it and let it pass
    if 'id' in json_data:
        if json_data['id'] is not None:
            return jsonify({"error": "The 'id' field must be null if provided when creating a new MediaReview"}), 400
        json_data.pop('id')

    # Extract genres from json_data and remove it from the main data
    try:
        media_review: MediaReview = media_review_schema.load(json_data)
    except ValidationError as err:
        return jsonify({"error": f"Issue with provided fields: {err.messages}"}), 422

    response = media_review.insert()
    return response


@bp.route('/<int:review_id>', methods=['PUT'])
@limiter.limit('10/minute', override_defaults=True)
@login_required
@roles_required('admin')
def update_review(review_id):
    json_data = request.get_json()

    # Check for existing review
    existing_review = MediaReview.query.get(review_id)
    if not existing_review:
        return jsonify({"error": "MediaReview not found"}), 404

    # Temporarily remove genres from json_data to avoid premature processing
    genres_data = json_data.pop('genres', [])

    # Validate genres separately
    try:
        genre_list_schema.load(genres_data)
    except ValidationError as err:
        return jsonify({"error": f"Issue with provided genres: {err.messages}"}), 422

    # Parse input data without genres
    try:
        media_review: MediaReview = media_review_schema.load(
            json_data, partial=True, instance=existing_review)
    except ValidationError as err:
        return jsonify({"error": f"Issue with provided fields: {err.messages}"}), 422

    # Process genres separately
    genre_names = [genre['name'] for genre in genres_data]
    existing_genres = Genre.query.filter(Genre.name.in_(genre_names)).all()

    processed_genres = []
    # with db.session.no_autoflush:
    for genre_name in genre_names:
        existing_genre = next(
            (g for g in existing_genres if g.name == genre_name), None)
        if existing_genre:
            processed_genres.append(existing_genre)
        else:
            new_genre = Genre(name=genre_name)
            db.session.add(new_genre)
            db.session.flush()  # Ensures new_genre gets an ID
            processed_genres.append(new_genre)

    # Assign processed genres to the media review
    media_review.genres = processed_genres

    # Delete orphaned genres
    all_genres = Genre.query.all()
    for genre in all_genres:
        if not genre.media_reviews:
            db.session.delete(genre)

    # Commit changes
    try:
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        if "duplicate key value violates unique constraint" in str(e.orig):
            return jsonify({"error": "A genre with the same name already exists."}), 409
        return jsonify({"error": f"Error updating the review: {str(e)}"}), 500

    # Return updated review
    return jsonify(media_review_schema.dump(media_review)), 200


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
