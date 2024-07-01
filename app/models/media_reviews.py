from datetime import datetime
import sys
from typing import Dict, List

from flask import jsonify
from sqlalchemy import ARRAY, Boolean, TIMESTAMP, Column, Float, ForeignKey, Integer, String, Text, func, inspect
from zoneinfo import ZoneInfo
from app.extensions import db
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateSchema
from sqlalchemy.orm import joinedload, relationship
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema
from marshmallow import fields, pre_load, validate

SCHEMA = 'media_reviews_schema'

# Association table for the many-to-many relationship between MediaReview and Genre


class MediaReviewGenre(db.Model):
    __tablename__ = 'media_review_genre'
    __table_args__ = {'schema': SCHEMA}

    media_review_id = Column(Integer, ForeignKey(
        f'{SCHEMA}.media_reviews.id'), primary_key=True)
    genre_id = Column(Integer, ForeignKey(
        f'{SCHEMA}.genres.id'), primary_key=True)


def initialise_media_reviews():
    with db.engine.connect() as connection:
        if not inspect(connection).has_schema(SCHEMA):
            print(f"Creating schema: {SCHEMA}", file=sys.stderr)
            connection.execute(CreateSchema(SCHEMA))
            connection.commit()


class MediaReview(db.Model):
    __tablename__ = 'media_reviews'
    __table_args__ = {'schema': SCHEMA}

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    media_type = Column(String, nullable=False)
    review_creation_date = Column(TIMESTAMP(
        timezone=True), default=datetime.now(tz=ZoneInfo("UTC")), nullable=False)
    review_last_update_date = Column(TIMESTAMP(timezone=True), default=datetime.now(
        tz=ZoneInfo("UTC")), onupdate=func.now(), nullable=False)
    cover_image = Column(String)
    rating = Column(Float)
    review_content = Column(Text)
    word_count = Column(Integer)
    run_time = Column(Integer)
    creator = Column(String)
    media_creation_date = Column(TIMESTAMP(timezone=True))
    consumed_date = Column(TIMESTAMP(timezone=True))
    pros = Column(ARRAY(String), nullable=False)
    cons = Column(ARRAY(String), nullable=False)
    visible = Column(Boolean, default=True)

    # Define relationship to Genre
    genres = relationship(
        'Genre', secondary=f'{SCHEMA}.media_review_genre', back_populates='media_reviews')

    # Define relationship to SubMediaReview
    sub_media_reviews = relationship(
        'SubMediaReview', back_populates='media_review', cascade="all, delete-orphan")

    def insert(self):
        if self.id:
            return jsonify({"error": "The 'id' field must be null if provided when creating a new MediaReview"}), 400

        # Check if the MediaReview already exists with the same name for the given media_review
        existing_review = MediaReview.query.filter_by(
            name=self.name).first()
        if existing_review:
            return jsonify({"error": f"Media with the name '{self.name}' already exists"}), 409

        try:
            # Fetch or create genres based on provided data
            genres: List[Genre] = self.genres
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

            self.genres = processed_genres

            db.session.add(self)
            db.session.commit()
            result = media_review_schema.dump(self)
            return jsonify(result), 201
        except IntegrityError:
            db.session.rollback()
            return jsonify({"error": "An error occurred while creating the media review"}), 500


class Genre(db.Model):
    __tablename__ = 'genres'
    __table_args__ = {'schema': SCHEMA}

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)

    # Define relationship to MediaReview
    media_reviews = db.relationship(
        'MediaReview', secondary=f'{SCHEMA}.media_review_genre', back_populates='genres')


