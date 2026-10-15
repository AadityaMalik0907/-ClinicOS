from django.conf import settings
from django.db.models import Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException

from .models import Organization, Patient, UsageEvent


class PlanLimitExceeded(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "plan_limit_exceeded"

    def __init__(self, *, metric, limit, used):
        super().__init__({
            "message": "This clinic has reached its plan limit.",
            "metric": metric,
            "limit": limit,
            "used": used,
        }, code=self.default_code)


def month_window(now=None):
    now = now or timezone.now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1)
    else:
        next_month = start.replace(month=start.month + 1)
    return start, next_month


def plan_limits(plan):
    if plan == Organization.Plan.FREE:
        return {
            "patients": settings.FREE_PATIENT_LIMIT,
            "encounters_monthly": settings.FREE_ENCOUNTERS_MONTHLY_LIMIT,
        }
    # Pro is unmetered for these learning-project quotas; request throttles still apply.
    return {"patients": None, "encounters_monthly": None}


def record_usage(*, organization_id, actor_user_id, metric):
    return UsageEvent.objects.create(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        metric=metric,
        quantity=1,
    )


def check_patient_limit(organization):
    limit = plan_limits(organization.plan)["patients"]
    used = Patient.objects.filter(organization_id=organization.pk).count()
    if limit is not None and used >= limit:
        raise PlanLimitExceeded(metric="patients", limit=limit, used=used)


def check_encounter_limit(organization):
    limit = plan_limits(organization.plan)["encounters_monthly"]
    if limit is None:
        return
    month_start, _ = month_window()
    used = UsageEvent.objects.filter(
        organization_id=organization.pk,
        metric=UsageEvent.Metric.ENCOUNTER_CREATED,
        occurred_at__gte=month_start,
    ).aggregate(total=Sum("quantity"))["total"] or 0
    if used >= limit:
        raise PlanLimitExceeded(metric="encounters_monthly", limit=limit, used=used)


def usage_summary(organization):
    now = timezone.now()
    month_start, next_month = month_window(now)
    current_period = UsageEvent.objects.filter(
        organization_id=organization.pk,
        occurred_at__gte=month_start,
        occurred_at__lt=next_month,
    )
    return {
        "plan": organization.plan,
        "period_start": month_start.date().isoformat(),
        "period_end": next_month.date().isoformat(),
        "patients": {
            "current": Patient.objects.filter(organization_id=organization.pk).count(),
            "created_this_month": current_period.filter(
                metric=UsageEvent.Metric.PATIENT_CREATED,
            ).aggregate(total=Sum("quantity"))["total"] or 0,
            "limit": plan_limits(organization.plan)["patients"],
        },
        "encounters": {
            "created_this_month": current_period.filter(
                metric=UsageEvent.Metric.ENCOUNTER_CREATED,
            ).aggregate(total=Sum("quantity"))["total"] or 0,
            "limit": plan_limits(organization.plan)["encounters_monthly"],
        },
    }
