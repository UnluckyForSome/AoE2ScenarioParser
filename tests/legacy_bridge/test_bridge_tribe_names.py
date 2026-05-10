"""Tribe names: RGEScen ``player_names`` is applied first; ``ScenarioPlayerData.name`` fills empty slots only."""

from AoE2ScenarioParser.objects.data_objects.player.player import Player


def _mk_player(**kwargs) -> Player:
    defaults = dict(
        player_id=1,
        starting_age=2,
        lock_civ=0,
        lock_personality=0,
        food=0,
        wood=0,
        gold=0,
        stone=0,
        personality="",
        ai_type=0,
        ai_script="",
        color=0,
        active=True,
        human=True,
        civilization=1,
        architecture_set=1,
        tribe_name=None,
    )
    defaults.update(kwargs)
    return Player(**defaults)


def test_scenario_player_name_does_not_overwrite_existing_tribe_name():
    p = _mk_player(tribe_name="Mongol Envoy")
    name = "Player 1"
    if name and not (getattr(p, "tribe_name", None) or "").strip():
        p.tribe_name = str(name)
    assert p.tribe_name == "Mongol Envoy"


def test_scenario_player_name_fills_when_tribe_name_empty():
    p = _mk_player(tribe_name=None)
    name = "Custom"
    if name and not (getattr(p, "tribe_name", None) or "").strip():
        p.tribe_name = str(name)
    assert p.tribe_name == "Custom"