class SubMediaReview(db.Model):
    __tablename__ = 'sub_media_reviews'
    __table_args__ = {'schema': SCHEMA}

    id = Column(Integer, primary_key=True)
    media_review_id = Column(Integer, ForeignKey(
        f'{SCHEMA}.media_reviews.id'), nullable=False)
    display_index = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    review_creation_date = Column(TIMESTAMP(
        timezone=True), default=datetime.now(tz=ZoneInfo("UTC")), nullable=False)
    review_last_update_date = Column(TIMESTAMP(timezone=True), default=datetime.now(
        tz=ZoneInfo("UTC")), onupdate=func.now(), nullable=False)
    cover_image = Column(String)
    rating = Column(Float)
    review_content = Column(Text)
    word_count = Column(Integer)
    run_time = Column(Integer)
    media_creation_date = Column(TIMESTAMP(timezone=True))
    consumed_date = Column(TIMESTAMP(timezone=True))
    pros = Column(ARRAY(String), nullable=False)
    cons = Column(ARRAY(String), nullable=False)

    media_review = relationship(
        'MediaReview', back_populates='sub_media_reviews')

    def insert(self):
        # Extract name and media_review_id for checking existence
        name = self.name
        media_review_id = self.media_review_id

        # Check if the MediaReview exists
        media_review = MediaReview.query.get(media_review_id)
        if not media_review:
            return jsonify({"error": "MediaReview with this ID does not exist"}), 404

        # Check if the SubMediaReview already exists with the same name for the given media_review
        existing_review = SubMediaReview.query.filter_by(
            name=name, media_review_id=media_review_id).first()
        if existing_review:
            return jsonify({"error": f"SubMediaReview with the name '{name}' already exists for the given media review"}), 409

        db.session.add(self)
        db.session.commit()

        try:
            # Serialize the new SubMediaReview instance
            result = sub_media_review_schema.dump(self)
            return jsonify(result), 201
        except IntegrityError:
            db.session.rollback()
            return jsonify({"error": "An error occurred while creating the sub media review"}), 500

    def update(self):
        # Check if one with the same name already exists
        existing_review = SubMediaReview.query.filter_by(
            name=self.name, media_review_id=self.media_review_id).first()

        if existing_review and existing_review.id != self.id:
            return jsonify({"error": f"SubMediaReview with the name '{existing_review.name}' already exists for the given media review"}), 409

        try:
            db.session.commit()
            result = sub_media_review_schema.dump(self)
            return jsonify(result), 200
        except IntegrityError:
            db.session.rollback()
            return jsonify({"error": "An error occurred while updating the media review"}), 500


class GenreSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = Genre
        load_instance = True
        include_fk = True
        sqla_session = db.session

    id = fields.Int(dump_only=True)
    name = fields.Str(required=True, validate=validate.Length(min=1))


class SubMediaReviewSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = SubMediaReview
        load_instance = True
        include_fk = True
        sqla_session = db.session

    id = fields.Int(dump_only=True)
    media_review_id = fields.Int(required=True, validate=validate.Range(min=1))
    display_index = fields.Int(required=True, validate=validate.Range(min=0))
    name = fields.Str(required=True, validate=validate.Length(min=1))
    review_creation_date = fields.DateTime(dump_only=True)
    review_last_update_date = fields.DateTime(dump_only=True)
    cover_image = fields.Str()
    rating = fields.Float(validate=validate.Range(min=0.0, max=10.0))
    review_content = fields.Str()
    word_count = fields.Int(validate=validate.Range(min=0))
    run_time = fields.Int(validate=validate.Range(min=0))
    media_creation_date = fields.DateTime()
    consumed_date = fields.DateTime()
    pros = fields.List(fields.Str(), required=True)
    cons = fields.List(fields.Str(), required=True)


class MediaReviewSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = MediaReview
        load_instance = True
        include_fk = True
        sqla_session = db.session

    id = fields.Int(dump_only=True)
    name = fields.Str(required=True, validate=validate.Length(min=1))
    media_type = fields.Str(validate=validate.OneOf(
        ["Movie", "Book", "Show", "Game", "Music"]))
    review_creation_date = fields.DateTime(dump_only=True)
    review_last_update_date = fields.DateTime(dump_only=True)
    cover_image = fields.Str(allow_none=True)
    rating = fields.Float(validate=validate.Range(
        min=0.0, max=10.0), allow_none=True)
    review_content = fields.Str(allow_none=True)
    word_count = fields.Int(validate=validate.Range(min=0), allow_none=True)
    run_time = fields.Int(validate=validate.Range(min=0), allow_none=True)
    creator = fields.Str(allow_none=True)
    media_creation_date = fields.DateTime(allow_none=True)
    consumed_date = fields.DateTime(allow_none=True)
    pros = fields.List(
        fields.Str(), required=True)
    cons = fields.List(
        fields.Str(), required=True)
    visible = fields.Bool(required=True)
    genres = fields.List(fields.Nested(GenreSchema), required=True)
    sub_media_reviews = fields.List(fields.Nested(
        SubMediaReviewSchema), dump_only=True)

    @pre_load
    def handle_null_fields(self, data, **kwargs):
        if 'review_last_update_date' in data:
            del data['review_last_update_date']
        if 'review_creation_date' in data:
            del data['review_creation_date']
        return data


