"""Shared exception types."""


class ComplianceError(Exception):
    """Raised when a target must not be reconstructed for legal/policy reasons
    (e.g. its robots.txt disallows crawling). Not a transient failure — callers
    should fail the job permanently rather than retry."""
