from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import os
import csv
from urllib.parse import urljoin, urlparse

app = FastAPI()

class ShowURL(BaseModel):
    url: str

def find_exhibitor_page(base_url):
    try:
        res = requests.get(base_url, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        for link in soup.find_all('a', href=True):
            href = link['href'].lower()
            text = link.get_text(strip=True).lower()
            if any(keyword in href or keyword in text for keyword in ['exhibit', 'exhibitor', 'lineup', 'sponsor', 'partners']):
                return urljoin(base_url, link['href'])
        return None
    except Exception as e:
        print(f"Error finding exhibitor page: {e}")
        return None

def scrape_exhibitors(url):
    try:
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        exhibitors = []

        # Generalized scraping pattern — customize per show if needed
        for item in soup.find_all(['div', 'li']):
            text = item.get_text(" ", strip=True)
            if text and len(text.split()) <= 15:  # crude filter
                exhibitors.append({
                    'Name': text,
                    'Booth': ''  # You can improve with regex or specific parsing
                })

        return exhibitors[:100]  # limit to 100 for safety
    except Exception as e:
        print(f"Error scraping: {e}")
        return []

def save_to_csv(exhibitors, filename):
    filepath = os.path.join("/tmp", filename)
    with open(filepath, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=['Name', 'Booth'])
        writer.writeheader()
        for exhibitor in exhibitors:
            writer.writerow(exhibitor)
    return filepath

@app.post("/extract")
def extract_and_return_csv(input: ShowURL):
    base_url = input.url
    exhibitor_page = find_exhibitor_page(base_url)
    if not exhibitor_page:
        raise HTTPException(status_code=404, detail="Exhibitor page not found")

    exhibitors = scrape_exhibitors(exhibitor_page)
    if not exhibitors:
        raise HTTPException(status_code=500, detail="Could not extract exhibitor data")

    csv_path = save_to_csv(exhibitors, "exhibitors.csv")
    return FileResponse(csv_path, media_type='text/csv', filename="exhibitors.csv")
