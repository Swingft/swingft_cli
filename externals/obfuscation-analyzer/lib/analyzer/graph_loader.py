import json
import networkx as nx
from typing import Dict, Any


class SymbolGraph:
    """JSON 파일로부터 심볼 그래프를 로드하고 쿼리 헬퍼를 제공합니다."""

    def __init__(self, json_path: str):
        self.graph = nx.DiGraph()
        self._load_from_json(json_path)

    def _load_from_json(self, json_path: str):
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for symbol_data in data.get('symbols', []):
            self.graph.add_node(symbol_data['id'], **symbol_data)

        for edge_data in data.get('edges', []):
            self.graph.add_edge(
                edge_data['from'],
                edge_data['to'],
                type=edge_data['type']
            )

    def get_node(self, node_id: str) -> Dict[str, Any]:
        """노드 ID로 노드 데이터를 반환합니다."""
        if node_id not in self.graph:
            return None
        return self.graph.nodes[node_id]

    def find_all_nodes(self):
        """모든 노드 ID 리스트를 반환합니다."""
        return list(self.graph.nodes)

    def get_neighbors(self, node_id: str, edge_type: str = None, direction: str = 'out'):
        """특정 엣지 타입으로 연결된 이웃 노드를 찾습니다."""
        neighbors = []
        edges = self.graph.out_edges(node_id, data=True) if direction == 'out' else self.graph.in_edges(node_id,
                                                                                                        data=True)

        for u, v, data in edges:
            if edge_type is None or data.get('type') == edge_type:
                neighbors.append(v if direction == 'out' else u)
        return neighbors