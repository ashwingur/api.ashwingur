import concurrent.futures
from datetime import datetime, timedelta
import sys
from zoneinfo import ZoneInfo
import concurrent
from flask import jsonify, request, current_app
import requests
from sqlalchemy import and_
from app.clashofclans import bp
from app.extensions import db, limiter, get_real_ip
from config import Config
from app.models.clashofclans import CocPlayerDataSchema, CocPlayerData, CocPlayer, CocPlayerSchema
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

    for player in clan_data["memberList"]:
        tag = player["tag"]
        name = player["name"]

        existing_player = CocPlayer.query.get(tag)

        if existing_player:
            if existing_player.name != name:
                existing_player.name = name
        else:
            new_player = CocPlayer(tag=tag, name=name, clan_tag=clan_data["tag"], view_count=0)
            db.session.add(new_player)

    # Commit after processing all players
    db.session.commit()

    all_players = CocPlayer.query.all()


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
                
                player = session.query(CocPlayer).get(tag)
                if player_response.json().get("clan"):
                    player.clan_tag = player_response.json()["clan"]["tag"]
                    player.clan_name = player_response.json()["clan"]["name"]
                    

                data = player_response.json()
                schema = CocPlayerDataSchema()
                player_data = schema.load(data)
                player_data.timestamp = datetime.now(tz=ZoneInfo("UTC"))

                session.add(player_data)
                session.commit()
                return tag  # Return tag after processing
            except Exception as e:
                session.rollback()
                print(f"Error processing {tag}: {str(e)}", file=sys.stderr)
                return None
            finally:
                session.close()  # Ensure the session is closed properly

    with concurrent.futures.ThreadPoolExecutor() as executor:
        # Submit tasks for each player in parallel, passing the app instance
        futures = [executor.submit(process_player, p.tag, app) for p in all_players]

        # Wait for all futures to complete and handle the results
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result is None:
                print(f"Failed to commit data for a player.", file=sys.stderr)
            else:
                print(f"Successfully committed data for {result}", file=sys.stderr)

    return jsonify({"success": True}), 201


@bp.route('/player_data/<string:tag>', methods=['GET'])
@limiter.limit('30/minute', override_defaults=True)
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
    return jsonify({"name": player.name, "view_count": player.view_count, "clan_tag": player.clan_tag, "clan_name": player.clan_name, "tag": player.tag,"history": schema.dump(player_data)}), 200

@bp.route('/player_data/increment_view_count/<string:tag>', methods=['PATCH'])
@limiter.limit('1/5minute;20/day', key_func=lambda: f"{get_real_ip()}:{request.view_args.get('tag', 'UNKNOWN')}", override_defaults=True)
def increment_view_count(tag):
    player = CocPlayer.query.get(tag)
    
    if player:
        player.view_count += 1
        db.session.commit()
        
        return jsonify({"success": True}), 200
    else:
        return jsonify({"success": False, "error": "Player not found"}), 404

@bp.route('/players', methods=['GET'])
@limiter.limit('40/minute', override_defaults=True)
def get_players():
    players = CocPlayer.query.all()
    schema = CocPlayerSchema(many=True)
    return jsonify(schema.dump(players)), 200

@bp.route('/players/<string:tag>', methods=['GET'])
@limiter.limit('40/minute', override_defaults=True)
def get_player_by_tag(tag):
    player = CocPlayer.query.get(tag)

    if player is None:
        return jsonify({"error": "Player not found"}), 404

    schema = CocPlayerSchema()
    return jsonify(schema.dump(player)), 200


@bp.route('/goldpass', methods=['GET'])
@limiter.limit('40/minute', override_defaults=True)
def gold_pass():
    gold_response = requests.get(f"{BASE_URL}/goldpass/seasons/current", headers=headers)

    if gold_response.status_code != 200:
        return jsonify({"success": False, "error": gold_response.json().get("message")}), gold_response.status_code

    return jsonify(gold_response.json()), 200


