from enum import Enum

class StateEnum(Enum):
    CLASSIFY = "classify"
    OTHER = "other"
    # Incident lifecycle states
    ESCALATION = "escalation"
    RUNBOOK_LOOKUP = "runbook_lookup"
    COMMS_DRAFTING = "comms_drafting"
    POSTMORTEM = "postmortem"

class SharedState:
    def __init__(self):
        self.value = StateEnum.CLASSIFY
