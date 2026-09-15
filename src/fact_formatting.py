"""Display helpers that preserve the distinction between unknown and known facts."""

from __future__ import annotations

from typing import Optional


def format_team_size(team_min: Optional[int], team_max: Optional[int]) -> str:
    """Format team bounds without inventing a missing minimum or maximum."""
    if team_min is not None and team_max is not None:
        if team_min == team_max:
            return f"{team_min} 人"
        return f"{team_min}—{team_max} 人"
    if team_min is not None:
        return f"至少 {team_min} 人"
    if team_max is not None:
        return f"最多 {team_max} 人"
    return "人数未明确"
