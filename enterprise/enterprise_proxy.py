class EnterpriseProxy:
    """
    以代理模式让Agent(外部用户)动态从 controller 拿取最新 enterprise 实例
    """
    def __init__(self, controller, enterprise_id: str):
        self._controller = controller
        self._enterprise_id = enterprise_id

    @property
    def enterprise(self):
        return self._controller.enterprises[self._enterprise_id]

    def __getattr__(self, item):
        """
        将所有 enterprise.xxx 的访问
        自动代理到 controller.enterprises[id].xxx
        """
        return getattr(self.enterprise, item)
