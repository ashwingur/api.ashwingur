from collections import defaultdict
import concurrent.futures
from datetime import datetime, timedelta
import sys
from zoneinfo import ZoneInfo
from flask import jsonify, request, current_app
from sqlalchemy import and_, func, or_
from app.clashofclans import bp
from app.extensions import db, limiter, get_real_ip
from config import Config
from app.models.clashofclans import CocPlayerDataSchema, CocPlayerData, CocPlayer, CocPlayerSchema, CocPlayerWarHistory, CocPlayerWarHistorySchema
from dateutil import parser
from app.clashofclans.coc_api import BASE_URL, coc_get, encode_tag, error_message, normalise_tag
from app.clashofclans.war import cwl_war_tags, parse_coc_time, pick_wars, summarise_clan, summarise_cwl


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
    clan_response = coc_get("/clans/%23220QP2GGU")

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
                player_response = coc_get(url)

                if player_response.status_code != 200:
                    return None
                
                player = session.query(CocPlayer).get(tag)
                if player_response.json().get("clan"):
                    player.clan_tag = player_response.json()["clan"]["tag"]
                    player.clan_name = player_response.json()["clan"]["name"]
                else:
                    player.clan_tag = None
                    player.clan_name = None
                    

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

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
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

@bp.route('update_player_activity', methods=['POST'])
@limiter.limit('1/15seconds;4/minute', override_defaults=True)
def update_player_activity():
    all_players = CocPlayer.query.all()
    # Get the current Flask app context
    app = current_app._get_current_object()  # Extract actual app instance

    def process_player(tag, app):
        with app.app_context():  # Ensure Flask context is available
            
            # Create a new database session for this thread
            session = db.sessionmaker(bind=db.engine)()

            try:

                url = f"{BASE_URL}/players/{tag.replace('#', '%23')}"
                player_response = coc_get(url)

                if player_response.status_code != 200:
                    return None
                
                player = session.query(CocPlayer).get(tag)
                if player_response.json().get("clan"):
                    player.clan_tag = player_response.json()["clan"]["tag"]
                    player.clan_name = player_response.json()["clan"]["name"]
                else:
                    player.clan_tag = None
                    player.clan_name = None
                player.name = player_response.json()["name"]

                data = player_response.json()
                
                # Build the new activity state
                new_activity_state = {
                    "name": data.get("name"),
                    "builderBaseTrophies": data.get("builderBaseTrophies"),
                    "warPreference": data.get("warPreference"),
                    "clanCapitalContributions": data.get("clanCapitalContributions")
                }

                # Also do specific achievement changes that can indicate activity
                achievements = ["Nice and Tidy", "Gold Grab", "Elixir Escapade", 
                                "Heroic Heist", "Conqueror", "Friend in Need", 
                                "War Hero", "Clan War Wealth", "Games Champion",
                                "War League Legend", "Well Seasoned" ]
                
                for a in achievements:
                    value = next((x.get("value") for x in data.get("achievements") if x["name"] == a), None)
                    new_activity_state[a] = value
                
                # War preference will be null if player was kicked from the clan, which will be a false positive change from 'in' or 'out'
                # Therefore if war preference is null, copy it from the previous value
                if player.last_activity_state and not new_activity_state["warPreference"]:
                    new_activity_state["warPreference"] = player.last_activity_state["warPreference"]
                
                if new_activity_state != player.last_activity_state:
                    # Player made an action between the 2 states
                    player.activity_change_date = player.last_state_date
                    player.last_activity_state = new_activity_state
                
                player.last_state_date = datetime.now(ZoneInfo("UTC"))
                
                session.commit()
                return tag  # Return tag after processing
            except Exception as e:
                session.rollback()
                print(f"Error processing {tag}: {str(e)}", file=sys.stderr)
                return None
            finally:
                session.close()  # Ensure the session is closed properly

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        # Submit tasks for each player in parallel, passing the app instance
        futures = [executor.submit(process_player, p.tag, app) for p in all_players]

        # Wait for all futures to complete and handle the results
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result is None:
                print(f"Failed to commit data for a player.", file=sys.stderr)
            else:
                pass
                # print(f"Successfully committed data for {result}", file=sys.stderr)

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
    print(player.activity_change_date, file=sys.stderr)
    # Serialize results
    data_schema = CocPlayerDataSchema(many=True)
    player_schema = CocPlayerSchema()

    return jsonify({**player_schema.dump(player), "history": data_schema.dump(player_data)}), 200

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

