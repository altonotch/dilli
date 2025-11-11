from __future__ import annotations
from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm
from django.utils import timezone, translation
from django.utils.translation import gettext_lazy as _, gettext
from .models import PriceReport, StoreProductSnapshot
from whatsapp.utils import send_whatsapp_text


class PriceReportActionForm(ActionForm):
    rejection_reason = forms.CharField(
        required=False,
        label=_("Rejection reason"),
        help_text=_("Provide a reason when rejecting reports."),
    )


@admin.register(PriceReport)
class PriceReportAdmin(admin.ModelAdmin):
    change_list_template = "admin/pricing/pricereport/change_list.html"
    action_form = PriceReportActionForm
    list_display = (
        "id",
        "product",
        "store",
        "price",
        "units_in_price",
        "unit_measure_type",
        "unit_measure_quantity",
        "is_for_club_members_only",
        "min_cart_total",
        "needs_moderation",
        "moderated_at",
        "observed_at",
        "user",
        "source",
    )
    list_filter = (
        "source",
        "observed_at",
        "units_in_price",
        "is_for_club_members_only",
        "needs_moderation",
    )
    search_fields = (
        "product__name_he",
        "product__name_en",
        "store__name",
        "store__city",
        "store__city_he",
        "store__city_en",
        "store__city_obj__name_he",
        "store__city_obj__name_en",
    )
    autocomplete_fields = ("product", "store", "user")
    readonly_fields = ("created_at", "moderated_at", "moderated_by")
    date_hierarchy = "observed_at"
    actions = ["mark_reports_approved", "mark_reports_rejected"]

    @admin.action(description=_("Approve selected price reports"))
    def mark_reports_approved(self, request, queryset):
        updated = 0
        for report in queryset.select_related("product", "store", "user"):
            self._apply_moderation(report, request.user, approved=True)
            updated += 1
        self.message_user(
            request,
            _("Marked %(count)s report(s) as approved.") % {"count": updated},
            messages.SUCCESS,
        )

    @admin.action(description=_("Reject selected price reports"))
    def mark_reports_rejected(self, request, queryset):
        reason = request.POST.get("rejection_reason", "").strip()
        if not reason:
            self.message_user(
                request,
                _("Please provide a rejection reason in the action form."),
                messages.ERROR,
            )
            return
        updated = 0
        for report in queryset.select_related("product", "store", "user"):
            self._apply_moderation(report, request.user, approved=False, reason=reason)
            updated += 1
        self.message_user(
            request,
            _("Rejected %(count)s report(s).") % {"count": updated},
            messages.WARNING,
        )
        if request.POST.get("from_queue") == "1":
            return self._queue_response(request, queryset)

    def _apply_moderation(self, report: PriceReport, moderator, approved: bool, reason: str = "") -> None:
        now = timezone.now()
        report.needs_moderation = False
        report.moderated_at = now
        report.moderated_by = moderator
        report.moderation_reason = "" if approved else reason[:240]
        report.save(update_fields=["needs_moderation", "moderated_at", "moderated_by", "moderation_reason"])
        if approved:
            self._increment_snapshot(report)
            self._notify_user_approved(report)

    def _increment_snapshot(self, report: PriceReport) -> None:
        snapshot, created = StoreProductSnapshot.objects.get_or_create(
            product=report.product,
            store=report.store,
            defaults={
                "last_price": report.price,
                "last_observed_at": report.observed_at,
                "confirmation_count": 0,
            },
        )
        snapshot.last_price = report.price
        snapshot.last_observed_at = report.observed_at
        snapshot.confirmation_count = (snapshot.confirmation_count or 0) + 1
        snapshot.save(update_fields=["last_price", "last_observed_at", "confirmation_count"])

    def _notify_user_approved(self, report: PriceReport) -> None:
        user = report.user
        if not user or not getattr(user, "wa_number", ""):
            return
        locale = getattr(user, "locale", "en")
        try:
            with translation.override(locale):
                message = gettext(
                    "Your deal for %(product)s at %(store)s (%(price)s₪) was approved! "
                    "Thanks for helping everyone save."
                ) % {
                    "product": report.product_text_raw or report.product.name_he,
                    "store": report.store.display_name or report.store.name,
                    "price": report.price,
                }
            send_whatsapp_text(user.wa_number, message)
        except Exception:
            # Don't let messaging failures break admin actions
            pass


@admin.register(StoreProductSnapshot)
class StoreProductSnapshotAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "store", "last_price", "last_observed_at", "confirmation_count", "updated_at")
    search_fields = (
        "product__name_he",
        "product__name_en",
        "store__name",
        "store__city",
        "store__city_he",
        "store__city_en",
        "store__city_obj__name_he",
        "store__city_obj__name_en",
    )
    list_filter = ("last_observed_at",)
    autocomplete_fields = ("product", "store")
    def changelist_view(self, request, extra_context=None):
        if request.GET.get("moderation_queue") == "1":
            extra_context = extra_context or {}
            extra_context["queue"] = self._build_queue()
        return super().changelist_view(request, extra_context=extra_context)

    def _build_queue(self):
        pending = PriceReport.objects.filter(needs_moderation=True).select_related("product", "store", "user")
        queue = []
        for report in pending:
            queue.append(
                {
                    "report": report,
                    "session_data": self._fetch_session_data(report),
                }
            )
        return queue

    def _fetch_session_data(self, report: PriceReport) -> dict:
        session = report.user.deal_sessions.filter(
            data__price_report_id=report.id
        ).order_by("-updated_at").first() if report.user_id else None
        return session.data if session else {}

    def _queue_response(self, request, queryset):
        return self.changelist_view(request, extra_context={"queue": self._build_queue(), "from_queue": True})
