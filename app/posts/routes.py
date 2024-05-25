from app.posts import bp
from flask import jsonify, make_response, request
from app.extensions import db
from app.models.post import Post

@bp.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'GET':
        return make_response(jsonify([post.serialised for post in Post.query.all()]))
    elif request.method == 'POST':
        data = request.get_json()
        print(data)
        title = data['title']
        content = data['content']
        new_post = Post(title=title, content=content)
        db.session.add(new_post)
        db.session.commit()
        return make_response(jsonify({"success": "true"}))
        

@bp.route('/categories/')
def categories():
    return "Categories"