@bp.route('/players/<string:tag>/profile', methods=['GET'])
@limiter.limit('15/minute', override_defaults=True)
def get_player_profile(tag):
    """
    Retrieves a player's ingame data
    """
    tag = tag.replace("#", "%23")
    player_response = coc_get(f"{BASE_URL}/players/{tag}")

    if player_response.status_code != 200:
        return jsonify({"success": False, "error": player_response.json().get("message")}), player_response.status_code

    return jsonify(player_response.json()), 200


@bp.route('/goldpass', methods=['GET'])
@limiter.limit('40/minute', override_defaults=True)
def gold_pass():
    gold_response = coc_get(f"{BASE_URL}/goldpass/seasons/current")

    if gold_response.status_code != 200:
        return jsonify({"success": False, "error": gold_response.json().get("message")}), gold_response.status_code

    return jsonify(gold_response.json()), 200

@bp.route('/clan/<string:tag>/currentwar', methods=['GET'])
@limiter.limit('15/minute', override_defaults=True)
def get_current_regular_war(tag):
    """
    Retrieves information about a clan's current war
    """
    tag = tag.replace("#", "%23")
    war_response = coc_get(f"{BASE_URL}/clans/{tag}/currentwar")

    if war_response.status_code != 200:
        return jsonify({"success": False, "error": war_response.json().get("message")}), war_response.status_code

    return jsonify(war_response.json()), 200

@bp.route('/clanwarleagues/wars/<string:war_tag>', methods=['GET'])
@limiter.limit('15/minute', override_defaults=True)
def get_current_CWL_war(war_tag):
    """
    Retrieves information about a CWL war
    """
    war_tag = war_tag.replace("#", "%23")
    war_response = coc_get(f"{BASE_URL}/clanwarleagues/wars/{war_tag}")

    if war_response.status_code != 200:
        return jsonify({"success": False, "error": war_response.json().get("message")}), war_response.status_code

    return jsonify(war_response.json()), 200

def _fetch_cwl_wars(leaguegroup_data):
    """Fetch every CWL war in the league group concurrently. Each war gets a `war_tag` ('#...')."""
    tags = [war_tag for _, war_tag in cwl_war_tags(leaguegroup_data)]
    if not tags:
        return []

    def fetch(war_tag):
        response = coc_get(f"/clanwarleagues/wars/{encode_tag(war_tag)}")
        if not response.ok:
            return None
        data = response.json()
        data["war_tag"] = war_tag
        return data

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        wars = [w for w in executor.map(fetch, tags) if w]
    wars.sort(key=lambda w: parse_coc_time(w.get("startTime")) or datetime.min.replace(tzinfo=ZoneInfo("UTC")))
    return wars


def fetch_war_sources(tag):
    """
    Fetch the clan's regular war, CWL league group and all CWL wars.
    Return value: (regular_war or None, regular_war_private, leaguegroup or None, cwl_wars, error, status)
    """
    encoded = encode_tag(tag)
    with concurrent.futures.ThreadPoolExecutor() as executor:
        war_future = executor.submit(coc_get, f"/clans/{encoded}/currentwar")
        leaguegroup_future = executor.submit(coc_get, f"/clans/{encoded}/currentwar/leaguegroup")
        war_response, leaguegroup_response = war_future.result(), leaguegroup_future.result()

    # League group is 404 outside of CWL; current war is 403 when the war log is private
    if not leaguegroup_response.ok and leaguegroup_response.status_code != 404:
        return None, False, None, [], error_message(leaguegroup_response), leaguegroup_response.status_code
    if not war_response.ok and war_response.status_code != 403:
        return None, False, None, [], error_message(war_response), war_response.status_code

    regular_war = war_response.json() if war_response.ok else None
    leaguegroup = leaguegroup_response.json() if leaguegroup_response.ok else None
    cwl_wars = _fetch_cwl_wars(leaguegroup) if leaguegroup else []
    return regular_war, war_response.status_code == 403, leaguegroup, cwl_wars, None, 200


def current_active_war(tag):
    """
    Retrieves the current active war of the clan, whether it is a regular or CWL war.
    The returned war is oriented so `clan` is the requested clan, and has `isCwl` set.
    Return value: war_data, error_message, status_code
    """
    clan_tag = normalise_tag(tag)
    regular_war, private, _, cwl_wars, error, status = fetch_war_sources(clan_tag)
    if error:
        return None, error, status

    active_war, _ = pick_wars(clan_tag, regular_war, cwl_wars)
    if active_war:
        if active_war.get("war_tag"):
            # Keep the historical URL-encoded format ('%23...') that API consumers already rely on
            active_war["war_tag"] = encode_tag(active_war["war_tag"])
        return active_war, None, 200
    if private:
        return None, "Private war log", 404
    return None, "No war found", 404

