from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from pricing.models import PriceReport
from .models import WAUser, DealReportSession


@admin.register(WAUser)
class WAUserAdmin(admin.ModelAdmin):
    list_display = ("id", "role", "is_active", "last_seen", "date_joined")
    list_filter = ("role", "is_active")
    search_fields = ("id", "wa_last4")
    readonly_fields = ("wa_id_hash", "date_joined", "last_seen", "consent_ts")


@admin.register(DealReportSession)
class DealReportSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "step",
        "is_active",
        "store_link",
        "product_link",
        "price_report_link",
        "updated_at",
    )
    list_filter = ("is_active", "step")
    search_fields = ("user__display_name", "user__wa_last4", "data")
    readonly_fields = ("created_at", "updated_at", "data", "price_report_link")

    def store_link(self, obj: DealReportSession) -> str:
        report = self._get_price_report(obj)
        if report and report.store_id:
            url = reverse("admin:stores_store_change", args=[report.store_id])
            return format_html('<a href="{}">{}</a>', url, report.store)
        return (obj.data or {}).get("store_name", "") or "—"

    store_link.short_description = "Store"

    def product_link(self, obj: DealReportSession) -> str:
        report = self._get_price_report(obj)
        if report and report.product_id:
            url = reverse("admin:catalog_product_change", args=[report.product_id])
            return format_html('<a href="{}">{}</a>', url, report.product)
        return (obj.data or {}).get("product_name", "") or "—"

    product_link.short_description = "Product"

    def price_report_link(self, obj: DealReportSession) -> str:
        report_id = (obj.data or {}).get("price_report_id")
        if not report_id:
            return "—"
        url = reverse("admin:pricing_pricereport_change", args=[report_id])
        return format_html('<a href="{}">#{}</a>', url, report_id)

    price_report_link.short_description = "Price Report"

    def _get_price_report(self, obj: DealReportSession):
        if hasattr(obj, "_cached_price_report"):
            return obj._cached_price_report
        report_id = (obj.data or {}).get("price_report_id")
        if not report_id:
            obj._cached_price_report = None
        else:
            obj._cached_price_report = PriceReport.objects.filter(pk=report_id).select_related("store", "product").first()
        return obj._cached_price_report
