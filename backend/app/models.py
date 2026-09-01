from datetime import datetime

from sqlalchemy import ForeignKey, JSON, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class League(Base):
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20))
    platform_league_id: Mapped[str] = mapped_column(String(64))
    season: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32))
    roster_positions: Mapped[list[str]] = mapped_column(JSON, default=list)
    scoring_settings: Mapped[dict] = mapped_column(JSON, default=dict)
    current_week: Mapped[int] = mapped_column(default=1)
    playoff_teams: Mapped[int] = mapped_column(default=6)
    playoff_week_start: Mapped[int] = mapped_column(default=15)
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    teams: Mapped[list["Team"]] = relationship(back_populates="league")
    matchups: Mapped[list["Matchup"]] = relationship(back_populates="league")
    connections: Mapped[list["LeagueConnection"]] = relationship(back_populates="league")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"))
    platform_roster_id: Mapped[str] = mapped_column(String(64))
    platform_owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255))
    wins: Mapped[int] = mapped_column(default=0)
    losses: Mapped[int] = mapped_column(default=0)
    ties: Mapped[int] = mapped_column(default=0)
    points_for: Mapped[float] = mapped_column(default=0)
    points_against: Mapped[float] = mapped_column(default=0)

    league: Mapped["League"] = relationship(back_populates="teams")
    weekly_scores: Mapped[list["WeeklyScore"]] = relationship(back_populates="team")
    roster_slots: Mapped[list["RosterSlot"]] = relationship(back_populates="team")


class Matchup(Base):
    __tablename__ = "matchups"

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"))
    week: Mapped[int]
    platform_matchup_id: Mapped[int]

    league: Mapped["League"] = relationship(back_populates="matchups")
    weekly_scores: Mapped[list["WeeklyScore"]] = relationship(back_populates="matchup")


class WeeklyScore(Base):
    __tablename__ = "weekly_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    matchup_id: Mapped[int] = mapped_column(ForeignKey("matchups.id"))
    week: Mapped[int]
    points: Mapped[float]

    team: Mapped["Team"] = relationship(back_populates="weekly_scores")
    matchup: Mapped["Matchup"] = relationship(back_populates="weekly_scores")


class RosterSlot(Base):
    __tablename__ = "roster_slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    week: Mapped[int]
    platform_player_id: Mapped[str] = mapped_column(String(32))
    is_starter: Mapped[bool]
    points: Mapped[float] = mapped_column(default=0)

    team: Mapped["Team"] = relationship(back_populates="roster_slots")


class Player(Base):
    __tablename__ = "players"

    platform: Mapped[str] = mapped_column(String(20), primary_key=True)
    platform_player_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    position: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(255))
    gsis_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    team: Mapped[str | None] = mapped_column(String(8), nullable=True)
    injury_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class ProjectionRecord(Base):
    __tablename__ = "projection_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"))
    platform_player_id: Mapped[str] = mapped_column(String(32))
    week: Mapped[int]
    source: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(255))
    position: Mapped[str] = mapped_column(String(16))
    projected_points: Mapped[float]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class PlayerUsageStats(Base):
    __tablename__ = "player_usage_stats"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20))
    platform_player_id: Mapped[str] = mapped_column(String(32))
    season: Mapped[str] = mapped_column(String(8))
    week: Mapped[int]
    targets: Mapped[int | None] = mapped_column(nullable=True)
    target_share: Mapped[float | None] = mapped_column(nullable=True)
    carries: Mapped[int | None] = mapped_column(nullable=True)
    snap_share: Mapped[float | None] = mapped_column(nullable=True)
    red_zone_opportunities: Mapped[int | None] = mapped_column(nullable=True)
    fantasy_points_ppr: Mapped[float | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class TeamDefenseStrength(Base):
    __tablename__ = "team_defense_strength"

    id: Mapped[int] = mapped_column(primary_key=True)
    season: Mapped[str] = mapped_column(String(8))
    team: Mapped[str] = mapped_column(String(8))
    position: Mapped[str] = mapped_column(String(16))
    points_allowed_avg: Mapped[float]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class TeamMatchup(Base):
    __tablename__ = "team_matchups"

    id: Mapped[int] = mapped_column(primary_key=True)
    season: Mapped[str] = mapped_column(String(8))
    week: Mapped[int]
    team: Mapped[str] = mapped_column(String(8))
    opponent: Mapped[str] = mapped_column(String(8))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class PositionVolatilityPrior(Base):
    __tablename__ = "position_volatility_priors"

    id: Mapped[int] = mapped_column(primary_key=True)
    season: Mapped[str] = mapped_column(String(8))
    position: Mapped[str] = mapped_column(String(16))
    low_ratio: Mapped[float]
    high_ratio: Mapped[float]
    sample_size: Mapped[int]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class PlayerSeasonBaseline(Base):
    __tablename__ = "player_season_baselines"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20))
    platform_player_id: Mapped[str] = mapped_column(String(32))
    season: Mapped[str] = mapped_column(String(8))
    team: Mapped[str | None] = mapped_column(String(8), nullable=True)
    target_share: Mapped[float | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class LeagueConnection(Base):
    __tablename__ = "league_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"))
    access_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    my_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    league: Mapped["League"] = relationship(back_populates="connections")
