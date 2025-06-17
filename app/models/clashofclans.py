from datetime import datetime
from marshmallow import Schema, fields, EXCLUDE,post_load, pre_load
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema
from sqlalchemy.dialects.postgresql import JSONB
from app.extensions import db, psycop_conn
from zoneinfo import ZoneInfo
import re


class CocPlayerData(db.Model):
    __tablename__ = 'coc_player_historical_data'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.now(tz=ZoneInfo("UTC")))
    tag = db.Column(db.String(15), db.ForeignKey('coc_player.tag'), nullable=False)
    town_hall_level = db.Column(db.Integer, nullable=False)
    town_hall_weapon_level = db.Column(db.Integer, nullable=True)
    exp_level = db.Column(db.Integer, nullable=False)
    trophies = db.Column(db.Integer, nullable=False)
    best_trophies = db.Column(db.Integer, nullable=False)
    war_stars = db.Column(db.Integer, nullable=False)
    attack_wins = db.Column(db.Integer, nullable=False)
    defense_wins = db.Column(db.Integer, nullable=False)
    builder_hall_level = db.Column(db.Integer, nullable=False)
    builder_base_trophies = db.Column(db.Integer, nullable=False)
    best_builder_base_trophies = db.Column(db.Integer, nullable=False)
    donations = db.Column(db.Integer, nullable=False)
    donations_received = db.Column(db.Integer, nullable=False)
    clan_capital_contributions = db.Column(db.Integer, nullable=False)

    """
    [{"name" : "Barbarian", "level" : 10}]
    """
    troops = db.Column(JSONB, nullable=False)
    heroes = db.Column(JSONB, nullable=False)
    spells = db.Column(JSONB, nullable=False)
    hero_equipment = db.Column(JSONB, nullable=False)
    
    """
    [{"name" : "Shattered and Scattered", "value" : 4059}]
    """
    achievements = db.Column(JSONB, nullable=False)

    # Relationship to CocPlayer
    player = db.relationship('CocPlayer', backref=db.backref('historical_data', lazy=True))

class CocPlayerWarHistory(db.Model):
    __tablename__ = 'coc_player_war_history'

    # war_end_timestamp + attack_order will be unique
    id = db.Column(db.Integer, primary_key=True)
    war_end_timestamp = db.Column(db.DateTime(timezone=True), nullable=False)
    attack_order = db.Column(db.Integer, nullable=False)
    tag = db.Column(db.String(15), db.ForeignKey('coc_player.tag'), nullable=False)
    attacker_townhall = db.Column(db.Integer, nullable=False)
    map_position = db.Column(db.Integer, nullable=False)
    defender_townhall = db.Column(db.Integer, nullable=False)
    defender_tag = db.Column(db.String(15), nullable=False)
    defender_map_position = db.Column(db.Integer, nullable=False)
    destruction_percentage = db.Column(db.Integer, nullable=False)
    duration = db.Column(db.Integer, nullable=False)
    stars = db.Column(db.Integer, nullable=False)

    # Relationship to CocPlayer
    player = db.relationship('CocPlayer', backref=db.backref('war_history', lazy=True))

class CocPlayer(db.Model):
    __tablename__ = 'coc_player'

    tag = db.Column(db.String(15), primary_key=True, nullable=False)
    name = db.Column(db.String(20), nullable=False)
    clan_tag = db.Column(db.String(15), nullable=True)
    clan_name = db.Column(db.String(20), nullable=True)
    view_count = db.Column(db.Integer, nullable=False, default=0)
    last_activity_state = db.Column(JSONB, nullable=True)
    last_state_date = db.Column(db.DateTime(timezone=True), nullable=True)
    activity_change_date = db.Column(db.DateTime(timezone=True), nullable=True)


class PlayerDataItemLevelSchema(Schema):
    name = fields.String(required=True)
    level = fields.Integer(required=True)

    @pre_load
    def filter_fields(self, data, **kwargs):
        # Only keep 'name' and 'level'
        return {key: data[key] for key in ["name", "level"] if key in data}

class PlayerDataAchievementsSchema(Schema):
    name = fields.String(required=True)
    value = fields.Integer(required=True)

    @pre_load
    def filter_fields(self, data, **kwargs):
        # Only keep 'name' and 'value'
        return {key: data[key] for key in ["name", "value"] if key in data}

class CocPlayerDataSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = CocPlayerData
        load_instance = True  # Deserialize into SQLAlchemy model
        include_fk = True  # Include foreign keys if needed
        unknown = 'exclude'  # Ignore extra keys from API response
        sqla_session = db.session
        exclude = ("id",) # Dont serialise this

    # Automatically convert snake_case to camelCase for serialization
    def on_bind_field(self, field_name, field_obj):
        camel_case_name = re.sub(r'_([a-z])', lambda x: x.group(1).upper(), field_name)
        field_obj.data_key = camel_case_name

    troops = fields.List(fields.Nested(PlayerDataItemLevelSchema))
    heroes = fields.List(fields.Nested(PlayerDataItemLevelSchema))
    spells = fields.List(fields.Nested(PlayerDataItemLevelSchema))
    hero_equipment = fields.List(fields.Nested(PlayerDataItemLevelSchema), data_key="heroEquipment")
    achievements = fields.List(fields.Nested(PlayerDataAchievementsSchema))

class CocPlayerSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = CocPlayer
        load_instance = True
        exclude = ("last_activity_state", "last_state_date")
