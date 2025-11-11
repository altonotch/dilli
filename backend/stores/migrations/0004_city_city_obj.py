from django.db import migrations, models
import django.db.models.deletion
from django.utils.text import slugify

def _allocate_slug(City, base_name: str) -> str:
    base_slug = slugify(base_name or "city", allow_unicode=True) or "city"
    candidate = base_slug
    counter = 1
    while City.objects.filter(slug=candidate).exists():
        counter += 1
        candidate = f"{base_slug}-{counter}"
    return candidate


def create_city_records(apps, schema_editor):
    City = apps.get_model("stores", "City")
    Store = apps.get_model("stores", "Store")
    for store in Store.objects.all():
        names = {
            "he": (store.city_he or "").strip(),
            "en": (store.city_en or "").strip(),
            "fallback": (store.city or "").strip(),
        }
        base_name = names["he"] or names["en"] or names["fallback"]
        if not base_name:
            continue
        city = (
            City.objects.filter(name_he__iexact=names["he"]).first()
            or City.objects.filter(name_en__iexact=names["en"]).first()
            or City.objects.filter(name_en__iexact=base_name).first()
            or City.objects.filter(name_he__iexact=base_name).first()
        )
        if not city:
            slug_value = _allocate_slug(City, base_name)
            city = City.objects.create(
                name_he=names["he"] or base_name,
                name_en=names["en"] or base_name,
                slug=slug_value,
            )
        store.city_obj_id = city.id
        store.save(update_fields=["city_obj"])


class Migration(migrations.Migration):

    dependencies = [
        ("stores", "0003_store_city_translations"),
    ]

    operations = [
        migrations.CreateModel(
            name="City",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name_he", models.CharField(blank=True, max_length=120)),
                ("name_en", models.CharField(blank=True, max_length=120)),
                ("slug", models.SlugField(blank=True, max_length=160, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "City",
                "verbose_name_plural": "Cities",
            },
        ),
        migrations.AddIndex(
            model_name="city",
            index=models.Index(fields=["name_he"], name="stores_city_name_he_idx"),
        ),
        migrations.AddIndex(
            model_name="city",
            index=models.Index(fields=["name_en"], name="stores_city_name_en_idx"),
        ),
        migrations.AddField(
            model_name="store",
            name="city_obj",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="stores", to="stores.city"),
        ),
        migrations.RunPython(create_city_records, migrations.RunPython.noop),
    ]
