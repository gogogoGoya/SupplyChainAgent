"""
企业网络管理器模块

负责管理和维护企业间的网络关系
"""

import random
from typing import Dict, List, Set, Tuple


class NetworkManager:
    """
    企业网络管理器
    """
    def __init__(self):
        """
        初始化网络管理器
        """
        self.enterprises = {}  # 企业信息
        self.enterprise_instances = {}  # 企业实例
        self.connections = {}  # 企业间连接 {enterprise_id: {connected_id: relationship_type}}
        self.supply_chain_layers = []  # 供应链层级
        self.network_metrics = {}  # 网络指标
    
    def add_enterprise(self, enterprise_id: str, enterprise_info: Dict, enterprise_instance=None):
        """
        添加企业到网络
        
        Args:
            enterprise_id: 企业ID
            enterprise_info: 企业信息
            enterprise_instance: 企业实例（可选）
        """
        self.enterprises[enterprise_id] = enterprise_info
        self.connections[enterprise_id] = {}
        if enterprise_instance:
            self.enterprise_instances[enterprise_id] = enterprise_instance
    
    def add_enterprises(self, enterprises: Dict[str, Dict], enterprise_instances: Dict[str, object] = None):
        """
        批量添加企业
        
        Args:
            enterprises: 企业字典
            enterprise_instances: 企业实例字典（可选）
        """
        for enterprise_id, enterprise_info in enterprises.items():
            # 如果提供了企业实例字典，则尝试获取对应的企业实例
            instance = enterprise_instances.get(enterprise_id) if enterprise_instances else None
            self.add_enterprise(enterprise_id, enterprise_info, instance)
    
    def add_connection(self, from_id: str, to_id: str, relationship_type: str, metadata: Dict = None):
        """
        添加企业间连接
        
        Args:
            from_id: 源企业ID
            to_id: 目标企业ID
            relationship_type: 关系类型（supplier, customer, competitor等）
            metadata: 额外元数据
        """
        if from_id not in self.enterprises or to_id not in self.enterprises:
            raise ValueError(f"企业ID {from_id} 或 {to_id} 不存在")
        
        connection_data = {
            "type": relationship_type,
            "metadata": metadata or {}
        }
        self.connections[from_id][to_id] = connection_data
    
    def remove_connection(self, from_id: str, to_id: str):
        """
        移除企业间连接
        
        Args:
            from_id: 源企业ID
            to_id: 目标企业ID
        """
        if from_id in self.connections and to_id in self.connections[from_id]:
            del self.connections[from_id][to_id]
    
    def get_connected_enterprises(self, enterprise_id: str, relationship_type: str = None) -> Dict[str, Dict]:
        """
        获取企业的连接企业
        
        Args:
            enterprise_id: 企业ID
            relationship_type: 关系类型（可选）
            
        Returns:
            dict: 连接企业ID到关系数据的映射
        """
        if enterprise_id not in self.connections:
            return {}
        
        if relationship_type is None:
            return self.connections[enterprise_id]
        
        # 过滤特定关系类型
        filtered = {}
        for connected_id, connection_data in self.connections[enterprise_id].items():
            if connection_data["type"] == relationship_type:
                filtered[connected_id] = connection_data
        
        return filtered
    
    def build_supply_chain(self, layers: List[List[str]]):
        """
        构建供应链网络
        
        Args:
            layers: 供应链层级结构，每个层级包含该层级的企业ID列表
        """
        self.supply_chain_layers = layers
        
        # 在相邻层级间创建供应商-客户关系
        for i in range(len(layers) - 1):
            suppliers = layers[i]
            customers = layers[i + 1]
            
            for customer in customers:
                # 每个客户连接到多个供应商
                num_suppliers = random.randint(1, min(3, len(suppliers)))
                selected_suppliers = random.sample(suppliers, num_suppliers)
                
                for supplier in selected_suppliers:
                    self.add_connection(supplier, customer, "supplier", {"tier": i})
                    self.add_connection(customer, supplier, "customer", {"tier": i}) 
    
    def get_suppliers(self, enterprise_id: str) -> List[str]:
        """
        获取企业的供应商
        
        Args:
            enterprise_id: 企业ID
            
        Returns:
            list: 供应商ID列表
        """
        suppliers = []
        
        # 查找所有连接到当前企业的供应商
        for potential_supplier, connection_data in self.get_connected_enterprises(enterprise_id).items():
            if connection_data["type"] == "supplier":
                suppliers.append(potential_supplier)
        
        # 查找所有以当前企业为客户的企业
        for other_id, connections in self.connections.items():
            if enterprise_id in connections and connections[enterprise_id]["type"] == "customer":
                if other_id not in suppliers:
                    suppliers.append(other_id)
        
        return suppliers
    
    def get_customers(self, enterprise_id: str) -> List[str]:
        """
        获取企业的客户
        
        Args:
            enterprise_id: 企业ID
            
        Returns:
            list: 客户ID列表
        """
        customers = []
        
        # 查找所有连接到当前企业的客户
        for potential_customer, connection_data in self.get_connected_enterprises(enterprise_id).items():
            if connection_data["type"] == "customer":
                customers.append(potential_customer)
        
        # 查找所有以当前企业为供应商的企业
        for other_id, connections in self.connections.items():
            if enterprise_id in connections and connections[enterprise_id]["type"] == "supplier":
                if other_id not in customers:
                    customers.append(other_id)
        
        return customers
    
    def calculate_network_metrics(self):
        """
        计算网络指标
        """
        # 计算网络密度
        total_enterprises = len(self.enterprises)
        max_possible_connections = total_enterprises * (total_enterprises - 1)
        actual_connections = sum(len(cons) for cons in self.connections.values())
        
        density = actual_connections / max_possible_connections if max_possible_connections > 0 else 0
        
        # 计算平均度
        avg_degree = actual_connections / total_enterprises if total_enterprises > 0 else 0
        
        # 计算聚类系数
        clustering_coefficient = self._calculate_clustering_coefficient()
        
        # 计算中心性指标
        betweenness_centrality = self._calculate_betweenness_centrality()
        
        self.network_metrics = {
            "density": density,
            "average_degree": avg_degree,
            "clustering_coefficient": clustering_coefficient,
            "betweenness_centrality": betweenness_centrality,
            "total_enterprises": total_enterprises,
            "total_connections": actual_connections
        }
        
        return self.network_metrics
    
    def _calculate_clustering_coefficient(self) -> float:
        """
        计算网络聚类系数
        
        Returns:
            float: 聚类系数
        """
        coefficients = []
        
        for enterprise_id in self.enterprises:
            # 获取企业的邻居
            neighbors = list(self.connections[enterprise_id].keys())
            k = len(neighbors)
            
            if k < 2:
                coefficients.append(0)
                continue
            
            # 计算邻居间的连接数
            actual_connections = 0
            for i in range(len(neighbors)):
                for j in range(i + 1, len(neighbors)):
                    if neighbors[j] in self.connections.get(neighbors[i], {}):
                        actual_connections += 1
            
            # 计算聚类系数
            max_possible_connections = k * (k - 1) / 2
            if max_possible_connections > 0:
                coefficients.append(actual_connections / max_possible_connections)
            else:
                coefficients.append(0)
        
        return sum(coefficients) / len(coefficients) if coefficients else 0
    
    def _calculate_betweenness_centrality(self) -> Dict[str, float]:
        """
        计算节点介数中心性（简化版本）
        
        Returns:
            dict: 企业ID到介数中心性的映射
        """
        centrality = {enterprise_id: 0.0 for enterprise_id in self.enterprises}
        all_pairs = [(s, t) for s in self.enterprises for t in self.enterprises if s != t]
        
        for s, t in all_pairs:
            # 使用BFS查找最短路径（简化实现）
            paths = self._find_shortest_paths(s, t)
            
            if not paths:
                continue
            
            # 计算经过每个节点的路径比例
            for node in centrality:
                if node == s or node == t:
                    continue
                
                paths_through_node = [path for path in paths if node in path]
                if paths_through_node:
                    centrality[node] += len(paths_through_node) / len(paths)
        
        # 标准化
        n = len(self.enterprises)
        if n > 2:
            for node in centrality:
                centrality[node] /= ((n - 1) * (n - 2))
        
        return centrality
    
    def _find_shortest_paths(self, start: str, end: str) -> List[List[str]]:
        """
        查找两个节点间的所有最短路径
        
        Args:
            start: 起始节点
            end: 目标节点
            
        Returns:
            list: 最短路径列表
        """
        # 简化的BFS实现
        if start == end:
            return [[start]]
        
        visited = {start}
        queue = [[start]]
        shortest_paths = []
        found = False
        
        while queue and not found:
            level_size = len(queue)
            
            for _ in range(level_size):
                path = queue.pop(0)
                last_node = path[-1]
                
                for neighbor in self.connections.get(last_node, {}):
                    if neighbor == end:
                        # 找到一条最短路径
                        shortest_paths.append(path + [neighbor])
                        found = True
                    elif neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(path + [neighbor])
        
        return shortest_paths
    
    def get_network_state(self) -> Dict:
        """
        获取网络状态
        
        Returns:
            dict: 网络状态
        """
        return {
            "enterprises": self.enterprises,
            "connections": self.connections,
            "supply_chain_layers": self.supply_chain_layers,
            "metrics": self.network_metrics
        }
    
    def clear(self):
        """
        清空网络
        """
        self.enterprises = {}
        self.enterprise_instances = {}
        self.connections = {}
        self.supply_chain_layers = []
        self.network_metrics = {}
    
    def find_shortest_path(self, from_id: str, to_id: str) -> List[str]:
        """
        查找两个企业间的最短路径
        
        Args:
            from_id: 起始企业ID
            to_id: 目标企业ID
            
        Returns:
            list: 路径上的企业ID列表
        """
        paths = self._find_shortest_paths(from_id, to_id)
        return paths[0] if paths else []
    
    def get_enterprise_by_type(self, enterprise_type: str) -> List[str]:
        """
        根据类型获取企业
        
        Args:
            enterprise_type: 企业类型
            
        Returns:
            list: 企业ID列表
        """
        return [eid for eid, info in self.enterprises.items() if info.get("type") == enterprise_type]
    
    def get_enterprise_instance(self, enterprise_id: str) -> object:
        """
        获取企业实例
        
        Args:
            enterprise_id: 企业ID
            
        Returns:
            object: 企业实例，如果不存在则返回None
        """
        return self.enterprise_instances.get(enterprise_id)
    
    def get_all_enterprise_instances(self) -> Dict[str, object]:
        """
        获取所有企业实例
        
        Returns:
            dict: 企业ID到企业实例的映射
        """
        return self.enterprise_instances.copy()

    def clear_connections(self):
        """
        清空所有企业间的关系连接
        
        该方法会保留企业信息、企业实例和供应链层级，但会清空所有企业之间的连接关系
        """
        # 清空所有连接
        self.connections = {}
        
        # 重新初始化每个企业的连接字典
        for enterprise_id in self.enterprises.keys():
            self.connections[enterprise_id] = {}
        
        return {
            "success": True,
            "message": "所有关系连接已清空",
            "enterprises_affected": len(self.enterprises)
        }
    
    def reset(self):
        # TODO
        pass