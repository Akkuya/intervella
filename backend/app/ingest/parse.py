import datetime
import json
from zoneinfo import ZoneInfo
import bs4
import re


def _parse_room(room):
    match = re.search(r"\((\d+)\)", room.a.string)
    capacity = int(match.group(1))
    room_name = re.sub(r"\((\d+)\)", "", room.a.string).strip()
    room_id = int(re.search(r"rfilter=(\d+)", room.a["href"]).group(1))
    return room_name, capacity, room_id


with open("exampledata.html") as f:
    soup = bs4.BeautifulSoup(f, "html.parser")
    contents = soup.body.find(id="contentwrapper")
    schedules = contents.find_all(class_="tableform")
    schedule_data = {
        "date": soup.find(id="labtime").get("value"),
        "generated_at": datetime.datetime.now(
        ZoneInfo("America/Toronto")
    ).isoformat(timespec="seconds"),
        "buildings": []
    }
    
    
    for building in schedules:
        building_name = building.caption.get_text(strip=True)
        print(building_name)
        rooms = building.find_all(class_="smallth")
        room_data = []
        building_data = {
            "name": building_name,
            "rooms": []
        }
        for room in rooms:
            name, capacity, room_id = _parse_room(room)

            room_data.append({
                "name": name,
                "capacity": capacity,
                "id": room_id,
                "events": []
            })
        print("\n")
        
        
        remaining_spans = [0] * len(rooms)
        rows = building.thead.find_next_siblings("tr")
        
        for index, row in enumerate(rows):
            entries = row.find_all("td")
            time = entries[0].div.get_text(strip=True)
            cells = entries[1:]

            cell_index = 0

            for room_index in range(len(rooms)):

                # A previous cell still covers this room
                if remaining_spans[room_index] > 0:
                    continue

                # Get the next HTML cell
                cell = cells[cell_index]
                cell_index += 1

                # Extract its rowspan
                span = int(cell.get("rowspan", 1))

                # Track how many rows this cell covers
                remaining_spans[room_index] = span

                
                classes = cell.get("class", [])
                
                if "event" in classes:
                    start = datetime.datetime.strptime(time, "%H:%M")
                    end = start + datetime.timedelta(minutes=span * 30)

                    event = {
                        "start_time": time,
                        "end_time": end.strftime("%H:%M"),
                        "description": cell.get_text(" ", strip=True)
                    }

                    room_data[room_index]["events"].append(event)
               

            # One row has now been processed
            remaining_spans = [
                max(0, span - 1)
                for span in remaining_spans
            ]
            
        

        building_data["rooms"] = room_data
        schedule_data["buildings"].append(building_data)

    with open("output.json", "w+") as x:
        import json
        json.dump(schedule_data, x)
        