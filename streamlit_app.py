"""
MES Image-Inventory Prototype — Streamlit version
--------------------------------------------------
Same idea as app.py, but as a single Streamlit app so it deploys to
Streamlit Cloud for free (with HTTPS, so the camera works on phones too).

What it does:
  1. Shows a camera widget in the browser (st.camera_input).
  2. Sends the captured photo to Google Gemini (a vision AI) and asks
     "what items are here?".
  3. Compares what Gemini found against minimum stock levels (inventory.json).
  4. Shows a table of items that need to be re-ordered.

Run locally:
    streamlit run streamlit_app.py

The Gemini API key is read from Streamlit secrets (st.secrets) or, as a
fallback, the GEMINI_API_KEY environment variable. See README for setup.
"""

import os
import json
import base64

import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

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


def get_api_key():
    """
    Read the Gemini API key. On Streamlit Cloud you set this under
    Settings -> Secrets. Locally you can use .streamlit/secrets.toml or the
    GEMINI_API_KEY environment variable.
    """
    # st.secrets raises if there is no secrets file at all, so guard it.
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    return os.environ.get("GEMINI_API_KEY", "")


# ---------------------------------------------------------------------------
# Helper functions (ported from app.py, unchanged logic)
# ---------------------------------------------------------------------------

def load_inventory():
    """Read the minimum-stock list from inventory.json."""
    with open("inventory.json", "r", encoding="utf-8") as f:
        return json.load(f)


def ask_gemini(image_bytes, api_key):
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
        params={"key": api_key},
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
# Streamlit UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Smart Inventory Scanner — MES Prototype", page_icon="📦")

st.title("Smart Inventory Scanner")
st.caption(
    "Take a photo of a shelf → AI identifies the items → the app flags anything "
    "below its minimum stock level and generates a re-order list."
)

api_key = get_api_key()
if not api_key:
    st.error(
        "No Gemini API key found. On Streamlit Cloud, add it under "
        "**Settings → Secrets** as `GEMINI_API_KEY = \"your-key\"`. "
        "Locally, set the `GEMINI_API_KEY` environment variable or create "
        "`.streamlit/secrets.toml`."
    )
    st.stop()

# Sidebar: show / let them inspect the tracked inventory.
inventory = load_inventory()
with st.sidebar:
    st.header("Tracked inventory")
    st.caption("Minimum stock levels (edit inventory.json to change these).")
    st.json(inventory)

st.subheader("1. Capture a photo")
st.caption(
    "Tip: photograph one bin / part-type at a time — AI vision nails *identifying* "
    "items but only *estimates* counts when they overlap."
)

photo = st.camera_input("Point your camera at some items and take a picture")

# Also allow uploading an existing image (handy for demos / desktops).
uploaded = st.file_uploader(
    "…or upload a photo instead", type=["jpg", "jpeg", "png"]
)

image_file = photo or uploaded

if image_file is not None:
    st.subheader("2. Analyze")
    if st.button("📸 Analyze this photo", type="primary"):
        image_bytes = image_file.getvalue()
        with st.spinner("Asking Gemini what it sees…"):
            try:
                detected = ask_gemini(image_bytes, api_key)
            except requests.HTTPError as e:
                st.error(f"Gemini API error: {e.response.text}")
                st.stop()
            except Exception as e:
                st.error(f"Something went wrong: {e}")
                st.stop()

        report = compare_to_inventory(detected, inventory)

        st.subheader("3. Results")

        # Re-order list first — that's the point of the tool.
        to_order = [r for r in report if r["needs_order"]]
        if to_order:
            st.warning(f" {len(to_order)} item(s) below minimum — re-order needed:")
            st.dataframe(
                [
                    {
                        "Item": r["item"],
                        "Minimum": r["minimum"],
                        "On hand": r["on_hand"],
                        "Order qty": r["order_qty"],
                    }
                    for r in to_order
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.success("Everything is at or above its minimum stock level.")

        with st.expander("Full stock report (all tracked items)"):
            st.dataframe(
                [
                    {
                        "Item": r["item"],
                        "Minimum": r["minimum"],
                        "On hand": r["on_hand"],
                        "Order qty": r["order_qty"],
                        "Needs order": r["needs_order"],
                    }
                    for r in report
                ],
                hide_index=True,
                use_container_width=True,
            )

        with st.expander("Raw items Gemini detected"):
            st.json(detected)
