import asyncio
from typing import Dict
from threading import Lock


class GlobalDepartmentLockManager:
    """
    Global department Lock Manager
    Make sure that only one specific enterprise department is running at the same time
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
        Get a lock on specific department roles
        : paramdepartment_role: department role names such as "HR", "Sales", "Procurement" etc.
        :return: The asynchronous lock for the department role.
                """
        if department_role not in self._locks:
            self._locks[department_role] = asyncio.Lock()
        return self._locks[department_role]
    
    async def acquire_department_lock(self, department_role: str) -> None:
        """
        Get and wait for a specific lock department
        : paramdepartment_role: department Role name
                """
        lock = self.get_lock(department_role)
        await lock.acquire()
    
    def release_department_lock(self, department_role: str) -> None:
        """
        Release specific lock department
        : paramdepartment_role: department Role name
                """
        lock = self.get_lock(department_role)
        if lock.locked():
            lock.release()
    
    def is_department_locked(self, department_role: str) -> bool:
        """
        Check if specific department is locked
        : paramdepartment_role: department Role name
        :return: Locked
                """
        lock = self.get_lock(department_role)
        return lock.locked()
