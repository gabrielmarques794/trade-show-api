from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import os
import csv
from urllib.parse import urljoin, urlparse
import openai
import json

app = FastAPI()

openai.api_key = os.getenv("OPENAI_API_KEY")  # Make sure to set this in your local environment

KNOWN_SHOWS = {
    "uk.healthoptimisation.com": "https://uk.healthoptimisation.com/page/3902835/exhibitor-lineup",
    "expowest.com": "https://www.expowest.com/en/exhibitor-list.html",
    "npe.org": "https://npe.org/exhibitors",
    "naturallynetwork.org": "https://www.naturallynetwork.org/sponsors",
    "worldteaconference.com": "https://worldteaconference.com/exhibitor-list",
    "supplysideeast.com": "https://east.supplysideshow.com/en/exhibitor-list.html"
}

class ShowURL(BaseModel):
    url: str

from playwright.sync_api import sync_playwright

def get_rendered_html(url):
    from playwright.sync_api import sync_playwright
    import traceback

    print(f"[Playwright] Attempting to open: {url}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, slow_mo=100)
            page = browser.new_page()
            response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
            print(f"[Playwright] Response status: {response.status if response else 'No response'}")
            content = page.content()
            print("[Playwright] Page content retrieved.")
            browser.close()
            return content
    except Exception as e:
        print("[Playwright ERROR]")
        traceback.print_exc()
        return ""

def ask_gpt_for_exhibitor_link(base_url, html):
    prompt = f"""
You're a smart crawler trained to analyze trade show websites.

From the HTML provided below, your job is to:
1. Identify the link that leads to the exhibitor list, sponsor list, partner brands, or booth map.
2. Respond ONLY with the full URL to that page (absolute URL), nothing else.
3. Do not explain anything.

The homepage URL is: {base_url}

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

HTML (first 15000 characters):
{html[:15000]}
"""
    try:
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.choices[0].message.content.strip()
        print(f"[GPT data guess]: {raw[:300]}...")

        if raw.startswith("```json"):
            raw = raw.removeprefix("```json").removesuffix("```").strip()
        elif raw.startswith("```"):
            raw = raw.removeprefix("```").removesuffix("```").strip()

        print(f"[Cleaned GPT data]: {raw[:300]}...")
        parsed = json.loads(raw)
        filtered = [item for item in parsed if item.get("Name") and len(item["Name"]) > 3 and "exhibit" not in item["Name"].lower()]
        return filtered[:100]
    except Exception as e:
        print(f"GPT content extraction failed: {e}")
        return []

def find_exhibitor_page(base_url):
    try:
        if any(keyword in base_url.lower() for keyword in ['exhibit', 'sponsor', 'lineup', 'partners']):
            print(f"[Direct match] Using provided URL as exhibitor page: {base_url}")
            return base_url

        parsed = urlparse(base_url)
        domain = parsed.hostname or ""

        if domain in KNOWN_SHOWS:
            print(f"[Known show match] Using hardcoded link for {domain}")
            return KNOWN_SHOWS[domain]

        res = requests.get(base_url, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')

        for link in soup.find_all('a', href=True):
            href = link['href'].lower()
            text = link.get_text(strip=True).lower()
            print(f"Found link: {text} -> {href}")
            if any(keyword in href or keyword in text for keyword in ['exhibit', 'exhibitor', 'lineup', 'line-up', 'sponsor', 'partners', 'expo']):
                return urljoin(base_url, link['href'])

        gpt_guess = ask_gpt_for_exhibitor_link(base_url, res.text)
        if gpt_guess:
            try:
                gpt_check = requests.get(gpt_guess, timeout=10)
                if gpt_check.status_code == 200:
                    return gpt_guess
            except Exception as e:
                print(f"GPT guessed URL failed to load: {e}")

        return None
    except Exception as e:
        print(f"Error finding exhibitor page: {e}")
        return None

def scrape_exhibitors(url):
    try:
        html = get_rendered_html(url)
        return ask_gpt_to_extract_exhibitors(html)
    except Exception as e:
        print(f"Error scraping: {e}")
        return []

def save_to_csv(exhibitors, filename):
    filepath = os.path.join(os.getcwd(), filename)
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
