# LeadsEngine AI (Free & Open Source Edition) 🚀

Ek complete, high-performance B2B Lead Generation aur Cold Outreach platform jo `challenge.leadsengine.ai` ki tarah natural language prompts se leads nikalta hai, websites crawl karke emails & phone numbers extract karta hai, MX handshake se verify karta hai, AI se pitch hooks generate karta hai, aur 3-layer tracking ke sath email campaigns bhejta hai.

---

## 🌟 Features (Phase 1: 100% Free Stack)

1. **AI Natural Language Hunter:**
   * Likhein: *"Roofing contractors in Dallas Texas"* ya *"Dentists in Miami FL"*.
   * Engine automatically target location, niche, aur service keywords detect karta hai.
2. **Google Maps & Local Business Scraping (Playwright Headless):**
   * Business name, rating, reviews count, category, website, phone number direct Google Maps se pull karta hai (Bina kisi paid API key ke).
3. **Deep Website Contact Hunter:**
   * Scraped business ki website ke `/about`, `/contact`, `/team`, aur homepage ko crawl karke direct verified emails, phone numbers, aur social profiles (LinkedIn, Instagram, Facebook, Twitter) nikalta hai.
4. **Direct SMTP Handshake Email Verification:**
   * DNS MX lookup + SMTP `RCPT TO` handshake se 100% free verify karta hai ke mailbox exist karta hai ya nahi.
5. **AI Lead Scoring & Pitch Hooks:**
   * Har lead ko 0-100 score deta hai aur customized 2-line cold outreach hook generate karta hai.
6. **3-Layer Outreach & Tracking:**
   * Layer 1: Deliverability check.
   * Layer 2: 1x1 transparent open tracking pixel (`/api/track/open/{id}`).
   * Layer 3: Click redirection wrapper (`/api/track/click/{id}?url=...`).
7. **Instant Exports:**
   * One-click download in CSV ya Excel (`.xlsx`).

---

## ⚡ Quick Start (Chalane Ka Tareeqa)

### 1. Requirements
Python 3.10+ installed hona chahiye (Chromium browser Playwright ke sath already setup hai).

### 2. Run Karein
Sirf ye command chalayein:
```bash
python run.py
```
Ya simply `start.bat` par double-click karein!

### 3. Open Dashboard
Browser me jayein:
👉 **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

---

## ⚙️ Configuration (.env)

* **GEMINI_API_KEY (Optional):** [Google AI Studio](https://aistudio.google.com/) se free Gemini key nikal kar `.env` me daal sakte hain (1,500 free requests daily). Agar key na bhi ho, built-in intelligent AI heuristics automatically prompt parse karega!
* **SMTP_USER & SMTP_PASSWORD (Optional):** Agar Gmail ya Brevo se real cold emails send karni hon to `.env` me SMTP credentials daal dein. Agar ye blank rahega to system **Simulation / Preview Mode** me chalega taake aap bina kisi risk ke test kar sakein.

---

## 🚀 Upgrade Path: Free se Paid SaaS Tak

Jab aap is free engine se pehli deals close karke revenue generate karein:
1. **Apify B2B Database Integration:** Apify actor (`lead-scraper-apollo-zoominfo-lusha`) connect karein for 250M+ Apollo decision-maker direct dials.
2. **Dedicated Domains:** Cold email outreach ke liye dedicated secondary domains (.co, .io) add karein.
3. **Stripe Checkout:** `$9.99` tripwire offer ya monthly subscription connect karein.
