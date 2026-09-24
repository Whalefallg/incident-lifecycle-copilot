"""
UserBehavior Module

Incident triage pattern analysis components:
- BehaviorRecorder: Records engineer incident handling actions
- PatternAnalyzer: Analyzes triage patterns and preferences
- PreferenceManager: Manages engineer preferences
"""

from .behavior_recorder import BehaviorRecorder
from .pattern_analyzer import PatternAnalyzer
from .preference_manager import PreferenceManager

__all__ = [
    'BehaviorRecorder',
    'PatternAnalyzer',
    'PreferenceManager'
]
