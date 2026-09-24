from sqlmodel import SQLModel, Field
from datetime import time
from typing import Optional

class Building(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str
    name: str

class Room(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    building_id: int = Field(foreign_key="building.id")
    number: str
    capacity: int
    type: str
    
class Meeting(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    room_id: int = Field(foreign_key="room.id")
    day_of_week: int  # 0=Monday ... 6=Sunday, matches Python's date.weekday()
    start_time: time
    end_time: time
    course_code: str
    term: str