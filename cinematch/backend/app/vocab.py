"""
Shared vocabularies (CONTRACT section 4). The ml/ pipeline uses exactly the
same strings, so never rename these values.
"""

GENRES = [
    "Action", "Adventure", "Animation", "Children", "Comedy", "Crime", "Documentary",
    "Drama", "Fantasy", "Film-Noir", "Horror", "IMAX", "Musical", "Mystery", "Romance",
    "Sci-Fi", "Thriller", "War", "Western",
]

EMOTIONS = ["joy", "sadness", "fear", "anger", "surprise", "disgust", "neutral"]
EMOTION_LABELS = {
    "joy": "Happy", "sadness": "Sad", "fear": "Tense", "anger": "Angry",
    "surprise": "Surprised", "disgust": "Disturbed", "neutral": "Calm",
}
# Positive / negative feeling of each emotion. Used to give partial credit
# (e.g. user wants "joy" at the end, item ends in "surprise" -> half a match).
EMOTION_VALENCE = {
    "joy": 1, "surprise": 1, "neutral": 0,
    "sadness": -1, "fear": -1, "anger": -1, "disgust": -1,
}

ARCS = ["rise", "fall", "fall-rise", "rise-fall", "steady"]

MOOD_TAGS = [
    "feel-good", "dark", "cozy", "thrilling", "romantic", "mind-bending", "epic", "heartwarming",
    "scary", "funny", "inspiring", "melancholic", "action-packed", "family", "slow-burn", "light",
]

WEATHER = ["sunny", "cloudy", "rainy", "stormy", "snowy", "foggy", "hot", "cold"]
WEATHER_INFO = {
    "sunny": ("Sunny", "☀️"),
    "cloudy": ("Cloudy", "☁️"),
    "rainy": ("Rainy", "🌧️"),
    "stormy": ("Stormy", "⛈️"),
    "snowy": ("Snowy", "❄️"),
    "foggy": ("Foggy", "🌫️"),
    "hot": ("Hot", "🔥"),
    "cold": ("Cold", "🥶"),
}

TIME_OF_DAY = ["morning", "afternoon", "evening", "night", "late_night"]
TIME_OF_DAY_WORDS = {  # used in reason strings: "Perfect for a rainy evening"
    "morning": "morning", "afternoon": "afternoon", "evening": "evening",
    "night": "night", "late_night": "late night",
}

TIME_AVAILABLE_MIN = [30, 60, 90, 120, 150, 180, None]

OCCASIONS = [
    "date_night", "family_night", "friends_hangout", "solo_chill", "kids_time",
    "late_night_thrills", "rainy_day_in", "weekend_binge",
]
OCCASION_INFO = {
    "date_night": ("Date night", "💕"),
    "family_night": ("Family night", "👨‍👩‍👧"),
    "friends_hangout": ("Friends hangout", "🍕"),
    "solo_chill": ("Solo chill", "🛋️"),
    "kids_time": ("Kids time", "🧸"),
    "late_night_thrills": ("Late-night thrills", "🌙"),
    "rainy_day_in": ("Rainy day in", "☔"),
    "weekend_binge": ("Weekend binge", "📺"),
}

FESTIVALS = [
    "diwali", "holi", "navratri", "eid", "christmas", "new_year", "halloween", "valentines",
    "raksha_bandhan", "independence_day", "onam", "pongal", "thanksgiving",
]
FESTIVAL_INFO = {
    "diwali": ("Diwali", "🪔"),
    "holi": ("Holi", "🎨"),
    "navratri": ("Navratri", "💃"),
    "eid": ("Eid", "🌙"),
    "christmas": ("Christmas", "🎄"),
    "new_year": ("New Year", "🎆"),
    "halloween": ("Halloween", "🎃"),
    "valentines": ("Valentine's Day", "💘"),
    "raksha_bandhan": ("Raksha Bandhan", "🧵"),
    "independence_day": ("Independence Day", "🇮🇳"),
    "onam": ("Onam", "🌼"),
    "pongal": ("Pongal", "🍚"),
    "thanksgiving": ("Thanksgiving", "🦃"),
}

AGE_RATINGS = ["U", "UA 7+", "UA 13+", "UA 16+", "A"]  # ordered, "max" means <= that bucket
FRANCHISE_MODE = ["any", "only", "exclude"]
CONTENT_TYPE = ["any", "movie", "series"]

# Human names for ISO 639-1 language codes (TMDB also uses "cn" for Cantonese
# and "xx" for "no language"). Unknown codes are shown in upper case.
LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "ta": "Tamil", "te": "Telugu", "ml": "Malayalam",
    "kn": "Kannada", "bn": "Bengali", "mr": "Marathi", "pa": "Punjabi", "gu": "Gujarati",
    "ur": "Urdu", "ko": "Korean", "ja": "Japanese", "zh": "Chinese (Mandarin)",
    "cn": "Chinese (Cantonese)", "fr": "French", "es": "Spanish", "de": "German",
    "it": "Italian", "pt": "Portuguese", "ru": "Russian", "sv": "Swedish", "da": "Danish",
    "no": "Norwegian", "nb": "Norwegian", "fi": "Finnish", "nl": "Dutch", "pl": "Polish",
    "tr": "Turkish", "fa": "Persian", "ar": "Arabic", "he": "Hebrew", "th": "Thai",
    "id": "Indonesian", "tl": "Tagalog", "cs": "Czech", "hu": "Hungarian", "el": "Greek",
    "ro": "Romanian", "uk": "Ukrainian", "vi": "Vietnamese", "ms": "Malay", "is": "Icelandic",
    "et": "Estonian", "sr": "Serbian", "hr": "Croatian", "bs": "Bosnian", "ka": "Georgian",
    "xx": "No language",
}
INDIAN_LANGUAGES = ["hi", "ta", "te", "ml", "kn", "bn", "mr", "pa", "gu", "ur"]


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code.upper() if code else "Unknown")


def time_of_day_for_hour(hour: int) -> str:
    """CONTRACT: morning 5–11, afternoon 12–16, evening 17–20, night 21–23, late_night 0–4."""
    hour = int(hour) % 24
    if 5 <= hour <= 11:
        return "morning"
    if 12 <= hour <= 16:
        return "afternoon"
    if 17 <= hour <= 20:
        return "evening"
    if 21 <= hour <= 23:
        return "night"
    return "late_night"
