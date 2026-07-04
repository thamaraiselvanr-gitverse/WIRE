from typing import Any, Dict, Literal

from pydantic import BaseModel, Field, field_validator


class SlotConstraint(BaseModel):
    allowed_types: list[str]
    max_length: int | None = None
    max_width: int | None = None
    max_height: int | None = None


class DataSlot(BaseModel):
    id: str
    type: Literal["text", "image", "video", "audio", "document"]
    constraint: SlotConstraint
    required: bool = False
    fallback: Any | None = None


class InputBlueprint(BaseModel):
    schema_version: str = "1.0"
    slots: Dict[str, DataSlot] = Field(default_factory=dict)

    @field_validator("slots")
    def validate_slots(cls, v):
        for slot_id, slot in v.items():
            if slot.id != slot_id:
                raise ValueError(f"Slot ID mismatch: {slot.id} != {slot_id}")
        return v

    def validate_input(
        self, slot_id: str, value: Any, strict: bool = True
    ) -> Dict[str, Any]:
        """
        Validates a user-provided value against slot constraints.
        Returns:
            dict: {
                "valid": bool,
                "severity": "hard" | "soft" | None,
                "message": str
            }
        """
        slot = self.slots.get(slot_id)
        if not slot:
            return {
                "valid": False,
                "severity": "hard" if strict else "soft",
                "message": f"Slot '{slot_id}' not found in blueprint.",
            }

        # Hard validations:
        # 1. Required field check (missing / None / empty string / empty list)
        if slot.required:
            if (
                value is None
                or value == ""
                or (isinstance(value, list) and len(value) == 0)
            ):
                return {
                    "valid": False,
                    "severity": "hard",
                    "message": f"Required slot '{slot_id}' is missing or empty.",
                }

        # Optional slots left empty:
        if value is None or value == "":
            return {
                "valid": True,
                "severity": "soft",
                "message": f"Optional slot '{slot_id}' is empty.",
            }

        # 2. Type mismatch:
        if slot.type == "text":
            if not isinstance(value, str):
                return {
                    "valid": False,
                    "severity": "hard",
                    "message": f"Type mismatch: slot '{slot_id}' expected text, got {type(value).__name__}.",
                }
        elif slot.type == "image":
            if not isinstance(value, (str, dict)):
                return {
                    "valid": False,
                    "severity": "hard",
                    "message": f"Type mismatch: slot '{slot_id}' expected image reference, got {type(value).__name__}.",
                }
            if isinstance(value, str) and (
                "placeholder" in value.lower() or "default" in value.lower()
            ):
                return {
                    "valid": True,
                    "severity": "soft",
                    "message": f"Slot '{slot_id}' contains a placeholder image value: '{value}'.",
                }
        elif slot.type in ("video", "audio", "document"):
            if not isinstance(value, str):
                return {
                    "valid": False,
                    "severity": "hard",
                    "message": f"Type mismatch: slot '{slot_id}' expected media/document path/URL, got {type(value).__name__}.",
                }

        # Soft validations:
        # 3. Length bounds for text:
        if slot.type == "text" and isinstance(value, str):
            max_len = slot.constraint.max_length
            if max_len is not None and len(value) > max_len:
                return {
                    "valid": True,
                    "severity": "soft",
                    "message": f"Text in slot '{slot_id}' length ({len(value)}) exceeds recommended limit ({max_len}).",
                }
            if "lorem ipsum" in value.lower() or "placeholder" in value.lower():
                return {
                    "valid": True,
                    "severity": "soft",
                    "message": f"Slot '{slot_id}' text contains placeholder pattern: '{value[:30]}...'.",
                }

        # 4. Image dimensions validation:
        if slot.type == "image" and isinstance(value, dict):
            w = value.get("width")
            h = value.get("height")
            max_w = slot.constraint.max_width
            max_h = slot.constraint.max_height
            if max_w and w and w > max_w:
                return {
                    "valid": True,
                    "severity": "soft",
                    "message": f"Image in slot '{slot_id}' width ({w}) exceeds recommended limit ({max_w}).",
                }
            if max_h and h and h > max_h:
                return {
                    "valid": True,
                    "severity": "soft",
                    "message": f"Image in slot '{slot_id}' height ({h}) exceeds recommended limit ({max_h}).",
                }

        return {
            "valid": True,
            "severity": None,
            "message": f"Slot '{slot_id}' validates successfully.",
        }

    def generate_summary_report(
        self, inputs: Dict[str, Any], strict: bool = True
    ) -> Dict[str, Any]:
        """
        Validates all inputs and aggregates them into a structured report.
        """
        report = {
            "is_valid": True,
            "hard_failures": [],
            "soft_warnings": [],
            "successes": [],
        }

        for slot_id, slot in self.slots.items():
            val = inputs.get(slot_id)
            res = self.validate_input(slot_id, val, strict=strict)

            if not res["valid"]:
                report["is_valid"] = False
                report["hard_failures"].append(
                    {"slot_id": slot_id, "message": res["message"]}
                )
            elif res["severity"] == "soft":
                report["soft_warnings"].append(
                    {"slot_id": slot_id, "message": res["message"]}
                )
            else:
                report["successes"].append(
                    {"slot_id": slot_id, "message": res["message"]}
                )

        return report