@bp.route('/clan/<string:tag>/activewar', methods=['GET'])
@limiter.limit('15/minute', override_defaults=True)
def get_curent_active_war(tag):
    data, error, status = current_active_war(tag)

    if error or not data:
        return jsonify({"success": False, "error": error}), status
    
    return jsonify(data), 200

@bp.route('/clan/<string:clan_tag>/warattackhistory', methods=['GET'])
@limiter.limit('20/minute', override_defaults=True)
def get_war_attack_history(clan_tag):
    """
     Retrieves war attack history of players for a given clan
     Players can be specified by comma separated player_tags or player_names
     If no names or tags are provided, it returns all the data for the timeframe.
     A start and end date can be provided to override the default past 1 year timeframe
    """
    # Retrieves war attack history for a given clan and list of players (by tag or name)
    player_tags_param = request.args.get("player_tags", "")
    player_names_param = request.args.get("player_names", "")

    player_tags = [tag.strip() for tag in player_tags_param.split(",") if tag.strip()]
    player_names = [name.strip() for name in player_names_param.split(",") if name.strip()]

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
            # Default now + 2 days so we also include ongoing wars
            end_date = datetime.now(ZoneInfo("UTC")) + timedelta(days=2)

    except ValueError:
        return jsonify({"error": "Invalid datetime format. Use ISO 8601 (YYYY-MM-DDTHH:MM:SS±HH:MM)"}), 400
    
    query = CocPlayerWarHistory.query.join(CocPlayer).filter(
        CocPlayer.clan_tag == clan_tag,
        CocPlayerWarHistory.preparation_start_timestamp >= start_date,
        CocPlayerWarHistory.preparation_start_timestamp <= end_date
    )

    # Filter by player tags or names
    if player_tags or player_names:
        player_filters = []
        if player_tags:
            player_filters.append(CocPlayer.tag.in_(player_tags))
        for name in player_names:
            search_term_processed = name # Only lowercase the search term
            player_name_processed = func.unaccent(func.lower(CocPlayer.name)) # Only lowercase the database column
            player_filters.append(player_name_processed.ilike(f"%{search_term_processed}%"))
        query = query.filter(or_(*player_filters))

    # Order by latest date (war_end_timestamp) and then attack_order
    query = query.order_by(
        CocPlayerWarHistory.war_end_timestamp.desc(),
        CocPlayerWarHistory.attack_order.desc()
    )

    war_history_records = query.all()
    schema = CocPlayerWarHistorySchema()

    # Group by each player
    player_war_history = defaultdict(list)

    for attack in war_history_records:
        player_tag = attack.tag
        player_name = attack.player.name
        regular_war_count = attack.player.regular_wars
        cwl_war_count = attack.player.cwl_wars

        player_war_history[(player_tag, player_name, regular_war_count, cwl_war_count)].append(schema.dump(attack))
    
    final_response = [{
        "tag": tag,
        "name": name,
        "all_time_regular_wars": regular_wars,
        "all_time_cwl_wars": cwl_wars,
        "attacks": attacks
    } for (tag, name, regular_wars, cwl_wars), attacks in player_war_history.items()]

    return jsonify(final_response), 200


@bp.route('/clan/<string:tag>/update_war_history', methods=['POST'])
@limiter.limit('5/minute', override_defaults=True)
def update_war_history(tag):
    post_body = request.get_json(silent=True) or {}
    if 'password' not in post_body:
            return jsonify({"success": False, 'error': 'password not provided'}), 400
    if post_body['password'] != Config.PARKING_POST_PASSWORD:
            return jsonify({"success": False, 'error': 'incorrect password'}), 400

    clan_tag = normalise_tag(tag)
    regular_war, private, _, cwl_wars, error, status = fetch_war_sources(clan_tag)
    if error:
        return jsonify({"success": False, "error": error}), status

    # Record every war we are part of that has attacks: the active war, plus every CWL round
    # (a CWL round ends at the same moment the next starts, so only looking at the active
    # war would drop attacks made in the last minutes of each round).
    wars = []
    active_war, _ = pick_wars(clan_tag, regular_war, [])
    if active_war:
        wars.append(active_war)
    for cwl_war in cwl_wars:
        oriented, _ = pick_wars(clan_tag, None, [cwl_war])  # orients + tags isCwl, None if not ours
        if oriented:
            wars.append(oriented)

    wars = [w for w in wars if w.get("state") in ("inWar", "warEnded")]
    if not wars:
        if not active_war and not cwl_wars:
            return jsonify({"success": False, "error": "Private war log" if private else "No war found"}), 404
        # No attacks to process
        return jsonify({"success": True})

    # Oldest first so per-player war counters move forward in order
    wars.sort(key=lambda w: parse_coc_time(w.get("preparationStartTime")) or datetime.min.replace(tzinfo=ZoneInfo("UTC")))
    for war in wars:
        _record_war_attacks(war)

    return jsonify({"success": True})


