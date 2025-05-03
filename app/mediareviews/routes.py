from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import partial
import sys
from typing import List
from flask_login import login_required
from marshmallow import ValidationError
from sqlalchemy import func, or_, select
from app.image_proxy import ImageProxy
from app.mediareviews import bp
from flask import current_app, jsonify, request
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
@limiter.limit('10/second', override_defaults=True)
def get_paginated_reviews():

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    media_types = request.args.getlist('media_types')
    genres = request.args.getlist('genres')
    creators = request.args.getlist('creators')
    names = request.args.getlist('names')
    order_by = request.args.get('order_by', "name_asc")
    show_hidden = request.args.get('show_hidden', 'false').lower() in [
        'true', '1', 't', 'yes']

    query = MediaReview.query

    # apply filtering
    if names:
        query = query.outerjoin(SubMediaReview, MediaReview.sub_media_reviews).filter(
            or_(
                MediaReview.name.in_(names),
                SubMediaReview.name.in_(names)
            )
        ).distinct()

    if media_types:
        query = query.filter(MediaReview.media_type.in_(media_types))

    if creators:
        query = query.filter(MediaReview.creator.in_(creators))

    if genres:
        query = query.join(MediaReview.genres).filter(Genre.name.in_(genres))

    if not show_hidden:
        query = query.filter(MediaReview.visible == True)

    # Correlated subqueries for update dates (we want to take into account subquery update dates)
    last_update_date = select(
        func.coalesce(func.max(SubMediaReview.review_last_update_date),
                      MediaReview.review_last_update_date)
    ).where(SubMediaReview.media_review_id == MediaReview.id).scalar_subquery()

    # order
    if order_by == "last_update_desc":
        query = query.order_by(last_update_date.desc(), MediaReview.id.asc())
    elif order_by == "last_update_asc":
        query = query.order_by(last_update_date.asc(), MediaReview.id.asc())
    elif order_by == "name_asc":
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
        query = query.filter(MediaReview.word_count.isnot(None)).order_by(
            MediaReview.word_count.asc(), MediaReview.id.asc())
    elif order_by == "word_count_desc":
        query = query.filter(MediaReview.word_count.isnot(None)).order_by(
            MediaReview.word_count.desc(), MediaReview.id.asc())
    elif order_by == "run_time_asc":
        query = query.filter(MediaReview.run_time.isnot(None)).order_by(
            MediaReview.run_time.asc(), MediaReview.id.asc())
    elif order_by == "run_time_desc":
        query = query.filter(MediaReview.run_time.isnot(None)).order_by(
            MediaReview.run_time.desc(), MediaReview.id.asc())
    else:
        query = query.order_by(
            MediaReview.rating.desc().nulls_last(), MediaReview.id.asc())

    # Order the results and apply pagination
    paginated_reviews = query.paginate(
        page=page, per_page=per_page, max_per_page=20, error_out=False)

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


