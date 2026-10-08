"""
Basic database model

Define the base category and common structure of the database tables
"""

from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy import Column, String, DateTime, JSON, Boolean, Integer
from sqlalchemy.sql import func
from database.db_manager import Base


class BaseModel(Base):
    """
    Database Model Base Category
    BaseModel in the data model
        """
    __abstract__ = True
    
    # Primary Key ID
    id = Column(String, primary_key=True, index=True)
    
    # Timetamp
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=func.now())
    
    # Status
    status = Column(String, default="active")
    
    # Label (use JSON storage list)
    tags = Column(JSON, default=list)
    
    # Metadata
    metadata_ = Column("metadata", JSON, default=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert database model to dictionary
                
        Returns:
            dict: Model dictionary
                """
        result = {}
        for column in self.__table__.columns:
            key = column.name
            value = getattr(self, key)
            
            # Process JSON fields
            if isinstance(value, dict) or isinstance(value, list):
                result[key] = value
            # Process the datetime field
            elif hasattr(value, 'isoformat'):
                result[key] = value.isoformat()
            else:
                result[key] = value
        
        # Fix metadata field name
        if 'metadata_' in result:
            result['metadata'] = result.pop('metadata_')
        
        return result
    
    def from_dict(self, data: Dict[str, Any]) -> "BaseModel":
        """
        Load data from dictionary to model
                
        Args:
            Data: Model dictionary data
                
        Returns:
            BaseModel: updated model examples
                """
        for key, value in data.items():
            # Process metadata field names
            if key == 'metadata':
                key = 'metadata_'
            
            if hasattr(self, key):
                setattr(self, key, value)
        
        return self
