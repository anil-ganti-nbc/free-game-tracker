import httpx
from bs4 import BeautifulSoup
r = httpx.get("https://primegaming.blog/")
print(r.status_code)
soup = BeautifulSoup(r.text, "html.parser")
articles = soup.find_all("article")
print("Articles:", len(articles))