@bp.route('/metadata', methods=['GET'])
@limiter.limit('40/minute', override_defaults=True)
def get_metadata():
    """
        Returns all media review meta data including every genre and author
    """
    creators = MediaReview.query.with_entities(
        MediaReview.creator).filter(MediaReview.creator.isnot(None)).distinct().order_by(MediaReview.creator.asc()).all()

    genres = Genre.query.order_by(Genre.name.asc())

    media_reviews = MediaReview.query.with_entities(
        MediaReview.name, MediaReview.rating, MediaReview.word_count, MediaReview.run_time, MediaReview.media_type
    ).order_by(MediaReview.name.asc()).all()

    sub_media_reviews = SubMediaReview.query.with_entities(
        SubMediaReview.name, SubMediaReview.rating, SubMediaReview.word_count, SubMediaReview.run_time
    ).order_by(SubMediaReview.name.asc()).all()

    # Combine and deduplicate the review names
    all_review_names = list(set(
        [name[0] for name in media_reviews] + [name[0]
                                               for name in sub_media_reviews]
    ))
    all_review_names.sort()  # Sort the unique names

    genres_list = genre_list_schema.dump(genres)
    creators_list = [creator[0] for creator in creators]

    # Combine ratings by media type
    rating_bins = {'all': [0] * 10}
    rating_bins_with_sub_reviews = {'all': [0] * 10}

    for media_type in ['Movie', 'Book', 'Show', 'Game', 'Music']:
        rating_bins[media_type.lower()] = [0] * 10

    def categorize_ratings(reviews, bins, by_media_type=False):
        for review in reviews:
            rating = review[1]
            if rating is not None:
                # Ensure the index is between 0 and 9
                index = min(int(rating // 1), 9)
                bins['all'][index] += 1
                if by_media_type:
                    media_type = review[4]
                    if media_type:
                        bins[media_type.lower()][index] += 1

    categorize_ratings(media_reviews, rating_bins, by_media_type=True)
    categorize_ratings(media_reviews, rating_bins_with_sub_reviews)
    categorize_ratings(sub_media_reviews, rating_bins_with_sub_reviews)

    # Calculate total word count and run time
    total_word_count = sum(word_count for _, _, word_count,
                           _, _ in media_reviews if word_count is not None)

    total_run_time = sum(run_time for _, _, _, run_time,
                         _ in media_reviews if run_time is not None)
    
    # Get the counts of MediaReview and SubMediaReview
    media_review_count = len(media_reviews)
    sub_media_review_count = len(sub_media_reviews)

    return jsonify({
        'creators': creators_list,
        'genres': genres_list,
        'review_names': all_review_names,
        'rating_bins': rating_bins,
        'rating_bins_with_sub_reviews': rating_bins_with_sub_reviews,
        'total_word_count': total_word_count,
        'total_run_time': total_run_time,
        'media_review_count': media_review_count,
        'sub_media_review_count': sub_media_review_count
    })


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
    
    # Check if the name changed or cover image changed
    name_changed = False
    if json_data.get('name') != existing_review.name:
        name_changed = True
        old_name = existing_review.name
    cover_image_changed = False
    if json_data.get('cover_image') != existing_review.cover_image:
        cover_image_changed = True

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
    try:
        if name_changed and not cover_image_changed:
            ImageProxy.rename_image( MediaReview.encode_image_name(old_name),  MediaReview.encode_image_name(media_review.name))
        elif cover_image_changed and media_review.cover_image:
            ImageProxy.download_image(media_review.cover_image, MediaReview.encode_image_name(media_review.name))
    except Exception as e:
        print(f"Unable to download or update cover image for '{MediaReview.encode_image_name(media_review.name)}': {e}", file=sys.stderr)
        

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
        try:
            ImageProxy.delete_image(MediaReview.encode_image_name(media_review.name))
        except Exception as e:
            print(f"Unable to delete image for '{MediaReview.encode_image_name(media_review.name)}': {e}", file=sys.stderr)
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
        try:
            ImageProxy.delete_image(SubMediaReview.encode_image_name(sub_media_review.id))
        except Exception as e:
            print(f"Unable to delete image for '{SubMediaReview.encode_image_name(sub_media_review.id)}': {e}", file=sys.stderr)
        db.session.delete(sub_media_review)
        db.session.commit()
        return '', 204
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "An error occurred while deleting the sub media review"}), 500
    

@bp.route('/download-all-images', methods=['POST'])
@login_required
@roles_required('admin')
def download_all_images():
    media_reviews: List[MediaReview] = MediaReview.query.all()

    app = current_app._get_current_object()

    def download(review: MediaReview, app):
        with app.app_context():
            try:
                ImageProxy.download_image(review.cover_image, MediaReview.encode_image_name(review.name))
                print(f'Downloaded cover image for {review.name}', file=sys.stderr)
            except Exception as e:
                print(f"Unable to download cover image for '{ MediaReview.encode_image_name(review.name)}': {e}", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=20) as executor:
        executor.map(partial(download, app=app), media_reviews)

    sub_media_reviews: List[SubMediaReview] = SubMediaReview.query.all()
    def download(review: SubMediaReview, app):
        with app.app_context():
            try:
                ImageProxy.download_image(review.cover_image, SubMediaReview.encode_image_name(review.id))
                print(f'Downloaded cover image for {review.name}', file=sys.stderr)
            except Exception as e:
                print(f"Unable to download cover image for '{ MediaReview.encode_image_name(review.name)}': {e}", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=20) as executor:
        executor.map(partial(download, app=app), sub_media_reviews)

    return jsonify({"success": True}), 200