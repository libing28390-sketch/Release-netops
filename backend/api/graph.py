from fastapi import APIRouter, HTTPException, Query, Body
from typing import List, Optional
from services.graph_service import GraphService
from core.rbac import require_role
import logging

_logger = logging.getLogger(__name__)
router = APIRouter()

@router.get('/graph')
def api_get_graph(
    types: Optional[str] = Query(None, description="Comma-separated list of node types to filter, e.g. device,interface"),
    _user=require_role('Operator')
):
    """
    Retrieve the Network Knowledge Graph (nodes and edges).
    Allows filtering nodes by type.
    """
    types_list = [t.strip().lower() for t in types.split(",")] if types else None
    svc = GraphService()
    return svc.get_graph(types_filter=types_list)

@router.get('/graph/search')
def api_search_graph(
    q: str = Query(..., min_length=1, description="Query string matching name, IP, MAC, hostname, or description"),
    _user=require_role('Operator')
):
    """
    Search the Knowledge Graph nodes by query value (substring match).
    """
    query = str(q).strip().lower()
    svc = GraphService()
    graph = svc.get_graph()
    
    matched_nodes = []
    for node in graph["nodes"]:
        node_id = str(node.get("id", "")).lower()
        node_name = str(node.get("name", "")).lower()
        props = node.get("properties", {})
        
        # Check all string properties for substring match
        prop_match = False
        for val in props.values():
            if val and query in str(val).lower():
                prop_match = True
                break
                
        if query in node_id or query in node_name or prop_match:
            matched_nodes.append(node)
            
    return {
        "query": q,
        "results_count": len(matched_nodes),
        "nodes": matched_nodes
    }

@router.post('/graph/path')
def api_find_graph_path(
    source: str = Body(..., embed=True, description="Source node ID, e.g. endpoint:00:11:22:33:44:55"),
    target: str = Body(..., embed=True, description="Target node ID, e.g. device:core-switch-01"),
    _user=require_role('Operator')
):
    """
    Calculate and trace the path (sequence of hops) between two node IDs.
    """
    svc = GraphService()
    path = svc.find_path(source, target)
    if not path:
        raise HTTPException(
            status_code=404, 
            detail=f"No path found in Network Knowledge Graph between source '{source}' and target '{target}'"
        )
    return {
        "source": source,
        "target": target,
        "hops_count": len(path) // 2 + 1 if path else 0, # edges are interleaved, so number of nodes is len(path) // 2 + 1
        "path": path
    }
