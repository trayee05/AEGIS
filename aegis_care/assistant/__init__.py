"""Natural-language routing for the AEGIS-Care console.

The model chooses an action; the console computes the answer. No clinical
value, metric, or chart datum ever originates from a language model.
"""
from .intents import ACTIONS, actions_for, match_local
from .router import Budget, Router

__all__ = ["ACTIONS", "actions_for", "match_local", "Router", "Budget"]
