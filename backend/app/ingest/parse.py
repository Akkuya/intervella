import bs4
import re


def _parse_room(room):
    match = re.search(r"\((\d+)*\)", room.a.string)
    capacity = match.group(1)
    room_name = re.sub(r"\([0-9]*\)", "", room.a.string).strip()
    return room_name, capacity


with open("backend\data\exampledata.html") as f:
    soup = bs4.BeautifulSoup(f, "html.parser")
    contents = soup.body.find(id="contentwrapper")
    schedules = contents.find_all(class_="tableform")
    
    for building in schedules:
        rooms = building.find_all(class_="smallth")
        print(building.caption.get_text(strip=True))
        for room in rooms:
            print(_parse_room(room))
        print("\n")
        
