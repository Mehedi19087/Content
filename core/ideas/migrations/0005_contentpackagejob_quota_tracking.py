from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ideas", "0004_contentpackagejob_job_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentpackagejob",
            name="quota_period_end",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="contentpackagejob",
            name="quota_period_start",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="contentpackagejob",
            name="quota_status",
            field=models.CharField(
                choices=[
                    ("not_applicable", "Not applicable"),
                    ("reserved", "Reserved"),
                    ("consumed", "Consumed"),
                    ("refunded", "Refunded"),
                ],
                db_index=True,
                default="not_applicable",
                max_length=20,
            ),
        ),
    ]
