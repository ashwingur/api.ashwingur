from datetime import datetime
import sys

from flask import jsonify, request
import requests
from app.analytics import bp
from app.models.request_log import get_api_requests_per_bucket
from app.models.frontend_log import get_frontend_log_per_bucket, insert_frontend_log
from app.extensions import limiter
from zoneinfo import ZoneInfo
from dateutil import parser
from urllib.parse import urlparse


@bp.route('/requests', methods=['GET'])
@limiter.limit('20/minute', override_defaults=True)
def get_requests():
    if request.method == 'GET':
        params = request.args
        endpoint = params.get('endpoint', None)
        start_time_str = params.get('start_time', None)
        end_time_str = params.get('end_time', None)

        # List of allowed parameters
        allowed_params = {'endpoint', 'start_time', 'end_time'}

        # Check for unknown parameters
        unknown_params = set(params.keys()) - allowed_params
        if unknown_params:
            return jsonify({'error': f'Unknown parameters: {", ".join(unknown_params)}'}), 400

        # Parse datetime parameters
        start_time = parse_datetime(start_time_str) if start_time_str else None
        end_time = parse_datetime(end_time_str) if end_time_str else None

        if (start_time_str and start_time is None) or (end_time_str and end_time is None):
            return jsonify({'error': 'Invalid datetime format. Use YYYY-MM-DDTHH:MM:SS'}), 400

        # Determine the appropriate bucket size based on the date range
        bucket_size = determine_bucket_size(start_time, end_time)

        result = get_api_requests_per_bucket(
            bucket_size, endpoint, start_time, end_time)
        return jsonify(result), 200


@bp.route('/frontend_visits', methods=['GET', 'POST'])
@limiter.limit('60/minute', override_defaults=True)
def frontend_visits():
    if request.method == 'GET':
        params = request.args
        route = params.get('route', None)
        start_time_str = params.get('start_time', None)
        end_time_str = params.get('end_time', None)

        # List of allowed parameters
        allowed_params = {'route', 'start_time', 'end_time'}

        # Check for unknown parameters
        unknown_params = set(params.keys()) - allowed_params
        if unknown_params:
            return jsonify({'error': f'Unknown parameters: {", ".join(unknown_params)}'}), 400

        # Parse datetime parameters
        start_time = parse_datetime(start_time_str) if start_time_str else None
        end_time = parse_datetime(end_time_str) if end_time_str else None

        if (start_time_str and start_time is None) or (end_time_str and end_time is None):
            return jsonify({'error': f'Invalid ISO 8601datetime format. Use YYYY-MM-DDTHH:MM:SS+HH:MM. start_time: {start_time}, end_time: {end_time}'}), 400

        # Determine the appropriate bucket size based on the date range
        bucket_size = determine_bucket_size(start_time, end_time)

        result = get_frontend_log_per_bucket(
            bucket_size, route, start_time, end_time)
        return jsonify(result), 200
    elif request.method == 'POST':
        data = request.json
        if 'route' not in data:
            return jsonify({"success": False, 'error': 'route not provided'}), 400

        # Check if the route is valid for security purposes (so we dont get any bad words in a nonexistent route)
        route = data['route']
        if not check_url_validity(f'https://www.ashwingur.com/{route}'):
            route = "404"

        insert_frontend_log(sanitise_route(route))
        return jsonify({'success': True}), 201


def sanitise_route(route: str) -> str:
    # Parse the URL to get the path
    parsed_url = urlparse(route)
    path = parsed_url.path

    # Sanitise the route based on your specified conditions
    if '/ClashOfClans/player/' in path:
        return '/ClashOfClans/player'
    elif '/ClashOfClans/clan/' in path:
        return '/ClashOfClans/clan'
    elif '/MediaReviewsV2/Edit' in path or '/MediaReviews/Edit' in path:
        return '/MediaReviews/Edit'
    elif '/MediaReviewsV2' in path:
        return '/MediaReviewsV2'
    elif '/MediaReviews' in path:
        return '/MediaReviews'
    elif '/LiveCarPark' in path:
        return '/LiveCarPark'
    return path


def check_url_validity(url: str) -> bool:
    try:
        response = requests.get(url)
        # Check if the status code is valid
        if 200 <= response.status_code < 300:
            return True
        else:
            return False
    except requests.exceptions.RequestException as e:
        return False


def parse_datetime(date_str: str):
    try:
        # Replace space with plus to handle potential URL encoding issues
        date_str = date_str.replace(" ", "+")
        # Parse the datetime string
        dt = parser.parse(date_str)
        # If the datetime object is not timezone-aware, set it to UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt
    except ValueError:
        return None


def determine_bucket_size(start_time: datetime, end_time: datetime):
    if not start_time or not end_time:
        return '1 day'  # Default bucket size if no dates are provided

    date_diff = (end_time - start_time).days
    seconds_difference = (end_time - start_time).total_seconds()

    if seconds_difference <= 7200:
        return '1 minute'
    elif seconds_difference <= 43200:
        return '5 minutes'

    if date_diff <= 1:
        return '15 minutes'
    elif date_diff <= 7:
        return '1 hour'
    elif date_diff <= 31:
        return '4 hours'
    else:
        return '1 day'
