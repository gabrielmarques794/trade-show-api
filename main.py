from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
import requests
from bs4 import BeautifulSoup

app = FastAPI()

class URLInput(BaseModel):
    url: str

class Exhibitor(BaseModel):
    name: str
    company: str
    title: str = None
    booth: str = None

@app.post("/scrape", response_model=List[Exhibitor])
def scrape(input: URLInput):
    response = requests.get(input.url)
    soup = BeautifulSoup(response.text, 'html.parser')
    exhibitors = []

    for card in soup.select('.exhibitor-card'):  # MUDE AQUI conforme o site real
        name = card.select_one('.exhibitor-name')
        company = card.select_one('.company')
        title = card.select_one('.title')
        booth = card.select_one('.booth')

        exhibitors.append(Exhibitor(
            name=name.text.strip() if name else '',
            company=company.text.strip() if company else '',
            title=title.text.strip() if title else None,
            booth=booth.text.strip() if booth else None
        ))

    return exhibitors
