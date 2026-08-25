"""Manifest of openly-licensed real badminton footage used for CV testing.

Every entry is hosted on Wikimedia Commons under a licence that explicitly
permits download and reuse (CC0, public domain, CC BY, or CC BY-SA). The files
themselves are NOT committed — they are fetched on demand and gitignored.

Attribution for each clip is reproduced in
`docs/evidence/real-footage-attribution.md`, which the fetch script regenerates
so the CC BY / CC BY-SA attribution requirement is actually satisfied rather
than assumed.

Explicitly excluded: BWF broadcast footage and any other rights-reserved match
video. Downloading it would breach both the platform terms and the licence.
`docs/BWF_MANUAL_TEST_PROTOCOL.md` covers that footage observationally instead.
"""
from pathlib import Path

FOOTAGE_DIR = Path("/tmp/bc-real")

BASE = "https://upload.wikimedia.org/wikipedia/commons"

FOOTAGE = [
    {
        "key": "school_training",
        "file": "Badminton_in_school,_2009.webm",
        "url": f"{BASE}/7/79/Badminton_in_school%2C_2009.webm",
        "page": "https://commons.wikimedia.org/wiki/File:Badminton_in_school,_2009.webm",
        "scenario": "Indoor school/recreational play, fixed camera, multiple people in frame",
        "licence": "CC0",
    },
    {
        "key": "club_competition",
        "file": "Badmington_competition_EuroGames_Bern_2023.webm",
        "url": f"{BASE}/5/51/Badmington_competition_EuroGames_Bern_2023.webm",
        "page": "https://commons.wikimedia.org/wiki/File:Badmington_competition_EuroGames_Bern_2023.webm",
        "scenario": "Club-level competition, handheld side angle",
        "licence": "CC BY-SA 4.0",
    },
    {
        "key": "competition_long",
        "file": "Badmington_Competition_EuroGames_2_2023_Bern.webm",
        "url": f"{BASE}/4/40/Badmington_Competition_EuroGames_2_2023_in_Wankdork%2C_Bern.webm",
        "page": "https://commons.wikimedia.org/wiki/File:Badmington_Competition_EuroGames_2_2023_in_Wankdork,_Bern.webm",
        "scenario": "Longer club competition sequence, multiple rallies",
        "licence": "CC BY-SA 4.0",
    },
    {
        "key": "championship_point",
        "file": "Zmagovalna_tocka_Kaje_Stankovic.webm",
        "url": f"{BASE}/f/f2/Zmagovalna_to%C4%8Dka_Kaje_Stankovi%C4%87_za_tretji_naslov_slovenske_prvakinje.webm",
        "page": "https://commons.wikimedia.org/wiki/File:Zmagovalna_to%C4%8Dka_Kaje_Stankovi%C4%87_za_tretji_naslov_slovenske_prvakinje.webm",
        "scenario": "National championship match point, competitive singles",
        "licence": "CC BY 3.0",
    },
    {
        "key": "demonstration",
        "file": "Demonstratie_badminton.webm",
        "url": f"{BASE}/5/5f/Demonstratie_badminton.webm",
        "page": "https://commons.wikimedia.org/wiki/File:Demonstratie_badminton.webm",
        "scenario": "Archival badminton demonstration footage",
        "licence": "Public domain",
    },
    {
        "key": "elite_broadcast",
        "file": "Wang_Zhiyi_China_Open_2025.webm",
        "url": f"{BASE}/2/2f/Wang_Zhiyi_triumph_in_all-Chinese_China_Open_finals_I_China_Open_2025.webm",
        "page": "https://commons.wikimedia.org/wiki/File:Wang_Zhiyi_triumph_in_all-Chinese_China_Open_finals_I_China_Open_2025.webm",
        "scenario": "Elite tour-level singles, broadcast camera angle (China Open 2025)",
        "licence": "CC BY 3.0",
    },
]
