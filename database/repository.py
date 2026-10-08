"""
Data Access Layer - Repository Mode Achieved

Provide common database CRUD operational interface
"""
from typing import Generic, TypeVar, Optional, List, Dict, Any, Type
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, inspect, func

from database.models.base import BaseModel

T = TypeVar('T', bound=BaseModel)


class Repository(Generic[T]):
    """
    Generic data warehouse base category
    Provide basic CRUD operations for database entities
        """
    
    def __init__(self, model_class: Type[T]):
        """
        Initialize Repivory
                
        Args:
            model_class: Database Model Category
                """
        self.model_class = model_class
    
    def get(self, db: Session, id: int) -> Optional[T]:
        """
        Acquisition of individual entities from ID
                
        Args:
            db: Database Session
            id: Entity ID
                        
        Returns:
            Example of entity or Noone
                """
        return db.query(self.model_class).filter(self.model_class.id == id).first()
    
    def get_all(self, db: Session, skip: int = 0, limit: int = 100) -> List[T]:
        """
        Access to all entities (page breakable)
                
        Args:
            db: Database Session
            sskip: Skipped records
            Limited: Maximum number of records returned
                        
        Returns:
            Entity List
                """
        return db.query(self.model_class).offset(skip).limit(limit).all()
    
    def get_by(self, db: Session, **kwargs) -> List[T]:
        """
        Search entities by condition
                
        Args:
            db: Database Session
            **kwargs: Query Conditions, Formatting Field Name = Value
                        
        Returns:
            List of eligible entities
                """
        # Build query conditions
        conditions = []
        for key, value in kwargs.items():
            # Checks if properties exist
            if hasattr(self.model_class, key):
                conditions.append(getattr(self.model_class, key) == value)
        
        return db.query(self.model_class).filter(and_(*conditions)).all()
    
    def get_first(self, db: Session, **kwargs) -> Optional[T]:
        """
        Search individual entities on condition
                
        Args:
            db: Database Session
            **kwargs: Query Conditions, Formatting Field Name = Value
                        
        Returns:
            First Eligible Entity or Noone
                """
        # Build query conditions
        conditions = []
        for key, value in kwargs.items():
            if hasattr(self.model_class, key):
                conditions.append(getattr(self.model_class, key) == value)
        
        return db.query(self.model_class).filter(and_(*conditions)).first()
    
    def create(self, db: Session, obj_in: Dict[str, Any]) -> T:
        """
        Create new entity
                
        Args:
            db: Database Session
            obj_in: Entity data dictionary
                        
        Returns:
            Examples of entities created
                """
        # Filter fields that do not exist in the model
        model_columns = [c.name for c in inspect(self.model_class).columns]
        filtered_data = {k: v for k, v in obj_in.items() if k in model_columns}
        
        # Examples of entities created
        db_obj = self.model_class(**filtered_data)
        
        # Add to Session and Submit
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        
        return db_obj
    
    def update(self, db: Session, db_obj: T, obj_in: Dict[str, Any]) -> T:
        """
        Update of existing entities
                
        Args:
            db: Database Session
            parameter: Entity objects in database
            parameter: Updated data dictionary
                        
        Returns:
            Updated Entity Examples
                """
        # Filter fields that do not exist in the model
        model_columns = [c.name for c in inspect(self.model_class).columns]
        filtered_data = {k: v for k, v in obj_in.items() if k in model_columns}
        
        # Update Fields
        for field, value in filtered_data.items():
            setattr(db_obj, field, value)
        
        # Submit Update
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        
        return db_obj
    
    def delete(self, db: Session, id: int) -> bool:
        """
        Delete Entity
                
        Args:
            db: Database Session
            id: Entity ID
                        
        Returns:
            Delete successfully
                """
        db_obj = self.get(db, id)
        if db_obj:
            db.delete(db_obj)
            db.commit()
            return True
        return False
    
    def delete_by(self, db: Session, **kwargs) -> int:
        """
        Deleting entities under conditions
                
        Args:
            db: Database Session
            **kwargs: Delete the condition, format it as field name = value
                        
        Returns:
            Number of records removed
                """
        # Build query conditions
        conditions = []
        for key, value in kwargs.items():
            if hasattr(self.model_class, key):
                conditions.append(getattr(self.model_class, key) == value)
        
        # Execute Delete
        result = db.query(self.model_class).filter(and_(*conditions)).delete()
        db.commit()
        
        return result
    
    def count(self, db: Session, **kwargs) -> int:
        """
        Number of statistical entities
                
        Args:
            db: Database Session
            **kwargs: Filter conditions, formatted as field name = value
                        
        Returns:
            Number of entities
                """
        query = db.query(func.count(self.model_class.id))
        
        # Apply filter conditions
        if kwargs:
            conditions = []
            for key, value in kwargs.items():
                if hasattr(self.model_class, key):
                    conditions.append(getattr(self.model_class, key) == value)
            query = query.filter(and_(*conditions))
        
        return query.scalar() or 0
    
    def exists(self, db: Session, **kwargs) -> bool:
        """
        Check for eligible entities
                
        Args:
            db: Database Session
            **kwargs: Query Conditions, Formatting Field Name = Value
                        
        Returns:
            Existence
                """
        return self.count(db, **kwargs) > 0
    
    def get_by_ids(self, db: Session, ids: List[int]) -> List[T]:
        """
        Get multiple entities according to ID list
                
        Args:
            db: Database Session
            ids: ID list
                        
        Returns:
            Entity List
                """
        return db.query(self.model_class).filter(self.model_class.id.in_(ids)).all()
    
    def search(self, db: Session, search_text: str, fields: List[str], skip: int = 0, limit: int = 100) -> List[T]:
        """
        Search Entity
                
        Args:
            db: Database Session
            parameter: Search text
            Fields: list of fields to search for
            sskip: Skipped records
            Limited: Maximum number of records returned
                        
        Returns:
            List of entities eligible for search
                """
        # Build search conditions
        search_conditions = []
        for field in fields:
            if hasattr(self.model_class, field):
                field_attr = getattr(self.model_class, field)
                # Apply type search only for string type fields
                if hasattr(field_attr, 'like'):
                    search_conditions.append(field_attr.like(f'%{search_text}%'))
        
        # Execute Search
        return db.query(self.model_class)\
            .filter(or_(*search_conditions))\
            .offset(skip)\
            .limit(limit)\
            .all()


