from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import os
import csv
from urllib.parse import urljoin
import openai
import json

app = FastAPI()

openai.api_key = os.getenv("OPENAI_API_KEY")  # Make sure to set this in your Render environment

class ShowURL(BaseModel):
    url: str

def ask_gpt_for_exhibitor_link(base_url, html):
    prompt = f"""
    Given the following HTML from a trade show homepage ({base_url}),
    return the most likely full URL path (not just the path, but full URL) for the exhibitor list page.
    Respond ONLY with the most likely full URL to the exhibitor page.

    HTML (first 15000 characters):
{html[:15000]}

    """
    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        result = response.choices[0].message.content.strip()
        print(f"[GPT link guess]: {result}")
        if not result.startswith("http"):
            return None
        return result
    except Exception as e:
        print(f"GPT fallback failed: {e}")
        return None

def ask_gpt_to_extract_exhibitors(html):
    prompt = f"""
    Extract a list of exhibitors from the following HTML.
    For each exhibitor, return:
    - Name
    - Booth (if available)

    Format the response strictly as a JSON array of objects like:
    [
      {{ "Name": "Example Exhibitor", "Booth": "123" }},
      {{ "Name": "Another Brand", "Booth": "A45" }}
    ]

    Do not include markdown, explanations, or extra formatting.

    HTML:
    {html[:4000]}
    """
    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.choices[0].message.content.strip()
        print(f"[GPT data guess]: {raw[:300]}...")

        # Clean up markdown formatting if present
        if raw.startswith("```json"):
            raw = raw.removeprefix("```json").removesuffix("```").strip()
        elif raw.startswith("```"):
            raw = raw.removeprefix("```").removesuffix("```").strip()

        print(f"[Cleaned GPT data]: {raw[:300]}...")
        parsed = json.loads(raw)

        # Filter out generic or low-value entries
        filtered = [item for item in parsed if item.get("Name") and len(item["Name"]) > 3 and "exhibit" not in item["Name"].lower()]
        return filtered[:100]
    except Exception as e:
        print(f"GPT content extraction failed: {e}")
        return []

def find_exhibitor_page(base_url):
    try:
        res = requests.get(base_url, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        for link in soup.find_all('a', href=True):
            href = link['href'].lower()
            text = link.get_text(strip=True).lower()
            print(f"Found link: {text} -> {href}")
            if any(keyword in href or keyword in text for keyword in ['exhibit', 'exhibitor', 'lineup', 'line-up', 'sponsor', 'partners', 'expo']):
                return urljoin(base_url, link['href'])

        # fallback to GPT if not found
        gpt_guess = ask_gpt_for_exhibitor_link(base_url, res.text)
        if gpt_guess:
            return gpt_guess
        return None
    except Exception as e:
        print(f"Error finding exhibitor page: {e}")
        return None

def scrape_exhibitors(url):
    try:
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        exhibitors = []

        for item in soup.find_all(['div', 'li']):
            text = item.get_text(" ", strip=True)
            if text and len(text.split()) <= 15 and "exhibit" not in text.lower():
                exhibitors.append({
                    'Name': text,
                    'Booth': ''
                })

        if not exhibitors:
            return ask_gpt_to_extract_exhibitors(res.text)

        return exhibitors[:100]
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
