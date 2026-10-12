from django.db import transaction
from django.utils import timezone

from .models import AuditEvent, Organization, audit_entry_digest


def append_audit_event(*, organization_id, actor_user_id, action, object_type, object_id="", metadata=None):
    """Append one event while serializing writers on the owning organization row."""
    metadata = {} if metadata is None else metadata
    if not isinstance(metadata, dict):
        raise ValueError("Audit metadata must be a JSON object.")

    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization_id)
        previous = AuditEvent.objects.filter(organization_id=organization_id).order_by("-sequence").first()
        sequence = previous.sequence + 1 if previous else 1
        previous_hash = previous.entry_hash if previous else AuditEvent.GENESIS_HASH
        created_at = timezone.now()
        entry_hash = audit_entry_digest(
            organization_id=organization_id,
            sequence=sequence,
            actor_user_id=actor_user_id,
            action=action,
            object_type=object_type,
            object_id=str(object_id) if object_id != "" else "",
            metadata=metadata,
            created_at=created_at,
            previous_hash=previous_hash,
        )
        return AuditEvent.objects.create(
            organization_id=organization_id,
            sequence=sequence,
            actor_user_id=actor_user_id,
            action=action,
            object_type=object_type,
            object_id=str(object_id) if object_id != "" else "",
            metadata=metadata,
            created_at=created_at,
            previous_hash=previous_hash,
            entry_hash=entry_hash,
        )


def verify_audit_chain(organization_id):
    previous_hash = AuditEvent.GENESIS_HASH
    expected_sequence = 1
    checked_entries = 0

    for event in AuditEvent.objects.filter(organization_id=organization_id).order_by("sequence").iterator():
        actual_hash = audit_entry_digest(
            organization_id=event.organization_id,
            sequence=event.sequence,
            actor_user_id=event.actor_user_id,
            action=event.action,
            object_type=event.object_type,
            object_id=event.object_id,
            metadata=event.metadata,
            created_at=event.created_at,
            previous_hash=event.previous_hash,
        )
        if event.sequence != expected_sequence or event.previous_hash != previous_hash or event.entry_hash != actual_hash:
            return {
                "valid": False,
                "checked_entries": checked_entries,
                "first_invalid_sequence": event.sequence,
            }
        previous_hash = event.entry_hash
        expected_sequence += 1
        checked_entries += 1

    return {"valid": True, "checked_entries": checked_entries, "first_invalid_sequence": None}