# Repository category for creating commonly used models
from database.models.enterprise import Enterprise, Supplier, Customer, ProductionPlan, PurchaseOrder, SalesOrder
from database.models.product import Product, ProductCategory, ProductAttribute, ProductVariant, Brand
from database.models.order import Order, OrderLineItem, ShippingAddress, PaymentInfo, ShippingInfo


class EnterpriseRepository(Repository[Enterprise]):
    """enterprise data repository"""
    def __init__(self):
        super().__init__(Enterprise)


class SupplierRepository(Repository[Supplier]):
    """Vendor data warehouse"""
    def __init__(self):
        super().__init__(Supplier)


class CustomerRepository(Repository[Customer]):
    """Client Data Repository"""
    def __init__(self):
        super().__init__(Customer)


class ProductRepository(Repository[Product]):
    """Product data warehouse"""
    def __init__(self):
        super().__init__(Product)


class OrderRepository(Repository[Order]):
    """Order data warehouse"""
    def __init__(self):
        super().__init__(Order)
    
    def get_by_order_number(self, db: Session, order_number: str) -> Optional[Order]:
        """Get orders by order number."""
        return self.get_first(db, order_number=order_number)
    
    def get_by_status(self, db: Session, status: str, skip: int = 0, limit: int = 100) -> List[Order]:
        """Get orders by status"""
        return self.get_by(db, status=status, skip=skip, limit=limit)


class OrderLineItemRepository(Repository[OrderLineItem]):
    """Order data warehouse"""
    def __init__(self):
        super().__init__(OrderLineItem)
    
    def get_by_order_id(self, db: Session, order_id: int) -> List[OrderLineItem]:
        """All line items for order acquisition"""
        return self.get_by(db, order_id=order_id)
