from __future__ import annotations

from decimal import Decimal
from typing import Optional

from django import forms
from django.utils.translation import gettext_lazy as _

from catalog.models import Product
from stores.models import Store, City
from pricing.models import PriceReport
from whatsapp.models import DealReportSession


class PriceReportFixForm(forms.Form):
    store = forms.ModelChoiceField(
        queryset=Store.objects.order_by("name"),
        required=False,
        label=_("Reassign store"),
    )
    product = forms.ModelChoiceField(
        queryset=Product.objects.order_by("name_he"),
        required=False,
        label=_("Reassign product"),
    )
    city = forms.ModelChoiceField(
        queryset=City.objects.order_by("name_he"),
        required=False,
        label=_("Assign city to store"),
        help_text=_("Pick an existing city to attach to the store."),
    )
    city_he = forms.CharField(
        required=False,
        label=_("City name (Hebrew)"),
    )
    city_en = forms.CharField(
        required=False,
        label=_("City name (English)"),
    )
    unit_type_he = forms.CharField(
        required=False,
        label=_("Unit type (Hebrew)"),
    )
    unit_type_en = forms.CharField(
        required=False,
        label=_("Unit type (English)"),
    )
    unit_quantity = forms.DecimalField(
        required=False,
        label=_("Unit quantity"),
        max_digits=6,
        decimal_places=2,
    )
    product_text_raw = forms.CharField(
        required=False,
        label=_("Product text (raw)"),
        help_text=_("Optional override of the free-text product field."),
    )

    def __init__(self, *args, report: PriceReport, **kwargs):
        self.report = report
        super().__init__(*args, **kwargs)
        self.fields["store"].initial = report.store_id
        self.fields["product"].initial = report.product_id
        self.fields["unit_type_en"].initial = report.unit_measure_type_en or report.unit_measure_type
        self.fields["unit_type_he"].initial = report.unit_measure_type_he
        self.fields["unit_quantity"].initial = report.unit_measure_quantity
        self.fields["product_text_raw"].initial = report.product_text_raw
        if report.store and report.store.city_obj_id:
            self.fields["city"].initial = report.store.city_obj_id
        self.fields["city_he"].initial = getattr(report.store, "city_he", "")
        self.fields["city_en"].initial = getattr(report.store, "city_en", "")

    def apply(self) -> None:
        report = self.report
        cleaned = self.cleaned_data
        update_fields: set[str] = set()

        target_store = cleaned.get("store") or report.store
        target_product = cleaned.get("product")

        if target_store and target_store.pk != report.store_id:
            report.store = target_store
            update_fields.add("store")

        if target_product and target_product.pk != report.product_id:
            report.product = target_product
            update_fields.add("product")

        unit_type_en = cleaned.get("unit_type_en")
        unit_type_he = cleaned.get("unit_type_he")
        unit_quantity = cleaned.get("unit_quantity")
        product_text_raw = cleaned.get("product_text_raw")

        if unit_type_en is not None:
            report.unit_measure_type_en = unit_type_en
            report.unit_measure_type = unit_type_en or report.unit_measure_type
            update_fields.update({"unit_measure_type_en", "unit_measure_type"})
        if unit_type_he is not None:
            report.unit_measure_type_he = unit_type_he
            if not unit_type_en:
                report.unit_measure_type = unit_type_he or report.unit_measure_type
                update_fields.add("unit_measure_type")
            update_fields.add("unit_measure_type_he")
        if unit_quantity is not None:
            report.unit_measure_quantity = unit_quantity
            update_fields.add("unit_measure_quantity")
        if product_text_raw is not None:
            report.product_text_raw = product_text_raw
            update_fields.add("product_text_raw")

        if update_fields:
            report.save(update_fields=list(update_fields))

        self._update_store_city(target_store or report.store)
        self._sync_session(report)

    def _update_store_city(self, store: Optional[Store]) -> None:
        if not store:
            return
        cleaned = self.cleaned_data
        city_choice: Optional[City] = cleaned.get("city")
        city_he = (cleaned.get("city_he") or "").strip()
        city_en = (cleaned.get("city_en") or "").strip()
        store_updates: set[str] = set()

        if city_choice:
            store.city_obj = city_choice
            store.city = city_choice.display_name
            store.city_he = city_choice.name_he
            store.city_en = city_choice.name_en
            store_updates.update({"city_obj", "city", "city_he", "city_en"})
        elif city_he or city_en:
            city_obj = store.city_obj
            if city_obj:
                obj_updates: set[str] = set()
                if city_he and city_he != city_obj.name_he:
                    city_obj.name_he = city_he
                    obj_updates.add("name_he")
                if city_en and city_en != city_obj.name_en:
                    city_obj.name_en = city_en
                    obj_updates.add("name_en")
                if obj_updates:
                    city_obj.save(update_fields=list(obj_updates))
            else:
                city_obj = City.objects.create(
                    name_he=city_he or city_en,
                    name_en=city_en or city_he,
                )
                store.city_obj = city_obj
                store_updates.add("city_obj")
            if city_he:
                store.city_he = city_he
                store_updates.add("city_he")
            if city_en:
                store.city_en = city_en
                store_updates.add("city_en")
            if city_he or city_en:
                store.city = city_he or city_en
                store_updates.add("city")

        if store_updates:
            store.save(update_fields=list(store_updates))

    def _sync_session(self, report: PriceReport) -> None:
        session = (
            DealReportSession.objects.filter(data__price_report_id=str(report.pk))
            .order_by("-updated_at")
            .first()
        )
        if not session:
            session = (
                DealReportSession.objects.filter(data__price_report_id=report.pk)
                .order_by("-updated_at")
                .first()
            )
        if not session:
            return
        data = dict(session.data or {})
        store = report.store
        if store:
            data["store_name"] = store.display_name or store.name
            if store.city_obj_id:
                data["city_id"] = str(store.city_obj_id)
            if store.city_he:
                data["city_he"] = store.city_he
            if store.city_en:
                data["city_en"] = store.city_en
            if store.city:
                data["city"] = store.city
        if report.unit_measure_type_en:
            data["unit_type"] = report.unit_measure_type_en
            data["unit_type_en"] = report.unit_measure_type_en
        if report.unit_measure_type_he:
            data["unit_type_he"] = report.unit_measure_type_he
        if report.unit_measure_quantity is not None:
            qty = Decimal(report.unit_measure_quantity).quantize(Decimal("0.01"))
            data["unit_quantity"] = str(qty)
        if report.product_text_raw:
            data["product_name"] = report.product_text_raw
        session.data = data
        session.save(update_fields=["data"])
