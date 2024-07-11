from datetime import datetime
import sys
from typing import List
from flask_login import login_required
from marshmallow import ValidationError
from app.mediareviews import bp
from flask import jsonify, request
from app.models.media_reviews import Genre, MediaReview, SubMediaReview, sub_media_review_schema, media_reviews_list_schema, media_review_schema, genre_list_schema
from app.extensions import db, roles_required, limiter
from dateutil import parser
from zoneinfo import ZoneInfo
from sqlalchemy.exc import IntegrityError


@bp.route('', methods=['GET'])
@limiter.limit('40/minute', override_defaults=True)
def get_review():
    """
        Gets a list of all MediaReview items
    """
    # Query all media reviews from the database
    media_reviews = MediaReview.query.order_by(MediaReview.name.asc()).all()

    # Serialize the media reviews
    media_reviews_data = media_reviews_list_schema.dump(media_reviews)

    # Return the serialized data as a JSON response
    return jsonify(media_reviews_data)


@bp.route('/paginated', methods=['GET'])
@limiter.limit('60/minute', override_defaults=True)
def get_paginated_reviews():

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    media_types = request.args.getlist('media_types')
    order_by = request.args.get('order_by', "name_asc")

    query = MediaReview.query

    # apply filtering...
    if media_types:
        query = query.filter(MediaReview.media_type.in_(media_types))

    # order
    if order_by == "name_asc":
        query = query.order_by(MediaReview.name.asc(), MediaReview.id.asc())
    elif order_by == "name_desc":
        query = query.order_by(MediaReview.name.desc(), MediaReview.id.asc())
    elif order_by == "rating_asc":
        query = query.order_by(
            MediaReview.rating.asc().nulls_last(), MediaReview.id.asc())
    elif order_by == "rating_desc":
        query = query.order_by(
            MediaReview.rating.desc().nulls_last(), MediaReview.id.asc())
    elif order_by == "media_creation_asc":
        query = query.order_by(
            MediaReview.media_creation_date.asc().nulls_last(), MediaReview.id.asc())
    elif order_by == "media_creation_desc":
        query = query.order_by(
            MediaReview.media_creation_date.desc().nulls_last(), MediaReview.id.asc())
    elif order_by == "word_count_asc":
        query = query.order_by(
            MediaReview.word_count.asc().nulls_last(), MediaReview.id.asc())
    elif order_by == "word_count_desc":
        query = query.order_by(
            MediaReview.word_count.desc().nulls_last(), MediaReview.id.asc())
    else:
        query = query.order_by(MediaReview.name.asc(), MediaReview.id.asc())

    # Order the results and apply pagination
    paginated_reviews = query.paginate(
        page=page, per_page=per_page, max_per_page=30, error_out=False)

    media_reviews_data = media_reviews_list_schema.dump(
        paginated_reviews.items)

    response = {
        'total': paginated_reviews.total,
        'pages': paginated_reviews.pages,
        'current_page': paginated_reviews.page,
        'per_page': paginated_reviews.per_page,
        'has_next': paginated_reviews.has_next,
        'media_reviews': media_reviews_data
    }

    return jsonify(response)


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

    # Check if the MediaReview already exists with the same name for the given media_review
    existing_name = MediaReview.query.filter_by(
        name=media_review.name).first()
    if existing_name and existing_name.media_type == media_review.media_type:
        return jsonify({"error": f"Review with the name '{existing_name.name}' already exists for media_type '{existing_name.media_type}'"}), 409

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
@login_required
@roles_required('admin')
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
@login_required
@roles_required('admin')
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
@login_required
@roles_required('admin')
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
