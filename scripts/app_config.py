"""European competition allowlist for this public distribution."""
EUROPE = ("PL", "BL1", "PD", "SA", "FL1", "CL")
def enabled_competitions(environment="public", source=None):
    if environment not in ("local", "public"):
        raise ValueError("unknown environment")
    return EUROPE
def filter_data(data, competitions):
    result = {"updatedAt": data.get("updatedAt"), "competitions": {c:v for c,v in data["competitions"].items() if c in competitions}}
    for key in ("standings", "competitionUpdatedAt"):
        if key in data: result[key] = {c:v for c,v in data[key].items() if c in competitions}
    return result
def filter_status(status, competitions):
    result = {"schemaVersion":status["schemaVersion"], "competitions":{c:v for c,v in status["competitions"].items() if c in competitions}}
    if "lastAttemptAt" in status: result["lastAttemptAt"] = status["lastAttemptAt"]
    return result
