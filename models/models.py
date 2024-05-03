from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from models.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    api_key = Column(String, unique=True, index=True)
    client_site_url = Column(String)
    total_requests = Column(Integer, default=0)
    api_key_created_at = Column(DateTime, default=func.now())


class TemporaryKey(Base):
    __tablename__ = "temporary_keys"

    temp_key = Column(String, primary_key=True, unique=True)