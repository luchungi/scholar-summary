import os
from sqlmodel import SQLModel, create_engine, Session

DATABASE_FILE = "scholar_summary.db"
# Locate the database file in the project root
db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", DATABASE_FILE))
sqlite_url = f"sqlite:///{db_path}"

engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
