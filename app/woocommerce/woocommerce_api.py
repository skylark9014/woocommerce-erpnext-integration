# =============================
# WooCommerce API Helper Functions
# =============================

import os
from dotenv import load_dotenv
load_dotenv()

import base64
from typing import Any, Dict
import httpx
import logging
 
WC_BASE_URL = os.getenv("WC_BASE_URL")
WC_API_KEY = os.getenv("WC_API_KEY")
WC_API_SECRET = os.getenv("WC_API_SECRET")

if not all([WC_BASE_URL, WC_API_KEY, WC_API_SECRET]):
    raise RuntimeError("Missing WooCommerce API credentials in .env")


def wc_get(path: str, params: dict = None):
    url = f"{WC_BASE_URL}/wp-json/wc/v3/{path}"
    auth = (WC_API_KEY, WC_API_SECRET)
    r = httpx.get(url, params=params or {}, auth=auth)
    r.raise_for_status()
    return r.json()


def wc_post(path: str, data: dict):
    url = f"{WC_BASE_URL}/wp-json/wc/v3/{path}"
    auth = (WC_API_KEY, WC_API_SECRET)
    r = httpx.post(url, json=data, auth=auth)
    r.raise_for_status()
    return r.json()


def wc_put(path: str, data: dict):
    url = f"{WC_BASE_URL}/wp-json/wc/v3/{path}"
    auth = (WC_API_KEY, WC_API_SECRET)
    r = httpx.put(url, json=data, auth=auth)
    r.raise_for_status()
    return r.json()


def wc_delete(path: str):
    url = f"{WC_BASE_URL}/wp-json/wc/v3/{path}?force=true"
    auth = (WC_API_KEY, WC_API_SECRET)
    r = httpx.delete(url, auth=auth)
    r.raise_for_status()
    return r.json()


# Short aliases
wc_create = wc_post
wc_update = wc_put

