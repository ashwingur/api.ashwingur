from app.extensions import db

class Post(db.Model):
    __tablename__ = "post"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150))
    content = db.Column(db.Text)

    @property
    def serialised(self):
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content
        }

    def __repr__(self):
        return f'<Post "{self.title}">'