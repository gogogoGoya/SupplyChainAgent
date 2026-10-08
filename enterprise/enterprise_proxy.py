class EnterpriseProxy:
    """
    Enable Agent (external user) dynamically to retrieve up-to-date examples of enterprise from controller in proxy mode
        """
    def __init__(self, controller, enterprise_id: str):
        self._controller = controller
        self._enterprise_id = enterprise_id

    @property
    def enterprise(self):
        return self._controller.enterprises[self._enterprise_id]

    def __getattr__(self, item):
        """
        Will all < x17/ > visits
        Automatic agent to < x17/>[id].xxx
                """
        return getattr(self.enterprise, item)
