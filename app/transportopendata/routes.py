import sys
from flask import jsonify
import requests
from app.transportopendata import bp
from app.extensions import db, roles_required, limiter
from config import Config


@bp.route('', methods=['GET'])
@limiter.limit('40/minute', override_defaults=True)
def test():
    # Load API key from environment variable
    print(vars(Config), file=sys.stderr)
    api_key = Config.OPEN_DATA_TOKEN
    print(api_key, file=sys.stderr)

    if not api_key:
        return jsonify({"error": "API key is missing"}), 500

    # API URL
    url = "https://api.transport.nsw.gov.au/v1/carpark"

    # Headers
    headers = {
        "Authorization": f"apikey {api_key}",
    }

    # Make the GET request
    response = requests.get(url, headers=headers)

    # Check if the request was successful
    if response.status_code == 200:
        return jsonify(response.json())  # Return the JSON response
    else:
        return jsonify({"error": f"Request failed with status {response.status_code}", "details": response.text}), response.status_code
