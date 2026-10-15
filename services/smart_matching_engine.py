"""
Smart Matching Engine Facade for Saghf Real Estate OS.
Re-exports MatchingEngine and UnifiedMatcher for Phase 1 & Phase 2 interoperability.
"""
from services.matching_service import MatchingEngine
from services.unified_matcher import UnifiedMatcher, DemandProfile, _Scorer

__all__ = ["MatchingEngine", "UnifiedMatcher", "DemandProfile", "_Scorer"]