def _record_war_attacks(data):
    war_preparation_start = parse_coc_time(data.get("preparationStartTime"))
    war_start = parse_coc_time(data.get("startTime"))
    war_end = parse_coc_time(data.get("endTime"))
    if not (war_preparation_start and war_start and war_end):
        print(f"Skipping war with missing timestamps: {data.get('war_tag')}", file=sys.stderr)
        return

    is_cwl = data["isCwl"]
    defenders = {p["tag"]: p for p in (data.get("opponent") or {}).get("members") or []}

    for member in (data.get("clan") or {}).get("members") or []:
        player_tag = member["tag"]
        town_hall = member.get("townhallLevel")
        map_position = member.get("mapPosition")

        # increment the war count of this player if not already done
        player = db.session.query(CocPlayer).filter_by(tag=player_tag).first()
        if player:
            if is_cwl:
                if not player.last_cwl_war_date or player.last_cwl_war_date < war_preparation_start:
                    player.last_cwl_war_date = war_preparation_start
                    player.cwl_wars = (player.cwl_wars or 0) + 1
                    db.session.commit()
            else:
                if not player.last_regular_war_date or player.last_regular_war_date < war_preparation_start:
                    player.last_regular_war_date = war_preparation_start
                    player.regular_wars = (player.regular_wars or 0) + 1
                    db.session.commit()

        for attack in member.get("attacks") or []:
            attack_order = attack["order"]
            defender_tag = attack["defenderTag"]

            existing_entry = db.session.query(CocPlayerWarHistory).filter_by(
                preparation_start_timestamp=war_preparation_start,
                attack_order=attack_order
            ).first()

            if existing_entry:
                continue

            # Need to find additional defender information
            defender = defenders.get(defender_tag)
            if not defender:
                print(f"Defender {defender_tag} not found in war {data.get('war_tag')}", file=sys.stderr)
                continue

            new_entry = CocPlayerWarHistory(
                war_end_timestamp=war_end,
                tag=player_tag,
                attacker_townhall=town_hall,
                map_position=map_position,
                defender_townhall=defender.get("townhallLevel"),
                defender_tag=defender_tag,
                defender_map_position=defender.get("mapPosition"),
                destruction_percentage=attack["destructionPercentage"],
                duration=attack["duration"],
                stars=attack["stars"],
                attack_order=attack_order,
                is_cwl=is_cwl,
                preparation_start_timestamp=war_preparation_start,
                start_timestamp=war_start
            )

            try:
                db.session.add(new_entry)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"Failed to save attack {attack_order} of {player_tag}: {e}", file=sys.stderr)

@bp.route('/clan/<string:tag>/warlog', methods=['GET'])
@limiter.limit('15/minute', override_defaults=True)
def get_war_log(tag):
    """
    Retrieves a clan's war log
    """
    tag = tag.replace("#", "%23")
    params = {}
    if request.args.get('limit'):
        try:
            params["limit"] = max(1, min(int(request.args['limit']), 100))
        except ValueError:
            return jsonify({"success": False, "error": "limit must be an integer"}), 400
    war_log_response = coc_get(f"{BASE_URL}/clans/{tag}/warlog", params=params or None)

    if war_log_response.status_code == 403:
        return jsonify({"success": False, "error": "Private war log"}), war_log_response.status_code
    if war_log_response.status_code != 200:
        return jsonify({"success": False, "error": war_log_response.json().get("message")}), war_log_response.status_code

    return jsonify(war_log_response.json()), 200