@bp.route('/fullclan/<string:tag>', methods=['GET'])
@limiter.limit('15/minute', override_defaults=True)
def get_full_clan_data(tag):
    """
    Gets all relevant clan data and combines it together in the members
    Clan data, regular war, cwl war, capital raid
    """
    tag = tag.replace("#", "%23")
    clan_url = f"{BASE_URL}/clans/{tag}"
    capital_raid = f"{BASE_URL}/clans/{tag}/capitalraidseasons?limit=1"
    war_url = f"{BASE_URL}/clans/{tag}/currentwar"
    leaguegroup_url = f"{BASE_URL}/clans/{tag}/currentwar/leaguegroup"

    def fetch(url):
        return requests.get(url, headers=headers)

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(fetch, url) for url in [clan_url, capital_raid, war_url, leaguegroup_url]]
        clan_response, capital_raid_response, war_response, leaguegroup_response = [f.result() for f in futures]
    

    if not clan_response.ok:
        return jsonify({"success": False, "error": clan_response.json().get("message")}), clan_response.status_code
    if not capital_raid_response.ok:
        return jsonify({"success": False, "error": clan_response.json().get("message")}), capital_raid_response.status_code
    if not war_response.ok and war_response.status_code != 403:
        return jsonify({"success": False, "error": clan_response.json().get("message")}), capital_raid_response.status_code
    if not leaguegroup_response.ok and leaguegroup_response.status_code != 404:
        return jsonify({"success": False, "error": clan_response.json().get("message")}), leaguegroup_response.status_code
    # League group can be 404 if CWL is not currently active
    # Current war is 403 if war log is not private

    if leaguegroup_response.status_code == 404:
        leaguegroup_data = None
    else:
        leaguegroup_data = leaguegroup_response.json()
    
    # If leaguegroup exists then fetch all CWL wars
    def fetchCWLWar(url, war_tag):
        response = requests.get(url, headers=headers)
        if response.ok:
            data = response.json()
            data["war_tag"] = war_tag
            return data
        else:
            return None
    cwl_wars = None
    if leaguegroup_data:
        cwl_war_tags = []
        for r in leaguegroup_data.get("rounds"):
            for war_tag in r.get("warTags"):
                if war_tag != "#0":
                    cwl_war_tags.append(war_tag.replace("#", "%23"))
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [executor.submit(fetchCWLWar, f"{BASE_URL}/clanwarleagues/wars/{war_tag}", war_tag) for war_tag in cwl_war_tags]
            cwl_wars = [f.result() for f in futures 
                                 if f.result()]
            # Keeping it sorted in order is good
            cwl_wars.sort(key=lambda x: datetime.strptime(x["startTime"], "%Y%m%dT%H%M%S.%fZ"))
        


    clan = clan_response.json()

    capital_data = capital_raid_response.json()["items"]
    if len(capital_data) == 1:
        capital_data = capital_data[0]
    else:
        capital_data = None

    war_data = war_response.json() if war_response.status_code != 403 else None
    

    for member in clan["memberList"]:
        # Getting raid contributions for current clan capital raid
        if capital_data and capital_data.get("state") == "ongoing":
            capital_player = next((p for p in capital_data["members"] if p["tag"] == member["tag"]), None)
            if capital_player:
                member["clan_capital"] = {
                    "attacks": capital_player.get("attacks", 0),
                    "capitalResourcesLooted": capital_player.get("capitalResourcesLooted", 0)
                }
            else:
                member["clan_capital"] = {
                    "attacks": 0,
                    "capitalResourcesLooted": 0
                }
        else:
            member["clan_capital"] = None
        
        # Getting current normal war attacks for ongoing war
        if war_data and war_data.get("state") == "inWar":
            war_player = next((p for p in war_data["clan"]["members"] if p["tag"] == member["tag"]), None)

            if war_player:
                member["war"] = {
                    "attacks": len(war_player.get("attacks"))
                }
            else:
                member["war"] = None
        else:
            member["war"] = None

        
        # Go through each cwl
        tag = tag.replace("%23", "#")
        if cwl_wars:
            attacks = 0
            attack_limit = 0
            total_destruction = 0
            total_stars = 0
            total_duration = 0
            attack_todo = False
            defends = 0
            defends_stars = 0
            defends_total_destruction = 0
            defends_total_duration = 0
            for war in cwl_wars:
                # If it's preparation then skip
                if war.get("state") == "preparation":
                    continue
                # Get the members list if the requested clan is in this war
                warMembers = None
                if war.get("clan").get("tag") == tag:
                    warMembers = war.get("clan").get("members")
                elif war.get("opponent").get("tag") == tag:
                    warMembers = war.get("opponent").get("members")
                else:
                    continue

                war_player = next((p for p in warMembers if p["tag"] == member["tag"]), None)

                # War state can be inWar or warEnded
                if war_player:
                    attack_limit += 1
                    if war_player.get("attacks") and len(war_player.get("attacks")) == 1:
                        attack_info = war_player.get("attacks")[0]
                        attacks += 1
                        total_destruction += attack_info.get("destructionPercentage")
                        total_stars += attack_info.get("stars")
                        total_duration += attack_info.get("duration")
                    elif war.get("state") == "inWar":
                        attack_todo = True
                    
                    if war_player.get("opponentAttacks") > 0:
                        defends += war_player.get("opponentAttacks")
                        if war_player.get("bestOpponentAttack"):
                            best_attack = war_player.get("bestOpponentAttack")
                            defends_stars += best_attack.get("stars")
                            defends_total_destruction += best_attack.get("destructionPercentage")
                            defends_total_duration += best_attack.get("duration")


                    
                    # can also do defend data
            member["cwl_war"] = {
                "attacks": attacks,
                "attack_limit": attack_limit,
                "total_destruction": total_destruction,
                "total_stars": total_stars,
                "total_duration": total_duration,
                "attack_todo": attack_todo,
                "defends": defends,
                "defends_stars": defends_stars,
                "defends_total_destruction": defends_total_destruction,
                "defends_total_duration": defends_total_duration
            }
        else:
            member["cwl_war"] = None


        # Put CWL round info for this clan (clan, opponent, war tag)
        if cwl_wars:
            cwl_war_rounds = []
            for war in cwl_wars:
                war_tag = war.get("war_tag")
                if war.get("opponent").get("tag") == tag:
                    opponent = war.get("clan").get("name")
                    opponent_tag = war.get("clan").get("tag")
                    clan_name = war.get("opponent").get("name")
                    clan_tag = tag
                else:
                    opponent = war.get("opponent").get("name")
                    opponent_tag = war.get("opponent").get("tag")
                    clan_name = war.get("clan").get("name")
                    clan_tag = war.get("clan").get("tag")                    

                # if war.get("clan").get("tag") == tag:
                #     opponent = war.get("opponent").get("name")
                #     opponent_tag = war.get("opponent").get("tag")

                # else:
                #     continue
                cwl_war_rounds.append({
                    "war_tag": war_tag,
                    "clan": clan_name,
                    "clan_tag": clan_tag,
                    "opponent": opponent,
                    "opponent_tag": opponent_tag,
                    "state": war.get("state")
                })
            clan["cwl_war_rounds"] = cwl_war_rounds
        else:
            clan["cwl_war_rounds"] = None

    return jsonify(clan), 200