# Instantiate the schema
sub_media_review_schema = SubMediaReviewSchema()
media_review_schema = MediaReviewSchema()
media_reviews_list_schema = MediaReviewSchema(many=True)
genre_list_schema = GenreSchema(many=True)


def media_review_to_response_item(review: MediaReview) -> Dict[str, any]:
    return {
        'id': review.id,
        'name': review.name,
        'media_type': review.media_type,
        'review_creation_date': review.review_creation_date.isoformat() if review.review_creation_date else None,
        'review_last_update_date': review.review_last_update_date.isoformat() if review.review_last_update_date else None,
        'cover_image': review.cover_image,
        'rating': review.rating,
        'review_content': review.review_content,
        'word_count': review.word_count,
        'run_time': review.run_time,
        'creator': review.creator,
        'media_creation_date': review.media_creation_date.isoformat() if review.media_creation_date else None,
        'consumed_date': review.consumed_date.isoformat() if review.consumed_date else None,
        'pros': review.pros,
        'cons': review.cons,
        'genres': [genre.name for genre in review.genres],
        'visible': review.visible
    }


def get_all_media_reviews_with_genres():
    reviews = db.session.query(MediaReview).options(
        joinedload(MediaReview.genres)).all()
    result = []

    for review in reviews:
        result.append(media_review_to_response_item(review))

    return result


def create_new_media_review(media_review: MediaReview, genres: List[str]):
    try:
        # Check if a media review with the same name and media_type already exists
        existing_review = MediaReview.query.filter_by(
            name=media_review.name, media_type=media_review.media_type).first()
        if existing_review:
            return jsonify({"error": f"A media review with the name '{existing_review.name}' and media_type '{existing_review.media_type}' already exists (id: {existing_review.id})"}), 409

        media_review.review_creation_date = datetime.now(tz=ZoneInfo("UTC"))
        media_review.review_last_update_date = media_review.review_creation_date

        db.session.add(media_review)
        db.session.commit()

        for genre_name in genres:
            genre = Genre.query.filter_by(name=genre_name).first()
            if not genre:
                genre = Genre(name=genre_name)
                db.session.add(genre)
                db.session.commit()

            media_review_genre = MediaReviewGenre(
                media_review_id=media_review.id, genre_id=genre.id)
            db.session.add(media_review_genre)

        db.session.commit()

        return jsonify(media_review_to_response_item(media_review)), 201

    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "An error occurred while creating the media review"}), 500


def update_media_review(media_review: MediaReview, genres: List[str]):
    try:
        # Handle genres
        if genres:
            new_genre_objs = []
            for genre_name in genres:
                genre = Genre.query.filter_by(name=genre_name).first()
                if not genre:
                    genre = Genre(name=genre_name)
                    db.session.add(genre)
                new_genre_objs.append(genre)

            # Update the media review's genres
            media_review.genres = new_genre_objs

            # Delete orphaned genres
            all_genres = Genre.query.all()
            for genre in all_genres:
                if not genre.media_reviews:
                    db.session.delete(genre)

        # Commit the changes
        db.session.commit()

        return jsonify(media_review_to_response_item(media_review)), 200
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "An error occurred while updating the media review"}), 500


def delete_media_review(media_review: MediaReview):
    # Delete the media review
    db.session.delete(media_review)

    # Commit the changes to delete the media review
    db.session.commit()

    # Delete orphaned genres
    all_genres = Genre.query.all()
    for genre in all_genres:
        if not genre.media_reviews:
            db.session.delete(genre)

    # Commit the changes to delete orphaned genres
    db.session.commit()

    return jsonify({"message": "Media review deleted successfully"}), 200


