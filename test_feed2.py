import xml.etree.ElementTree as ET

from newsroom.sources._http import fetch_text


def main() -> None:
    try:
        feed = fetch_text("https://blogs.nvidia.com/category/geforce-now/feed/")
        root = ET.fromstring(feed)
        titles = [
            item.find("title").text
            for item in root.findall(".//item")
            if item.find("title") is not None
        ]
        print(f"Total items: {len(titles)}")
        print("Titles:")
        for title in titles:
            print(f"- {title}")
    except Exception as exc:
        print(exc)


if __name__ == "__main__":
    main()
