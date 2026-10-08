"""
Event Manager Module

Manage events in the simulation system
"""

class EventManager:
    """
    Event Manager
        """
    def __init__(self):
        """
        Initialise Event Manager
                """
        self.events = []  # Organisation
        self.event_handlers = {}  # Organisation
    
    def add_event(self, event):
        """
        Add Event
                
        Args:
            event: object should include the words type, timestamp, payload
                """
        # Insert by Timestamp
        inserted = False
        for i, existing_event in enumerate(self.events):
            if event["timestamp"] < existing_event["timestamp"]:
                self.events.insert(i, event)
                inserted = True
                break
        
        if not inserted:
            self.events.append(event)
    
    def add_events(self, events):
        """
        Batch Add Event
                
        Args:
            Organisation
                """
        for event in events:
            self.add_event(event)
    
    def get_next_events(self, current_time):
        """
        Fetch all pending events at current time point and before
                
        Args:
            parameter : Current Time
                        
        Returns:
            list:
                """
        events_to_process = []
        remaining_events = []
        
        for event in self.events:
            if event["timestamp"] <= current_time:
                events_to_process.append(event)
            else:
                remaining_events.append(event)
        
        # Update Event List
        self.events = remaining_events
        
        return events_to_process
        
    def process_events(self, events, current_state=None):
        """
        Handle Event List
                
        Args:
            Organisation
            current_state: Current System Status (optional)
                        
        Returns:
            list: Process result list
                """
        results = []
        
        for event in events:
            # Find a handler for this event
            for handler in self.event_handlers.get(event["type"], []):
                try:
                    # Execute Processor
                    if current_state is not None:
                        result = handler(event, current_state)
                    else:
                        result = handler(event)
                    
                    # Record processing results
                    if result is not None:
                        results.append({
                            'event_id': id(event),
                            'event_type': event["type"],
                            'handler': str(handler),
                            'result': result
                        })
                except Exception as e:
                    # Record processing anomalies
                    results.append({
                        'event_id': id(event),
                        'event_type': event["type"],
                        'handler': str(handler),
                        'result': {'status': 'error', 'message': str(e)}
                    })
        
        return results
    
    def register_handler(self, event_type, handler):
        """
        Registered Event Processor
                
        Args:
            parameter: Event type
            Handler: Event Handling Function
                """
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        
        self.event_handlers[event_type].append(handler)
    
    def unregister_handler(self, event_type, handler):
        """
        Write-off incident processor
                
        Args:
            parameter: Event type
            Handler: Event Handling Function
                """
        if event_type in self.event_handlers:
            self.event_handlers[event_type].remove(handler)
    
    def process_events(self, events, state):
        """
        Deal with events
                
        Args:
            Organisation
            State: Current status
                        
        Returns:
            list: Process result list
                """
        results = []
        
        for event in events:
            event_type = event["type"]
            
            # Find Event Processor
            handlers = self.event_handlers.get(event_type, [])
            
            for handler in handlers:
                result = handler(event, state)
                results.append(result)
        
        return results
    
    def clear_events(self):
        """
        Clear all incidents
                """
        self.events = []
    
    def get_event_count(self):
        """
        Fetch the number of current events
                
        Returns:
            Int: Number of events
                """
        return len(self.events)
    
    def get_pending_events_by_type(self, event_type):
        """
        Get specified type of pending event
                
        Args:
            parameter: Event type
                        
        Returns:
            list:
                """
        return [event for event in self.events if event["type"] == event_type]
    
    def cancel_events(self, event_type=None, enterprise_id=None):
        """
        Cancel events of specified type or enterprise
                
        Args:
            event_type: Event type (optional)
            enterprise_id: enterpriseID (optional)
                """
        remaining_events = []
        
        for event in self.events:
            should_keep = True
            
            if event_type is not None and event["type"] == event_type:
                should_keep = False
            
            if enterprise_id is not None and event.get("enterprise_id") == enterprise_id:
                should_keep = False
            
            if should_keep:
                remaining_events.append(event)
        
        self.events = remaining_events
    
    def reset(self):
        """
        Reset Event Manager Status
                """
        self.events = []
        self.event_handlers = {}

# Predefined Event Type
EVENT_TYPES = {
    "PRODUCTION_COMPLETE": "production_complete",
    "ORDER_RECEIVED": "order_received",
    "ORDER_DELIVERED": "order_delivered",
    "PAYMENT_MADE": "payment_made",
    "PAYMENT_RECEIVED": "payment_received",
    "INVENTORY_LOW": "inventory_low",
    "SUPPLIER_DELAY": "supplier_delay",
    "DEMAND_CHANGE": "demand_change",
    "PRICE_CHANGE": "price_change",
    "ENTERPRISE_BANKRUPTCY": "enterprise_bankruptcy",
    "NEW_SUPPLIER": "new_supplier",
    "NEW_CUSTOMER": "new_customer",
    "CONTRACT_EXPIRE": "contract_expire",
    "QUALITY_ISSUE": "quality_issue",
    "MAINTENANCE_START": "maintenance_start",
    "MAINTENANCE_END": "maintenance_end"
}

# Event Factory Function
def create_event(event_type, timestamp, payload=None, enterprise_id=None, data=None):
    """
    Create Event
        
    Args:
        parameter: Event type
        Timestamp: Timetamp
        Payload: Event data (optional)
        enterprise_id: enterpriseID (optional)
        Data: Event data (new compatible format)
                
    Returns:
        dict: Object
        """
    # Create object to support both data and Payload formats
    event = {
        "type": event_type,
        "timestamp": timestamp
    }
    
    # If you provide payload, use payload
    if payload is not None:
        event["payload"] = payload
    # If data is provided, use data
    elif data is not None:
        event["data"] = data
    # Otherwise use an empty dictionary
    else:
        event["data"] = {}
    
    if enterprise_id:
        event["enterprise_id"] = enterprise_id
    
    return event

# Predefined step and stage event type
TIME_STEP_EVENT_TYPES = {
    "TIME_STEP_START": "time_step_start",
    "TIME_STEP_END": "time_step_end",
    "TIME_STEP_PHASE_STARTED": "time_step_phase_started",
    "TIME_STEP_PHASE_COMPLETED": "time_step_phase_completed",
    "TIME_STEP_COMPLETED": "time_step_completed",
    "ENTERPRISE_DECISION_STARTED": "enterprise_decision_started",
    "ENTERPRISE_DECISION_COMPLETED": "enterprise_decision_completed",
    "ENTERPRISE_EXECUTION_STARTED": "enterprise_execution_started",
    "ENTERPRISE_EXECUTION_COMPLETED": "enterprise_execution_completed"
}
