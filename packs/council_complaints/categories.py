"""Issue categories for the council complaints pack.

core/schema.py keeps Issue.category as a plain string. This list is the
council-specific vocabulary, so it lives in the pack (governance rule 7).
"""

CATEGORIES: frozenset[str] = frozenset(
    {
        "housing_repairs",     # council-owned homes: damp, leaks, heating, structure
        "homelessness",        # emergency and temporary accommodation
        "waste_recycling",     # bin collections, assisted collections
        "street_cleansing",    # litter, fly-tipping
        "highways",            # roads, pavements, potholes
        "parking",             # penalty charge notices, signage
        "council_tax",         # bills, discounts, enforcement
        "noise_asb",           # noise nuisance, anti-social behaviour
        "adult_social_care",   # assessments and care for adults
        "children_services",   # children in need, family support
        "equality_access",     # disability adjustments, accessible formats
        "information_request", # FOI and data requests
        "complaint_handling",  # complaints ignored, late or closed without contact
        "staff_conduct",       # rudeness, turning people away
        "parks_open_spaces",   # parks, benches, play areas
        "general_feedback",    # websites, opening hours, minor suggestions
    }
)
