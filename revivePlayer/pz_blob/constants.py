"""Shared constants for Project Zomboid player blob parsing."""

# 24 ordered stats as of current version
STAT_NAMES = [
    "Anger", "Boredom", "Discomfort", "Endurance", "Fatigue", "Fitness",
    "FoodSickness", "Hunger", "Idleness", "Intoxication", "Morale",
    "NicotineWithdrawal", "Pain", "Panic", "Poison", "Sanity", "Sickness",
    "Stress", "Temperature", "Thirst", "Unhappiness", "Wetness",
    "ZombieFever", "ZombieInfection"
]

# 17 body parts (index 0-16), MAX=17
BODY_PART_NAMES = [
    "Hand_L", "Hand_R", "ForeArm_L", "ForeArm_R",
    "UpperArm_L", "UpperArm_R", "Torso_Upper", "Torso_Lower",
    "Head", "Neck", "Groin",
    "UpperLeg_L", "UpperLeg_R", "LowerLeg_L", "LowerLeg_R",
    "Foot_L", "Foot_R"
]
NUM_BODY_PARTS = 17

# Stats that are relevant to death diagnostics
DEATH_RELEVANT_STATS = {
    "ZombieFever", "ZombieInfection", "Pain", "Sickness", "Poison",
    "FoodSickness", "Endurance", "Fatigue", "Hunger", "Thirst"
}

# Body part damage modifiers for overallBodyHealth calculation
# From BodyPartType.java:277-316
DAMAGE_MODIFIERS = [
    0.1, 0.1, 0.2, 0.2, 0.3, 0.3, 0.35, 0.4,
    0.6, 0.7, 0.4, 0.3, 0.3, 0.2, 0.2, 0.2, 0.2
]
