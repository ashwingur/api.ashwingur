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


@bp.route('', methods=['GET'])
@limiter.limit('20/minute', override_defaults=True)
def get_review():
    # Query all media reviews from the database
    media_reviews = MediaReview.query.order_by(MediaReview.name.asc()).all()

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

    if 'id' in json_data:
        if json_data['id'] != review_id:
            return jsonify({"error": "The 'id' field in the body does not match the id field in the url"}), 400
        json_data.pop('id')

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
@limiter.limit('5/minute; 20/hour', override_defaults=True)
@login_required
@roles_required('admin')
def delete_review(review_id):
    media_review = MediaReview.query.get(review_id)
    if not media_review:
        return jsonify({"error": "MediaReview not found"}), 404

    try:
        db.session.delete(media_review)

        # Delete orphaned genres
        all_genres = Genre.query.all()
        for genre in all_genres:
            if not genre.media_reviews:
                db.session.delete(genre)
        db.session.commit()
        return '', 204
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "An error occurred while deleting the media review"}), 500


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
        return jsonify({"error": "An error occurred while deleting the sub media review"}), 500
