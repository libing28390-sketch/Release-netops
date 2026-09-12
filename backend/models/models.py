from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()

class Device(Base):
    __tablename__ = "devices"
    id = Column(Integer, primary_key=True, index=True)
    hostname = Column(String, unique=True, index=True)
    ip_address = Column(String, index=True)
    platform = Column(String) # cisco_ios, juniper_junos, etc.
    username = Column(String)
    password = Column(String) # In real app, use encryption
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"))
    task_name = Column(String)
    status = Column(String, default="pending") # pending, running, success, failed, rolled_back
    config_before = Column(JSON) # Snapshot before change
    config_after = Column(JSON)  # Snapshot after change
    logs = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
