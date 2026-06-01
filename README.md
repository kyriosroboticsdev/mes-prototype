#Smart Inventory Scanner — MES Prototype

Take a photo of a shelf → an AI identifies the items → the app flags anything
below its minimum stock level and generates a re-order list.

This is a **prototype** that demonstrates an image-based approach to the
manufacturing inventory / MES (Manufacturing Execution System) re-ordering
process.

---

## How it works (the 30-second version)

```
Browser camera  →  capture photo  →  Python server  →  Google Gemini (vision AI)
                                                              │
                            re-order list  ←  compare to minimums  ←  detected items
```

- **Browser** opens the camera and captures a still photo.
- **Python (Flask) server** receives the photo and keeps the secret API key safe.
- **Google Gemini** looks at the photo and lists the items it sees.
- The server compares detected counts against `inventory.json` (your minimum
  stock levels) and returns what needs to be ordered.

---

## Setup — step by step (Windows)

You only have to do steps 1–3 once.

### 1. Get a free Google Gemini API key
1. Go to <https://aistudio.google.com/app/apikey>
2. Sign in with a Google account.
3. Click **Create API key**. Copy the long string it gives you.

### 2. Install the Python libraries
Open **PowerShell**, then run:
```powershell
cd C:\Users\Kyrio\mes-prototype
pip install -r requirements.txt
```
(If `pip` isn't recognized, install Python from <https://python.org> first and
check "Add Python to PATH" during installation.)

### 3. Tell the app your API key
In the **same PowerShell window**, paste this (replace with your real key):
```powershell
$env:GEMINI_API_KEY = "paste-your-key-here"
```
> Note: this lasts only for the current PowerShell window. If you close it,
> run this line again before starting the app.

### 4. Start the app
```powershell
python app.py
```
You should see: `Starting MES prototype on http://localhost:5000`

### 5. Open it
Open your browser to <http://localhost:5000>, allow camera access, point it at
some objects, and click **📸 Capture & Analyze**.

---

## Testing tips for your demo

- **Photograph one bin/type at a time.** AI vision is excellent at *identifying*
  objects but only *estimates* counts when items overlap. One part-type per photo
  keeps counts accurate and makes a cleaner demo.
- Use objects that match `inventory.json` (pens, a bottle, scissors, a phone…).
- Edit `inventory.json` to change which items are tracked and their minimum
  quantities — no code changes needed.

## Using a phone camera (optional, looks great in a demo)
1. Make sure your phone and computer are on the **same Wi-Fi**.
2. Find your computer's IP: run `ipconfig` in PowerShell, look for "IPv4 Address"
   (e.g. `192.168.1.42`).
3. On your phone's browser go to `http://192.168.1.42:5000`.
   - Phone browsers sometimes block the camera on non-HTTPS sites. If so, demo on
     the laptop, or ask me to help set up an HTTPS tunnel (e.g. `ngrok`).

---

## Files in this project
| File | What it is |
|------|------------|
| `app.py` | The Python server (camera handling, calls Gemini, compares stock). |
| `inventory.json` | Your tracked items and their minimum quantities. |
| `static/index.html` | The web page layout. |
| `static/app.js` | Browser code: camera + sending photos + showing results. |
| `static/style.css` | Styling. |
| `requirements.txt` | The Python libraries to install. |

---

## Honest limitations (good to mention in an internship writeup)
- Counts are **estimates**, not exact — best with one item type per photo.
- A real deployment would replace `inventory.json` with the company's real MES /
  database, and "order needed" would create a real purchase order.
- For real use you'd add user logins, store a history of scans, and host it on a
  proper server with HTTPS.

These limitations are normal for a prototype — the point is to prove the concept
works end-to-end, which it does.
