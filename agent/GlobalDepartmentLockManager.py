import asyncio
from typing import Dict
from threading import Lock


class GlobalDepartmentLockManager:
    """
    全局部门锁管理器
    确保同一时间只有一个企业的特定部门在运行
    """
    
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._locks: Dict[str, asyncio.Lock] = {}
            self._initialized = True
    
    def get_lock(self, department_role: str) -> asyncio.Lock:
        """
        获取特定部门角色的锁
        :param department_role: 部门角色名称，如 "HR", "Sales", "Procurement" 等
        :return: 对应的异步锁
        """
        if department_role not in self._locks:
            self._locks[department_role] = asyncio.Lock()
        return self._locks[department_role]
    
    async def acquire_department_lock(self, department_role: str) -> None:
        """
        获取并等待特定部门的锁
        :param department_role: 部门角色名称
        """
        lock = self.get_lock(department_role)
        await lock.acquire()
    
    def release_department_lock(self, department_role: str) -> None:
        """
        释放特定部门的锁
        :param department_role: 部门角色名称
        """
        lock = self.get_lock(department_role)
        if lock.locked():
            lock.release()
    
    def is_department_locked(self, department_role: str) -> bool:
        """
        检查特定部门是否已被锁定
        :param department_role: 部门角色名称
        :return: 是否被锁定
        """
        lock = self.get_lock(department_role)
        return lock.locked()