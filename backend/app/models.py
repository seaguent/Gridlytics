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
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class LeagueConnection(Base):
    __tablename__ = "league_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"))
    access_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    league: Mapped["League"] = relationship(back_populates="connections")
