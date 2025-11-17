from django.db import migrations, models


def copy_unit_types(apps, schema_editor):
    PriceReport = apps.get_model("pricing", "PriceReport")
    for report in PriceReport.objects.exclude(unit_measure_type=""):
        updated = False
        if not report.unit_measure_type_he:
            report.unit_measure_type_he = report.unit_measure_type
            updated = True
        if not report.unit_measure_type_en:
            report.unit_measure_type_en = report.unit_measure_type
            updated = True
        if updated:
            report.save(update_fields=["unit_measure_type_he", "unit_measure_type_en"])


class Migration(migrations.Migration):

    dependencies = [
        ("pricing", "0006_pricereport_unit_measure_quantity_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="pricereport",
            name="unit_measure_type_en",
            field=models.CharField(blank=True, help_text="Unit label for English experiences.", max_length=30),
        ),
        migrations.AddField(
            model_name="pricereport",
            name="unit_measure_type_he",
            field=models.CharField(blank=True, help_text="Unit label for Hebrew experiences.", max_length=30),
        ),
        migrations.RunPython(copy_unit_types, migrations.RunPython.noop),
    ]
