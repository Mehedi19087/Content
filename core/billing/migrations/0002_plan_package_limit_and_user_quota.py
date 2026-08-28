import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def populate_package_limits(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    limits = {
        "starter": 10,
        "starter-yearly": 10,
        "pro": 25,
        "pro-yearly": 25,
        "ultra": 45,
        "ultra-yearly": 45,
        "creator": 45,
        "creator-yearly": 45,
    }
    for slug, limit in limits.items():
        Plan.objects.filter(slug=slug).update(monthly_package_limit=limit)


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="plan",
            name="monthly_package_limit",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(populate_package_limits, migrations.RunPython.noop),
        migrations.CreateModel(
            name="UserPackageQuota",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("allowance", models.PositiveIntegerField(default=0)),
                ("remaining", models.PositiveIntegerField(default=0)),
                ("period_start", models.DateField()),
                ("period_end", models.DateField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="package_quota",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="userpackagequota",
            constraint=models.CheckConstraint(
                condition=models.Q(remaining__lte=models.F("allowance")),
                name="package_quota_remaining_lte_allowance",
            ),
        ),
        migrations.AddConstraint(
            model_name="userpackagequota",
            constraint=models.CheckConstraint(
                condition=models.Q(period_start__lt=models.F("period_end")),
                name="package_quota_valid_period",
            ),
        ),
    ]
