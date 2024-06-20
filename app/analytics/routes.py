import sys
from app.analytics import bp
from app.models.request_log import get_requests_per_bucket

@bp.route('/requests', methods=['GET'])
def get_requests():
    print(get_requests_per_bucket(), file=sys.stderr)
    return {}, 200