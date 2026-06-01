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
import io
import json
import base64

import requests
import streamlit as st

# Barcode decoding runs locally (no API call). Imported defensively so the app
# still loads with a clear message if the pyzbar system library isn't present.
try:
    from PIL import Image
    from pyzbar.pyzbar import decode as _zbar_decode

    _PYZBAR_OK = True
except Exception:
    _PYZBAR_OK = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Bump this string on each meaningful change. It's shown at the bottom of the
# app so you can confirm at a glance which build Streamlit Cloud is running.
BUILD_VERSION = "barcode v3"

# Which Gemini model to use. "flash" models are fast and free-tier friendly.
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

# The instruction we send to the AI along with the photo. We ask it to reply
# in a strict JSON format so our code can read it reliably.
VISION_PROMPT = """You are an inventory-counting assistant for a warehouse.
Look at the photo and list EVERY individual physical object you can see as its
own separate entry — one entry per object. Do NOT aggregate or give counts;
each real object gets its own line.

Rules:
- Use simple, lowercase, singular names (e.g. "pen", "bottle", "screwdriver").
- For each object include a short "location" (e.g. "top-right cluster",
  "next to the left bottle") so you are forced to point at each real object.
- Each physical object must be listed EXACTLY ONCE. Assign it to the single
  best-fit category. Never list the same object under two different names.
- If you are unsure what an object is, pick your single best guess — do NOT
  hedge by listing it as multiple types.
- Only list physical objects, not the background, surfaces, body parts, or
  furniture.

Respond with ONLY valid JSON in exactly this format, nothing else:
{"items": [
  {"name": "pen", "location": "top-right cluster"},
  {"name": "pen", "location": "top-right cluster"},
  {"name": "screwdriver", "location": "next to the left bottle"},
  {"name": "bottle", "location": "left of center"}
]}
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
        # Ask Gemini to reply as JSON so it's easy to parse. temperature 0
        # makes it deterministic and less likely to second-guess / inflate counts.
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0,
        },
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
    # The prompt now returns one entry per physical object, so each entry counts
    # as 1. (We still honor an explicit "count" if one is ever present.)
    seen = {}
    for item in detected_items:
        name = str(item.get("name", "")).lower().strip()
        count = int(item.get("count", 1))
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


def load_barcode_map():
    """
    Optional map of barcode/QR value -> item name (barcodes.json).
    Returns {} if the file is missing. Keys starting with "_" are ignored
    (so we can keep comments in the JSON file).
    """
    try:
        with open("barcodes.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_")}


def decode_barcodes(image_bytes):
    """
    Find and decode every barcode / QR code in the image. Runs locally via
    pyzbar (no API call, no cost). Returns a list of {"data", "type"}.
    """
    img = Image.open(io.BytesIO(image_bytes))
    results = []
    for d in _zbar_decode(img):
        results.append(
            {
                "data": d.data.decode("utf-8", errors="replace"),
                "type": d.type,  # e.g. "QRCODE", "EAN13", "CODE128"
            }
        )
    return results


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Smart Inventory Scanner — MES Prototype", page_icon="📦")

st.title("Smart Inventory Scanner")
st.caption(
    "Take a photo of a shelf → AI identifies the items → the app flags anything "
    "below its minimum stock level and generates a re-order list."
)

# Load the catalog + optional barcode map once.
inventory = load_inventory()
barcode_map = load_barcode_map()

# Sidebar: show / let them inspect the tracked inventory.
with st.sidebar:
    st.header("Tracked inventory")
    st.caption("Minimum stock levels (edit inventory.json to change these).")
    st.json(inventory)

# Two ways to scan. Barcode mode runs locally (free, no Gemini API call); AI
# vision mode estimates counts of un-labeled items via Gemini.
mode = st.radio(
    "Mode",
    ["📦 Count items (AI vision)", "🔖 Scan barcode (local, free)"],
    horizontal=True,
    help="Barcode scanning runs on the server for free and does not use the Gemini API.",
)
count_mode = mode.startswith("📦")

st.subheader("1. Capture a photo")
if count_mode:
    st.caption(
        "Tip: photograph one bin / part-type at a time — AI vision nails "
        "*identifying* items but only *estimates* counts when they overlap."
    )
else:
    st.caption(
        "Point at a single barcode or QR code. Fill the frame, hold steady, and "
        "keep it well-lit for the cleanest read."
    )

photo = st.camera_input("Point your camera and take a picture")

# Also allow uploading an existing image (handy for demos / desktops).
uploaded = st.file_uploader(
    "…or upload a photo instead", type=["jpg", "jpeg", "png"]
)

image_file = photo or uploaded

if image_file is not None:
    image_bytes = image_file.getvalue()
    st.subheader("2. Analyze")

    # -----------------------------------------------------------------------
    # AI vision count path (requires a Gemini key)
    # -----------------------------------------------------------------------
    if count_mode:
        api_key = get_api_key()
        if not api_key:
            st.error(
                "No Gemini API key found. On Streamlit Cloud, add it under "
                "**Settings → Secrets** as `GEMINI_API_KEY = \"your-key\"`. "
                "Locally, set the `GEMINI_API_KEY` environment variable or create "
                "`.streamlit/secrets.toml`. (Barcode mode works without a key.)"
            )
            st.stop()

        if st.button("📸 Analyze this photo", type="primary"):
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
                st.warning(f"{len(to_order)} item(s) below minimum — re-order needed:")
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

    # -----------------------------------------------------------------------
    # Barcode scan path (local, free — no API call)
    # -----------------------------------------------------------------------
    else:
        if not _PYZBAR_OK:
            st.error(
                "Barcode library not available. Install it with "
                "`pip install pyzbar Pillow`. On Streamlit Cloud, the `packages.txt` "
                "file installs the required `libzbar0` system library automatically."
            )
            st.stop()

        if st.button("🔖 Scan for barcodes", type="primary"):
            codes = decode_barcodes(image_bytes)

            st.subheader("3. Results")
            if not codes:
                st.warning(
                    "No barcode or QR code found. Try a closer, sharper, well-lit "
                    "shot with the code filling more of the frame."
                )
            else:
                st.success(f"Found {len(codes)} code(s).")
                rows = []
                for c in codes:
                    item = barcode_map.get(c["data"])
                    rows.append(
                        {
                            "Barcode": c["data"],
                            "Type": c["type"],
                            "Matched item": item or "— not in catalog —",
                            "Min stock": inventory.get(item, "—") if item else "—",
                        }
                    )
                st.dataframe(rows, hide_index=True, use_container_width=True)

                unknown = [c["data"] for c in codes if c["data"] not in barcode_map]
                if unknown:
                    st.info(
                        "Tip: codes shown as “not in catalog” can be linked to an "
                        "item by adding them to `barcodes.json`."
                    )

                with st.expander("Raw decoded codes"):
                    st.json(codes)

# Build stamp — lets you verify which version Streamlit Cloud is serving.
st.divider()
st.caption(f"Build: {BUILD_VERSION}")
