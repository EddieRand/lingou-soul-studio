# services/companion-server/app/api/souls.py
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import APIRouter, HTTPException

from data.store import get_archetypes

router = APIRouter()


@router.get("/archetypes")
def list_archetypes():
    """Return all archetype templates."""
    return get_archetypes()
