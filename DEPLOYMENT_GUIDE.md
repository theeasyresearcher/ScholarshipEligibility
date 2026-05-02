# Scholarship Eligibility Checker — Deployment & Customisation Guide

## Project Structure

```
scholarship-checker/
├── index.html                          ← Frontend UI (form + results)
├── style.css                           ← All styling
├── script.js                           ← Client-side filter logic
├── scholarships.json                   ← The data file (auto-updated daily)
├── scraper.py                          ← Python scraping script
├── requirements.txt                    ← Python dependencies
└── .github/
    └── workflows/
        └── update_scholarships.yml     ← GitHub Actions automation
```

---

## Part 1 — Deploying to GitHub Pages

### Step 1: Create the Repository

1. Go to [github.com/new](https://github.com/new)
2. Name it e.g. `scholarship-checker` (make it **Public**)
3. Click **Create repository**

### Step 2: Push all files

```bash
# From your local project folder
git init
git add .
git commit -m "feat: initial scholarship checker setup"
git remote add origin https://github.com/YOUR_USERNAME/scholarship-checker.git
git branch -M main
git push -u origin main
```

### Step 3: Enable GitHub Pages

1. Go to your repo → **Settings** → **Pages**
2. Under **Source**, select **Deploy from a branch**
3. Choose **Branch: main**, **Folder: / (root)**
4. Click **Save**

Your site will be live at:
```
https://YOUR_USERNAME.github.io/scholarship-checker/
```

> It takes 1–3 minutes to go live the first time.

### Step 4: Give Actions permission to push

1. Go to **Settings** → **Actions** → **General**
2. Scroll to **Workflow permissions**
3. Select **Read and write permissions**
4. Click **Save**

This allows the workflow to commit the updated `scholarships.json` back.

---

## Part 2 — Testing the Scraper Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run normally
python scraper.py

# Run with verbose debug output
python scraper.py --debug

# Run and save to a custom path
python scraper.py --output data/scholarships.json
```

After running, check:
- `scholarships.json` — the output data file
- `scraper.log` — detailed log of what was scraped and any errors
- `scholarships_meta.json` — stats about the run (count, sources used)

---

## Part 3 — Triggering the GitHub Action Manually

1. Go to your repo on GitHub
2. Click the **Actions** tab
3. Select **Update Scholarship Data** in the left sidebar
4. Click **Run workflow** → **Run workflow**

You can also enable **debug mode** from the dropdown before running.

---

## Part 4 — Customising the Scraper

### Adding a New Scholarship Source

Open `scraper.py` and add a new function following this pattern:

```python
def scrape_my_new_source(session: requests.Session) -> list[dict]:
    """Scrape scholarships from MyPortal.gov.in"""
    log.info("── Source N: MyPortal ───────────────────────────────")
    results = []

    try:
        polite_delay()
        resp = session.get("https://myportal.gov.in/scholarships", timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for card in soup.select(".scholarship-card"):
            title = safe_text(card.select_one("h2"))
            if not title:
                continue

            results.append(normalise({
                "name":        title,
                "amount":      safe_text(card.select_one(".amount")),
                "deadline":    _parse_deadline(safe_text(card.select_one(".date"))),
                "eligibility": safe_text(card.select_one(".description"))[:400],
                "link":        card.select_one("a")["href"],
                "type":        "central",    # or "state" / "private"
                "categories":  _guess_categories(title),
                "source":      "myportal.gov.in",
            }))

    except Exception as e:
        log.error("MyPortal scrape failed: %s", e)

    return results
```

Then add it to the `scrapers` list in `run_pipeline()`:

```python
scrapers = [
    ("Scholarise.in",  scrape_scholarise),
    ("Buddy4Study",    scrape_buddy4study),
    ("NSP",            scrape_nsp),
    ("MyPortal",       scrape_my_new_source),   # ← Add here
]
```

### Adding Scholarships Manually

Add entries directly to `scholarships.json` following this schema:

```json
{
  "id":             "unique-kebab-case-id",
  "name":           "Full Scholarship Name",
  "amount":         "₹10,000",
  "deadline":       "2025-12-31",
  "eligibility":    "Brief eligibility description.",
  "link":           "https://apply.here.gov.in",
  "type":           "central",
  "categories":     ["SC", "ST"],
  "gender":         "all",
  "states":         ["All"],
  "qualifications": ["undergraduate"],
  "max_income":     250000,
  "min_marks":      60,
  "min_age":        null,
  "max_age":        null,
  "disability_only": false,
  "source":         "manual",
  "scraped_at":     "2025-05-02T00:00:00Z"
}
```

**Field reference:**

| Field | Type | Values |
|-------|------|--------|
| `type` | string | `"central"`, `"state"`, `"private"` |
| `categories` | array | `["General","OBC","SC","ST","EWS"]` (use `["All"]` for no restriction) |
| `gender` | string | `"all"`, `"male"`, `"female"`, `"transgender"` |
| `states` | array | State names, or `["All"]` for national |
| `qualifications` | array | `"class9"`,`"class10"`,`"class11"`,`"class12"`,`"diploma"`,`"undergraduate"`,`"postgraduate"`,`"phd"` |
| `max_income` | integer | Annual family income limit in ₹ (e.g. `250000` = ₹2.5L) |
| `min_marks` | float | Minimum percentage (e.g. `60.0`) |
| `disability_only` | boolean | `true` only for PWD-specific scholarships |

### Changing the Scrape Schedule

In `.github/workflows/update_scholarships.yml`, edit the cron line:

```yaml
# Current: daily at 00:30 IST (18:30 UTC)
- cron: "30 18 * * *"

# Every 12 hours (twice daily)
- cron: "30 6,18 * * *"

# Every Monday at midnight IST
- cron: "30 18 * * 0"
```

Use [crontab.guru](https://crontab.guru) to build cron expressions easily.

---

## Part 5 — Enabling Selenium for JS-Heavy Sites

Some portals render content via JavaScript. To use Selenium:

1. Uncomment the Selenium lines in `requirements.txt`:
   ```
   selenium>=4.21.0
   webdriver-manager>=4.0.1
   ```

2. Uncomment the Chrome setup block in the GitHub Actions workflow:
   ```yaml
   - name: Install Chrome (for Selenium)
     uses: browser-actions/setup-chrome@v1
   ```

3. Call the helper in your scraper function:
   ```python
   results = scrape_with_selenium("https://js-heavy-portal.gov.in/scholarships", "portal-name")
   ```

---

## Part 6 — Keeping Data Fresh Without Scraping

If a source blocks scraping entirely, you can maintain a **manually curated** JSON
and update it whenever new scholarships are announced. The `_nsp_static_fallback()`
function in `scraper.py` shows this pattern — it's a Python list you can edit directly.

Commit the updated `scholarships.json` and it goes live on GitHub Pages within 1 minute.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Site live but shows no results | Check browser console for 404 on `scholarships.json` — ensure file is in root |
| Scraper crashes on one source | Check `scraper.log` — errors are caught and logged per-source |
| GitHub Actions can't push | Go to Settings → Actions → General → enable **Read and write permissions** |
| Anti-bot block (403/429) | Increase `MIN_DELAY`/`MAX_DELAY` in `scraper.py`; add more User-Agents |
| Empty JSON after scrape | All sources may be blocked — add manual entries to `_nsp_static_fallback()` |
| Cards not showing on mobile | Ensure `style.css` and `script.js` paths are relative (no leading `/`) |
