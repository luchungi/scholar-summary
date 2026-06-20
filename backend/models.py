from datetime import datetime
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship

class Run(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: str  # "running", "completed", "failed"
    emails_fetched: int = 0
    papers_processed: int = 0
    papers_failed: int = 0
    log_file_path: Optional[str] = None
    
    papers: List["Paper"] = Relationship(back_populates="run")

class Paper(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    url: str
    status: str  # "success", "failed"
    date_processed: datetime = Field(default_factory=datetime.utcnow)
    report_path: Optional[str] = None
    run_id: Optional[int] = Field(default=None, foreign_key="run.id")
    
    run: Optional[Run] = Relationship(back_populates="papers")

class EmailAlert(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    message_id: str = Field(unique=True, index=True)
    subject: str
    date: str
    processed: bool = False
