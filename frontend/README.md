# Coachin frontend

Streamlit multipage app. Talks to the backend only over HTTP (`client/api_client.py`), so it
has no dependency on backend code.

## Layout

```
frontend/
├── app.py              Entry point / dashboard
├── config.py           BACKEND_URL etc. from the root .env
├── client/
│   └── api_client.py   CoachinClient: one method per backend endpoint
├── components/
│   ├── auth.py         Login/register form, session-state token handling
│   ├── voice.py        Microphone capture (st.audio_input) and TTS playback
│   ├── charts.py       Plotly progress charts
│   └── safety.py       Safety banners and medical disclaimer
└── pages/              Sidebar pages (numeric prefix sets order)
    ├── 1_Coach.py      Voice/text chat with the coach
    ├── 2_Program.py    Weekly program view + generation
    ├── 3_Workouts.py   Log sessions, overload targets, exercise history
    ├── 4_Nutrition.py  Meal logging with LLM macro estimates
    ├── 5_Progress.py   Body metrics and monthly reports
    └── 6_Profile.py    Onboarding / profile settings
```

## Running

```bash
pip install -r requirements.txt
streamlit run app.py        # from frontend/ (or: streamlit run frontend/app.py from root)
```

The backend must be running at `BACKEND_URL` (default `http://localhost:8000`).
Microphone recording needs the page served from `localhost` or HTTPS.