@bp.route('/clan/<string:tag>/warboard', methods=['GET'])
@limiter.limit('30/minute', override_defaults=True)
def get_war_board(tag):
    """
    Everything needed to render a live war board in one call:
      clan              - summary of the requested clan (record, streak, league, badge)
      war               - the most relevant war (battle day > preparation > ended; regular or CWL),
                          oriented so `clan` is the requested clan, with isCwl / cwl_round / attacksPerMember
      opponent_clan     - summary of the opponent clan (record, streak) or null
      recent_ended_war  - latest ended war that isn't `war` (e.g. the CWL round that just finished) or null
      cwl               - CWL group standings + our rounds, or null outside CWL
      last_war          - most recent war log entry (only when there is no war to show), or null
      war_log_private   - true if the clan's war log is private
    """
    clan_tag = normalise_tag(tag)
    encoded = encode_tag(clan_tag)

    with concurrent.futures.ThreadPoolExecutor() as executor:
        clan_future = executor.submit(coc_get, f"/clans/{encoded}")
        sources_future = executor.submit(fetch_war_sources, clan_tag)
        clan_response = clan_future.result()
        regular_war, private, leaguegroup, cwl_wars, error, status = sources_future.result()

    if not clan_response.ok:
        return jsonify({"success": False, "error": error_message(clan_response)}), clan_response.status_code
    if error:
        return jsonify({"success": False, "error": error}), status

    clan = clan_response.json()
    war, recent_ended_war = pick_wars(clan_tag, regular_war, cwl_wars)

    cwl = summarise_cwl(leaguegroup, cwl_wars, clan_tag, war.get("war_tag") if war else None) if leaguegroup else None
    if cwl:
        cwl["league"] = (clan.get("warLeague") or {}).get("name")
        if not cwl["rounds"] and cwl["state"] not in ("preparation", "inWar"):
            cwl = None  # Stale group from an old season with none of our wars

    for w in (war, recent_ended_war):
        if not w:
            continue
        w.setdefault("attacksPerMember", 1 if w["isCwl"] else 2)
        if w["isCwl"] and cwl:
            w["cwl_round"] = next((r["round"] for r in cwl["rounds"] if r["war_tag"] == w.get("war_tag")), None)

    opponent_clan = None
    if war and (war.get("opponent") or {}).get("tag"):
        opponent_response = coc_get(f"/clans/{encode_tag(war['opponent']['tag'])}")
        if opponent_response.ok:
            opponent_clan = summarise_clan(opponent_response.json())

    last_war = None
    if not war and clan.get("isWarLogPublic"):
        war_log_response = coc_get(f"/clans/{encoded}/warlog", params={"limit": 1})
        if war_log_response.ok:
            items = war_log_response.json().get("items") or []
            last_war = items[0] if items else None

    return jsonify({
        "clan": summarise_clan(clan),
        "war": war,
        "opponent_clan": opponent_clan,
        "recent_ended_war": recent_ended_war,
        "cwl": cwl,
        "last_war": last_war,
        "war_log_private": private,
    }), 200


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
        return coc_get(url)

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(fetch, url) for url in [clan_url, capital_raid, war_url, leaguegroup_url]]
        clan_response, capital_raid_response, war_response, leaguegroup_response = [f.result() for f in futures]
    

    if not clan_response.ok:
        return jsonify({"success": False, "error": error_message(clan_response)}), clan_response.status_code
    if not capital_raid_response.ok:
        return jsonify({"success": False, "error": error_message(capital_raid_response)}), capital_raid_response.status_code
    if not war_response.ok and war_response.status_code != 403:
        return jsonify({"success": False, "error": error_message(war_response)}), war_response.status_code
    if not leaguegroup_response.ok and leaguegroup_response.status_code != 404:
        return jsonify({"success": False, "error": error_message(leaguegroup_response)}), leaguegroup_response.status_code
    # League group can be 404 if CWL is not currently active
    # Current war is 403 if war log is not private

    if leaguegroup_response.status_code == 404:
        leaguegroup_data = None
    else:
        leaguegroup_data = leaguegroup_response.json()
    
    # If leaguegroup exists then fetch all CWL wars (sorted by start time)
    cwl_wars = None
    if leaguegroup_data:
        cwl_wars = _fetch_cwl_wars(leaguegroup_data)
        for war in cwl_wars:
            # Keep the historical URL-encoded format ('%23...') that API consumers already rely on
            war["war_tag"] = encode_tag(war["war_tag"])

    clan = clan_response.json()

    capital_data = capital_raid_response.json().get("items") or []
    if len(capital_data) == 1:
        capital_data = capital_data[0]
    else:
        capital_data = None

    war_data = war_response.json() if war_response.status_code != 403 else None

    clan["war"] = war_data
    clan["cwl_wars"] = cwl_wars
    clan["capital_raid_data"] = capital_data
    

    for member in clan["memberList"]:
        # Getting raid contributions for current clan capital raid
        if capital_data and capital_data.get("state") == "ongoing":
            capital_player = next((p for p in capital_data.get("members") or [] if p["tag"] == member["tag"]), None)
            if capital_player:
                member["clan_capital"] = {
                    "attacks": capital_player.get("attacks", 0),
                    "capitalResourcesLooted": capital_player.get("capitalResourcesLooted", 0)
                }
            else:
                member["clan_capital"] = None # We dont want players who haven't opened it to show up
        else:
            member["clan_capital"] = None
        
        # Getting current normal war attacks for ongoing war
        if war_data and war_data.get("state") == "inWar":
            war_player = next((p for p in war_data["clan"].get("members") or [] if p["tag"] == member["tag"]), None)

            if war_player:
                member["war"] = {
                    "attacks": len(war_player.get("attacks", []))
                }
            else:
                member["war"] = None
        else:
            member["war"] = None

        
        # Go through each cwl to aggregate each player's stats in this clan
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

                war_player = next((p for p in warMembers or [] if p["tag"] == member["tag"]), None)

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
                    
                    if (war_player.get("opponentAttacks") or 0) > 0:
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
                war_tag = war.get("war_tag").replace("%23","#")
                if war.get("opponent").get("tag") == tag:
                    # Make our clan the friendly one
                    opponent = war.get("clan").get("name")
                    opponent_tag = war.get("clan").get("tag")
                    opponent_attacks = war.get("clan").get("attacks")
                    opponent_stars = war.get("clan").get("stars")
                    opponent_destruction_percentage = war.get("clan").get("destructionPercentage")
                    clan_name = war.get("opponent").get("name")
                    clan_tag = tag
                    clan_attacks = war.get("opponent").get("attacks")
                    clan_stars = war.get("opponent").get("stars")
                    clan_destruction_percentage = war.get("opponent").get("destructionPercentage")
                else:
                    opponent = war.get("opponent").get("name")
                    opponent_tag = war.get("opponent").get("tag")
                    opponent_attacks = war.get("opponent").get("attacks")
                    opponent_stars = war.get("opponent").get("stars")
                    opponent_destruction_percentage = war.get("opponent").get("destructionPercentage")
                    clan_name = war.get("clan").get("name")
                    clan_tag = war.get("clan").get("tag")  
                    clan_attacks = war.get("clan").get("attacks")
                    clan_stars = war.get("clan").get("stars")
                    clan_destruction_percentage = war.get("clan").get("destructionPercentage")                                      

                cwl_war_rounds.append({
                    "war_tag": war_tag,
                    "clan": clan_name,
                    "clan_tag": clan_tag,
                    "clan_attacks": clan_attacks,
                    "clan_stars": clan_stars,
                    "clan_destruction_percentage": clan_destruction_percentage,
                    "opponent": opponent,
                    "opponent_tag": opponent_tag,
                    "opponent_attacks": opponent_attacks,
                    "opponent_stars": opponent_stars,
                    "opponent_destruction_percentage": opponent_destruction_percentage,
                    "state": war.get("state"),
                    "team_size": war.get("teamSize"),
                })
            clan["cwl_war_rounds"] = cwl_war_rounds
        else:
            clan["cwl_war_rounds"] = None

    return jsonify(clan), 200


@bp.route('/clan/<string:tag>/capitalraidseasons', methods=['GET'])
@limiter.limit('4/second', override_defaults=True)
def get_capital_raid_seasons(tag):
    tag = tag.replace("#", "%23")
    try:
        limit = int(request.args.get('limit', default=10))
        if limit < 1 or limit > 20:
            raise ValueError
    except ValueError:
        return jsonify({"success": False, "error": f"limit must be an integer between 1-20, but received '{limit}'"}), 400
    after = request.args.get('after')

    params = {
        "limit": limit
    }
    if after:
        params["after"] = after

    capital_raid_response = coc_get(f"{BASE_URL}/clans/{tag}/capitalraidseasons", params=params)

    if capital_raid_response.status_code != 200:
        return jsonify({"success": False, "error": capital_raid_response.json().get("reason")}), capital_raid_response.status_code

    return jsonify(capital_raid_response.json()), 200

