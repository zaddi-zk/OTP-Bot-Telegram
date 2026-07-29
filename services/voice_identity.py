import random

VOICE_GENDER_MAP = {
    "Clara": "female",
    "Savannah": "female",
    "Emma": "female",
    "Layla": "female",
    "Naina": "female",
    "Godfrey": "male",
    "Elliot": "male",
    "Nico": "male",
    "Kai": "male",
    "Sagar": "male",
    "Neil": "male",
    "Sid": "male",
}

FEMALE_NAMES = [
    "Sarah", "Jessica", "Emma", "Olivia", "Sophia",
    "Isabella", "Mia", "Charlotte", "Amelia", "Harper",
    "Evelyn", "Abigail", "Emily", "Elizabeth", "Avery",
    "Sofia", "Ella", "Madison", "Scarlett", "Victoria",
    "Aria", "Grace", "Chloe", "Camila", "Penelope",
    "Riley", "Layla", "Zoe", "Nora", "Lily",
    "Hannah", "Lillian", "Addison", "Aubrey", "Ellie",
    "Stella", "Natalie", "Zoe", "Leah", "Hazel",
    "Violet", "Aurora", "Savannah", "Audrey", "Brooklyn",
    "Bella", "Claire", "Skylar", "Lucy", "Paisley",
]

MALE_NAMES = [
    "James", "David", "Michael", "Christopher", "Daniel",
    "Ethan", "Noah", "Liam", "Mason", "Logan",
    "Oliver", "Aiden", "Carter", "Jayden", "Owen",
    "Wyatt", "Hunter", "Jack", "Luke", "Dylan",
    "Evan", "Cole", "Chase", "Blake", "Jake",
    "Tyler", "Ryan", "Kyle", "Zack", "Caleb",
    "Nathan", "Aaron", "Adam", "Eric", "Mark",
    "Andrew", "Thomas", "Kevin", "Brian", "Matthew",
    "Benjamin", "Ryan", "Nathan", "Samuel", "Joseph",
    "Henry", "William", "Alexander", "Sebastian", "Daniel",
]

INDIAN_FEMALE_NAMES = [
    "Priya", "Anjali", "Kavya", "Meera", "Naina",
    "Maya", "Sneha", "Riya", "Asha", "Leela",
    "Neha", "Shreya", "Tanvi", "Isha", "Ananya",
]

INDIAN_MALE_NAMES = [
    "Arjun", "Vikram", "Ravi", "Anish", "Karan",
    "Rahul", "Amit", "Sanjay", "Raj", "Deepak",
    "Ajay", "Sunil", "Manoj", "Pradeep", "Suresh",
    "Sagar", "Vikas", "Nitin", "Rohan", "Akash",
]


def _resolve_canonical_voice_id(voice_id: str) -> str:
    from config import LEGACY_VOICE_ID_MAP
    mapped = LEGACY_VOICE_ID_MAP.get(voice_id)
    return mapped if mapped else voice_id


def select_agent_name(voice_id: str) -> str:
    if not voice_id:
        voice_id = "Clara"

    canonical = _resolve_canonical_voice_id(voice_id)
    gender = VOICE_GENDER_MAP.get(canonical)

    if gender == "female":
        if canonical == "Naina":
            pool = INDIAN_FEMALE_NAMES
        else:
            pool = FEMALE_NAMES
    elif gender == "male":
        if canonical in ("Sagar",):
            pool = INDIAN_MALE_NAMES
        else:
            pool = MALE_NAMES
    else:
        return canonical

    return random.choice(pool)
