from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.engine import URL
from sqlalchemy.orm import declarative_base, sessionmaker
from decouple import config

url = URL.create(
    drivername="postgresql",
    username=config("DB_USER"),
    password=config("DB_PASSWORD"),
    host="localhost",
    database="mydb",
    port=5432
)

engine = create_engine(url)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    sender = Column(String, index=True)
    message = Column(String)
    response = Column(String)

class UserState(Base):
    __tablename__ = "user_states"

    sender = Column(String, primary_key=True, index=True)
    in_handoff = Column(Boolean, default=False)

Base.metadata.create_all(engine)
