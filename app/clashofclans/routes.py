from datetime import datetime, timedelta
import sys
from zoneinfo import ZoneInfo
import concurrent
from flask import jsonify, request, current_app
import requests
from sqlalchemy import and_
from app.clashofclans import bp
from app.extensions import db, limiter
from config import Config
from app.models.clashofclans import CocPlayerDataSchema, CocPlayerData, CocPlayer
from dateutil import parser

BASE_URL = "https://cocproxy.royaleapi.dev/v1"
headers = {
    "Authorization": f"Bearer {Config.COC_BEARER_TOKEN}",
}


@bp.route('set_player_data', methods=['POST'])
@limiter.limit('4/minute', override_defaults=True)
def set_player_data():
    '''
    Logs player data of a given clan
    '''
    post_body = request.json

    if 'password' not in post_body:
            return jsonify({"success": False, 'error': 'password not provided'}), 400
    if post_body['password'] != Config.PARKING_POST_PASSWORD:
            return jsonify({"success": False, 'error': 'incorrect password'}), 400


    # Fetch clan data
    clan_response = requests.get(f"{BASE_URL}/clans/%23220QP2GGU", headers=headers)

    if clan_response.status_code != 200:
        return jsonify({"success": False, "error": clan_response.json().get("message")}), clan_response.status_code

    clan_data = clan_response.json()
    player_list = [player.get("tag") for player in clan_data["memberList"]]

    for player in clan_data["memberList"]:
        tag = player["tag"]
        name = player["name"]

        existing_player = CocPlayer.query.get(tag)

        if existing_player:
            if existing_player.name != name:
                existing_player.name = name
        else:
            new_player = CocPlayer(tag=tag, name=name)
            db.session.add(new_player)

    # Commit after processing all players
    db.session.commit()


    # Get the current Flask app context
    app = current_app._get_current_object()  # Extract actual app instance

    def process_player(tag, app):
        with app.app_context():  # Ensure Flask context is available
            
            # Create a new database session for this thread
            session = db.sessionmaker(bind=db.engine)()

            try:

                url = f"{BASE_URL}/players/{tag.replace('#', '%23')}"
                player_response = requests.get(url, headers=headers)

                if player_response.status_code != 200:
                    return None

                data = player_response.json()
                schema = CocPlayerDataSchema()
                player_data = schema.load(data)
                player_data.timestamp = datetime.now(tz=ZoneInfo("UTC"))

                session.add(player_data)
                session.commit()
                # print(f"committed {tag}", file=sys.stderr)
                return tag  # Return tag after processing
            except Exception as e:
                session.rollback()
                print(f"Error processing {tag}: {str(e)}", file=sys.stderr)
                return None
            finally:
                session.close()  # Ensure the session is closed properly

    with concurrent.futures.ThreadPoolExecutor() as executor:
        # Submit tasks for each player in parallel, passing the app instance
        futures = [executor.submit(process_player, tag, app) for tag in player_list]

        # Wait for all futures to complete and handle the results
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result is None:
                print(f"Failed to commit data for a player.", file=sys.stderr)
            else:
                print(f"Successfully committed data for {result}", file=sys.stderr)

    return jsonify({"success": True}), 201


@bp.route('/player_data/<string:tag>', methods=['GET'])
@limiter.limit('15/minute', override_defaults=True)
def get_player_data(tag):
    '''
    Retrieve player data by tag.
    Optionally filter by start and end with timezone support.
    If no dates are provided, fetch records from one year ago until now.
    '''
    
    try:
        start_date = request.args.get('start')
        end_date = request.args.get('end')

        if start_date:
            start_date = parser.parse(start_date)
        else:
            start_date = datetime.now(ZoneInfo("UTC")) - timedelta(days=365)  # Default: 1 year ago (UTC)

        if end_date:
            end_date = parser.parse(end_date)  # Parses timezone if provided
        else:
            end_date = datetime.now(ZoneInfo("UTC"))  # Default: now (UTC)

    except ValueError:
        return jsonify({"error": "Invalid datetime format. Use ISO 8601 (YYYY-MM-DDTHH:MM:SS±HH:MM)"}), 400
    
    player = CocPlayer.query.get(tag)

    # Check if player exists in the DB
    if not player:
        return jsonify({"error": f"No data exists for player {tag}"}), 404

    # Query the database
    player_data = CocPlayerData.query.filter(
        and_(
            CocPlayerData.tag == tag,
            CocPlayerData.timestamp >= start_date.astimezone(ZoneInfo("UTC")),
            CocPlayerData.timestamp <= end_date.astimezone(ZoneInfo("UTC"))
        )
    ).order_by(CocPlayerData.timestamp.asc()).all()

    # Serialize results
    schema = CocPlayerDataSchema(many=True)
    return jsonify({"name": player.name, "tag": player.tag,"history": schema.dump(player_data)}), 200



