"""World class module."""
from __future__ import annotations

import logging
import random

import engine.actor
import engine.map

logger = logging.getLogger(__name__)


class World:
    """This class is used to hold everything you'll want to save between sessions."""

    player: engine.actor.Actor  # The active player actor, this might be removed from here.

    def __init__(self) -> None:
        self.map = engine.map.Map(128, 128)
        self.rng = random.Random()

    def loop(self) -> None:
        while self.player in self.map.actors:
            next_obj = self.map.schedule[0]
            next_obj.on_turn()
            if self.map.schedule and self.map.schedule[0] is next_obj:
                self.map.schedule.rotate(1)
        logger.info("Player is dead or missing!")