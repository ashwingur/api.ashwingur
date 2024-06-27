from datetime import datetime
import sys

from sqlalchemy import ARRAY, inspect, text
from zoneinfo import ZoneInfo
from app.extensions import db
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateSchema
from sqlalchemy.orm import joinedload


SCHEMA = 'media_reviews_schema'

# Association table for the many-to-many relationship between MediaReview and Genre
class MediaReviewGenre(db.Model):
    __tablename__ = 'media_review_genre'
    __table_args__ = {'schema': SCHEMA}

    media_review_id = db.Column(db.Integer, db.ForeignKey(f'{SCHEMA}.media_reviews.id'), primary_key=True)
    genre_id = db.Column(db.Integer, db.ForeignKey(f'{SCHEMA}.genres.id'), primary_key=True)

def initialise_media_reviews():
    with db.engine.connect() as connection:
        if not inspect(connection).has_schema(SCHEMA):
            print("Creating schema...", file=sys.stderr)
            connection.execute(CreateSchema(SCHEMA))
            connection.commit()
        else:
            print("SCHEMA EXISTS...", file=sys.stderr)


class MediaReview(db.Model):
    __tablename__ = 'media_reviews'
    __table_args__ = {'schema': SCHEMA}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    media_type = db.Column(db.String, nullable=False)
    review_creation_date = db.Column(db.TIMESTAMP(timezone=True), default=datetime.now(tz=ZoneInfo("UTC")), nullable=False)
    review_last_update_date = db.Column(db.TIMESTAMP(timezone=True), default=datetime.now(tz=ZoneInfo("UTC")), onupdate=datetime.now(tz=ZoneInfo("UTC")), nullable=False)
    cover_image = db.Column(db.String)
    rating = db.Column(db.Float)
    review_content = db.Column(db.Text)
    word_count = db.Column(db.Integer)
    run_time = db.Column(db.Integer)
    creator = db.Column(db.String)
    creation_date = db.Column(db.TIMESTAMP(timezone=True))
    date_consumed = db.Column(db.TIMESTAMP(timezone=True))
    pros = db.Column(ARRAY(db.String))
    cons = db.Column(ARRAY(db.String))

    # Define relationship to Genre
    genres = db.relationship('Genre', secondary=f'{SCHEMA}.media_review_genre', back_populates='media_reviews')


class Genre(db.Model):
    __tablename__ = 'genres'
    __table_args__ = {'schema': SCHEMA}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False, unique=True)

    # Define relationship to MediaReview
    media_reviews = db.relationship('MediaReview', secondary=f'{SCHEMA}.media_review_genre', back_populates='genres')


def get_all_media_reviews_with_genres():
    reviews = db.session.query(MediaReview).options(joinedload(MediaReview.genres)).all()
    result = []

    for review in reviews:
        review_data = {
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
            'creation_date': review.creation_date.isoformat() if review.creation_date else None,
            'date_consumed': review.date_consumed.isoformat() if review.date_consumed else None,
            'pros': review.pros,
            'cons': review.cons,
            'genres': [genre.name for genre in review.genres]
        }
        result.append(review_data)

    return result


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

        db.session.add_all([genre1, genre2, genre3,genre4, genre5, genre6])
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
            creation_date=datetime(2023, 1, 1),
            date_consumed=datetime(2023, 1, 2),
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
            creation_date=datetime(2023, 2, 1),
            date_consumed=datetime(2023, 2, 2),
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
            creation_date=datetime(2023, 3, 1),
            date_consumed=datetime(2023, 3, 2),
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
            creation_date=datetime(2023, 4, 1),
            date_consumed=datetime(2023, 4, 2),
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
            creation_date=datetime(2023, 5, 1),
            date_consumed=datetime(2023, 5, 2),
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
            creation_date=datetime(2023, 6, 1),
            date_consumed=datetime(2023, 6, 2),
            pros=['Very informative.'],
            cons=['Could have included more interviews.'],
            genres=[genre2, genre5]
        )

        db.session.add_all([review1, review2, review3, review4, review5, review6])
        db.session.commit()

        print('Example reviews and genres created successfully.', file=sys.stderr)

    except IntegrityError:
        db.session.rollback()
        print('Error: Could not create example reviews and genres. There might be a conflict with existing data.',file=sys.stderr)
