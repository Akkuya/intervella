import datetime

import bs4
import re


def _parse_room(room):
    match = re.search(r"\((\d+)\)", room.a.string)
    capacity = int(match.group(1))
    room_name = re.sub(r"\((\d+)\)", "", room.a.string).strip()
    return room_name, capacity


with open("exampledata.html") as f:
    soup = bs4.BeautifulSoup(f, "html.parser")
    contents = soup.body.find(id="contentwrapper")
    schedules = contents.find_all(class_="tableform")
    schedule_data = {
        "date": soup.find(id="labtime").get("value"),
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
            name, capacity = _parse_room(room)

            room_data.append({
                "name": name,
                "capacity": capacity,
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

                
                room_name = room_data[room_index]["name"]
                capacity = room_data[room_index]["capacity"]
                start_time = time
                duration_minutes = span * 30
                classes = cell.get("class", [])
                description = cell.get_text(" ", strip=True)
                
                if "event" in classes:
                    start = datetime.datetime.strptime(start_time, "%H:%M")
                    end = start + datetime.timedelta(minutes=span * 30)

                    event = {
                        "start_time": start_time,
                        "end_time": end.strftime("%H:%M"),
                        "description": description
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
        x.write(schedule_data)
        