"""Collections of actions."""
from __future__ import annotations

import logging
from typing import Any, Iterator, List, Optional, Tuple, Type

import tcod

import engine.actor
import engine.effects
import engine.states
import engine.tiles
import g

logger = logging.getLogger(__name__)


class Action:
    """Basic action with no targets other than the invoking actor."""

    def __init__(self, actor: engine.actor.Actor):
        super().__init__()
        self.actor = actor  # The actor performing this action.

    def perform(self) -> bool:
        """Perform the action and return its status.

        If True then this action took time to perform and will end the actors turn.
        """
        return True


class ActionWithDir(Action):
    """An action with a direction."""

    def __init__(self, actor: engine.actor.Actor, direction: Optional[Tuple[int, int]] = None, **kargs: Any):
        super().__init__(actor=actor, **kargs)  # type: ignore
        self._direction = direction

    @property
    def direction(self) -> Tuple[int, int]:
        """The direction of this action."""
        if not self._direction:
            assert self.actor is g.world.player
            state = engine.states.AskDirection()
            state.run_modal()
            self._direction = state.direction
            assert self._direction  # Todo, handle no direction given.
        return self._direction

    @property
    def target_xy(self) -> Tuple[int, int]:
        """The target position immediately in front of this action."""
        return self.actor.x + self.direction[0], self.actor.y + self.direction[1]

    def trace_line(self) -> Iterator[Tuple[int, int]]:
        """Trace a line in the provided direction until out of bounds."""
        x, y = self.actor.x, self.actor.y
        if self.direction == (0, 0):
            yield x, y  # Target self.
            return
        while True:
            x += self.direction[0]
            y += self.direction[1]
            if not g.world.map.in_bounds(x, y):
                break
            yield x, y


class ActionWithEffect(Action):
    def __init__(self, actor: engine.actor.Actor, effect: engine.effects.Effect, **kargs: Any):
        super().__init__(actor=actor, **kargs)  # type: ignore
        self.effect = effect


class IdleAction(Action):
    """Do nothing and pass a turn."""


class MoveAction(ActionWithDir):
    """Move an actor normally."""

    def perform(self) -> bool:
        assert -1 <= self.direction[0] <= 1 and -1 <= self.direction[1] <= 1, self.direction
        if self.direction == (0, 0):
            return IdleAction(self.actor).perform()
        xy = self.target_xy
        if g.world.map.is_blocked(*xy):
            return False
        # Perform the move.
        self.actor.x, self.actor.y = xy
        return True


class PlaceActor(ActionWithDir):
    """Place bomb, pratice action."""

    def __init__(self, actor: engine.actor.Actor, spawn: Type[engine.actor.Actor], **kargs: Any):
        self.spawn = spawn
        super().__init__(actor=actor, **kargs)

    def perform(self) -> bool:
        xy = self.target_xy
        if not g.world.map.is_blocked(*xy):
            g.world.map.add_actor(self.spawn(*xy))
            return True
        return False


class Beam(ActionWithDir, ActionWithEffect):
    def perform(self) -> bool:
        """Trace a line and apply effects along it until a wall is hit."""
        for xy in self.trace_line():
            if not g.world.map.tiles[xy]["transparent"]:
                break  # Hit wall.
            self.effect.apply(*xy)
        return True


class WithRange(Action):
    def __init__(self, actor: engine.actor.Actor, range: int, **kargs: Any):
        self.range = range
        super().__init__(actor=actor, **kargs)  # type: ignore

    def trace_range(self, with_center: bool) -> Iterator[Tuple[int, int]]:
        for y in range(self.actor.y - self.range, self.actor.y + self.range + 1):
            for x in range(self.actor.x - self.range, self.actor.x + self.range + 1):
                if not with_center and x == self.actor.x and y == self.actor.y:
                    continue
                if not g.world.map.in_bounds(x, y):
                    continue
                yield x, y


class Blast(ActionWithEffect, WithRange):
    def perform(self) -> bool:
        """Trace the area around the actor and apply the effect."""
        for xy in self.trace_range(with_center=False):
            self.effect.apply(*xy)
        return True


class RandomStep(Action):
    """Move in a random direction."""

    def perform(self) -> bool:
        direction = g.world.rng.choice([(1, 1), (-1, 1), (-1, -1), (1, -1), (1, 0), (-1, 0), (0, 1), (0, -1)])
        return engine.actions.MoveAction(self.actor, direction).perform()


class Pathfind(Action):
    """Pathfind to `dest_xy`, this will go one step in that direction per performance."""

    def __init__(self, actor: engine.actor.Actor, dest_xy: Tuple[int, int]):
        cost = g.world.map.tiles["move_cost"].copy()
        for other in g.world.map.actors:
            cost[other.x, other.y] += 10  # Add some actor avoidance.
        pathfinder = tcod.path.Pathfinder(tcod.path.SimpleGraph(cost=cost, cardinal=2, diagonal=3))
        pathfinder.add_root((actor.x, actor.y))
        self.path: List[Tuple[int, int]] = pathfinder.path_from(dest_xy)[:-1].tolist()
        "The path to follow. This is a stack, so the last item is the next path."
        super().__init__(actor)

    def perform(self) -> bool:
        """Follow the path until the list is empty."""
        if not self.path:
            return False
        next_x, next_y = self.path.pop()
        if MoveAction(self.actor, direction=(next_x - self.actor.x, next_y - self.actor.y)).perform():
            return True
        self.path = []
        return False


class RandomPatrol(Action):
    """Pathfind to random areas."""

    def __init__(self, actor: engine.actor.Actor):
        self.pathfinder: Optional[Pathfind] = None
        super().__init__(actor)

    def perform(self) -> bool:
        """Generate new Pathfind instances then follow them until they're exhausted."""
        rng = g.world.rng
        map_ = g.world.map
        if not self.pathfinder:
            # Can be improved to guarantee a valid path.
            self.pathfinder = Pathfind(self.actor, (rng.randint(0, map_.width - 1), rng.randint(0, map_.height - 1)))
        if self.pathfinder:
            if self.pathfinder.perform():
                return True
        self.pathfinder = None
        return False


class DefaultAI(Action):
    """Default AI action when None is given to Actor."""

    def __init__(self, actor: engine.actor.Actor):
        self.patrol: RandomPatrol = RandomPatrol(actor)
        super().__init__(actor)

    def perform(self) -> bool:
        return self.patrol.perform()


class SeekEnemy(Action):
    def __init__(self, actor: engine.actor.Actor):
        self.pathfinder: Optional[Pathfind] = None
        super().__init__(actor)

    def distance_to(self, other: engine.actor.Actor) -> int:
        """Return the squared distance to another actor."""
        return (self.actor.x - other.x) ** 2 + (self.actor.y - other.y) ** 2

    def get_targets(self) -> Iterator[engine.actor.Actor]:
        """Ither over the enemies in my actors FOV."""
        my_fov = self.actor.get_fov()
        for other in g.world.map.actors:
            if other.faction == self.actor.faction:
                continue
            if not my_fov[other.xy]:
                continue
            yield other

    def perform(self) -> bool:
        targets = list(self.get_targets())
        if targets:
            best = min(targets, key=self.distance_to)
            self.pathfinder = Pathfind(self.actor, best.xy)

        if self.pathfinder and self.pathfinder.perform():
            return True
        self.pathfinder = None
        return False


class PlayerControl(Action):
    """Give control to the player."""

    def perform(self) -> bool:
        logger.info("Player turn")
        assert g.world.player is self.actor
        g.world.map.camera = engine.map.Camera(self.actor.x, self.actor.y)
        engine.states.InGame().run_modal()
        return True
