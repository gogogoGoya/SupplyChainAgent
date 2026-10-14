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
        Forward attribute access to the current enterprise instance held by the controller.
                """
        return getattr(self.enterprise, item)
