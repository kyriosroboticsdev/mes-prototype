"""
MES Image-Inventory Prototype
--------------------------------
A tiny web server that:
  1. Serves a web page that opens your camera.
  2. Receives a captured photo from the browser.
  3. Sends the photo to Google Gemini (a vision AI) and asks "what items are here?".
  4. Compares what Gemini found against minimum stock levels (inventory.json).
  5. Returns a list of items that need to be re-ordered.

Beginner notes:
  - "Flask" is a small library that turns Python into a web server.
  - A "route" (like @app.route("/analyze")) is a URL the browser can talk to.
  - Your secret API key stays HERE on the server, never in the browser. That's the
    main reason we use a Python server instead of a plain HTML file.
"""

import os
import json
import base64

import requests
from flask import Flask, request, jsonify, send_from_directory

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Your Gemini API key is read from an environment variable so it never gets
# written into the code (and never accidentally shared on GitHub).
# You will set this before running the app (the README explains how).
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Which Gemini model to use. "flash" models are fast and free-tier friendly.
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

# The instruction we send to the AI along with the photo. We ask it to reply
# in a strict JSON format so our code can read it reliably.
VISION_PROMPT = """You are an inventory-counting assistant for a warehouse.
Look at the photo and list every distinct type of object you can see, with an
approximate count of how many of each there are.

Rules:
- Use simple, lowercase, singular names (e.g. "pen", "bottle", "screwdriver").
- If items are stacked or overlapping and you cannot count exactly, give your
  best estimate.
- Only list physical objects, not the background or surfaces.

Respond with ONLY valid JSON in exactly this format, nothing else:
{"items": [{"name": "pen", "count": 3}, {"name": "bottle", "count": 1}]}
"""

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def load_inventory():
    """Read the minimum-stock list from inventory.json."""
    with open("inventory.json", "r", encoding="utf-8") as f:
        return json.load(f)


def ask_gemini(image_bytes):
    """Send the photo to Gemini and return the parsed list of detected items."""
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": VISION_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_b64,
                        }
                    },
                ]
            }
        ],
        # Ask Gemini to reply as JSON so it's easy to parse.
        "generationConfig": {"response_mime_type": "application/json"},
    }

    response = requests.post(
        GEMINI_URL,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()

    # Dig the text answer out of Gemini's response structure.
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(text)
    return parsed.get("items", [])


def compare_to_inventory(detected_items, inventory):
    """
    Compare what the camera saw against the minimum stock levels.

    Returns a list of rows describing each tracked item: how many we need,
    how many we saw, and how many to order.
    """
    # Build a quick lookup of detected counts by name (lowercased).
    seen = {}
    for item in detected_items:
        name = str(item.get("name", "")).lower().strip()
        count = int(item.get("count", 0))
        seen[name] = seen.get(name, 0) + count

    rows = []
    for tracked_name, minimum in inventory.items():
        key = tracked_name.lower().strip()

        # Match if the tracked name appears in a detected name or vice-versa,
        # so "bottle" matches "water bottle", etc.
        on_hand = 0
        for seen_name, seen_count in seen.items():
            if key in seen_name or seen_name in key:
                on_hand += seen_count

        order_qty = max(0, minimum - on_hand)
        rows.append(
            {
                "item": tracked_name,
                "minimum": minimum,
                "on_hand": on_hand,
                "order_qty": order_qty,
                "needs_order": order_qty > 0,
            }
        )

    return rows


# ---------------------------------------------------------------------------
# Web routes
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    """Serve the main web page."""
    return send_from_directory("static", "index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    """Serve the CSS and JavaScript files."""
    return send_from_directory("static", filename)


@app.route("/analyze", methods=["POST"])
def analyze():
    """Receive a photo from the browser, run the full analysis, return results."""
    if not GEMINI_API_KEY:
        return jsonify({"error": "No GEMINI_API_KEY set on the server."}), 500

    body = request.get_json(silent=True) or {}
    image_data_url = body.get("image", "")

    # The browser sends the image as a "data URL" like "data:image/jpeg;base64,...."
    # We strip the prefix and decode the base64 part into raw bytes.
    if "," in image_data_url:
        image_data_url = image_data_url.split(",", 1)[1]

    try:
        image_bytes = base64.b64decode(image_data_url)
    except Exception:
        return jsonify({"error": "Could not read the image."}), 400

    try:
        detected = ask_gemini(image_bytes)
    except requests.HTTPError as e:
        return jsonify({"error": f"Gemini API error: {e.response.text}"}), 502
    except Exception as e:
        return jsonify({"error": f"Something went wrong: {e}"}), 500

    inventory = load_inventory()
    report = compare_to_inventory(detected, inventory)

    return jsonify({"detected": detected, "report": report})


if __name__ == "__main__":
    # debug=True auto-reloads when you edit the code. host=0.0.0.0 lets your
    # phone reach it over Wi-Fi if you want to test with a phone camera.
    print("Starting MES prototype on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