# Utility function
def create_example_reviews_and_genres():
    try:
        # Create some example genres
        genre1 = Genre(name='Action')
        genre2 = Genre(name='Drama')
        genre3 = Genre(name='Comedy')
        genre4 = Genre(name='Horror')
        genre5 = Genre(name='Science Fiction')
        genre6 = Genre(name='Romance')

        db.session.add_all([genre1, genre2, genre3, genre4, genre5, genre6])
        db.session.commit()

        # Create some example media reviews
        review1 = MediaReview(
            name='Review 1',
            media_type='Movie',
            review_creation_date=datetime.now(tz=ZoneInfo("UTC")),
            review_last_update_date=datetime.now(tz=ZoneInfo("UTC")),
            cover_image='http://example.com/cover1.jpg',
            rating=4.5,
            review_content='Great movie with a lot of action.',
            word_count=200,
            run_time=120,
            creator='Reviewer 1',
            media_creation_date=datetime(2023, 1, 1),
            consumed_date=datetime(2023, 1, 2),
            pros=['Great action scenes.'],
            cons=['Predictable plot.'],
            genres=[genre1, genre2]
        )

        review2 = MediaReview(
            name='Review 2',
            media_type='Series',
            review_creation_date=datetime.now(tz=ZoneInfo("UTC")),
            review_last_update_date=datetime.now(tz=ZoneInfo("UTC")),
            cover_image='http://example.com/cover2.jpg',
            rating=3.8,
            review_content='Funny series with great characters.',
            word_count=300,
            run_time=30,
            creator='Reviewer 2',
            media_creation_date=datetime(2023, 2, 1),
            consumed_date=datetime(2023, 2, 2),
            pros=['Hilarious dialogues.'],
            cons=['Some episodes are slow.'],
            genres=[genre2, genre3]
        )

        review3 = MediaReview(
            name='Review 3',
            media_type='Book',
            review_creation_date=datetime.now(tz=ZoneInfo("UTC")),
            review_last_update_date=datetime.now(tz=ZoneInfo("UTC")),
            cover_image='http://example.com/cover3.jpg',
            rating=4.2,
            review_content='A thrilling horror novel.',
            word_count=500,
            run_time=None,
            creator='Reviewer 3',
            media_creation_date=datetime(2023, 3, 1),
            consumed_date=datetime(2023, 3, 2),
            pros=['Keeps you on the edge of your seat.'],
            cons=['Somewhat predictable ending.'],
            genres=[genre4]
        )

        review4 = MediaReview(
            name='Review 4',
            media_type='Movie',
            review_creation_date=datetime.now(tz=ZoneInfo("UTC")),
            review_last_update_date=datetime.now(tz=ZoneInfo("UTC")),
            cover_image='http://example.com/cover4.jpg',
            rating=4.8,
            review_content='An amazing sci-fi adventure.',
            word_count=250,
            run_time=150,
            creator='Reviewer 4',
            media_creation_date=datetime(2023, 4, 1),
            consumed_date=datetime(2023, 4, 2),
            pros=['Great special effects.'],
            cons=['A bit too long.'],
            genres=[genre5]
        )

        review5 = MediaReview(
            name='Review 5',
            media_type='TV Show',
            review_creation_date=datetime.now(tz=ZoneInfo("UTC")),
            review_last_update_date=datetime.now(tz=ZoneInfo("UTC")),
            cover_image='http://example.com/cover5.jpg',
            rating=3.9,
            review_content='A heartwarming romance series.',
            word_count=350,
            run_time=45,
            creator='Reviewer 5',
            media_creation_date=datetime(2023, 5, 1),
            consumed_date=datetime(2023, 5, 2),
            pros=['Great chemistry between leads.'],
            cons=['Some clichés.'],
            genres=[genre6]
        )

        review6 = MediaReview(
            name='Review 6',
            media_type='Documentary',
            review_creation_date=datetime.now(tz=ZoneInfo("UTC")),
            review_last_update_date=datetime.now(tz=ZoneInfo("UTC")),
            cover_image='http://example.com/cover6.jpg',
            rating=4.7,
            review_content='An insightful and gripping documentary.',
            word_count=300,
            run_time=90,
            creator='Reviewer 6',
            media_creation_date=datetime(2023, 6, 1),
            consumed_date=datetime(2023, 6, 2),
            pros=['Very informative.'],
            cons=['Could have included more interviews.'],
            genres=[genre2, genre5]
        )

        db.session.add_all(
            [review1, review2, review3, review4, review5, review6])
        db.session.commit()

        print('Example reviews and genres created successfully.', file=sys.stderr)

    except IntegrityError:
        db.session.rollback()
        print('Error: Could not create example reviews and genres. There might be a conflict with existing data.', file=sys.stderr)
